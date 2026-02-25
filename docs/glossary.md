# Payment Risk Platform (PRP) — Glossary

## Core Domain Terms

### Tenant
A customer organization using PRP.  
All durable objects in the system are scoped to exactly one `tenant_id`.

---

### API Key
A secret credential associated with a Tenant.  
Used to authenticate requests and derive tenant context.  
API keys are never stored in plaintext and are not logged.

---

### Tenant Context
The resolved `tenant_id` derived from API key authentication for a request.  
All database queries must be scoped using this value.

---

### Customer
A tenant-scoped representation of an end user making payments.  
Customers are not global; they exist only within a single Tenant.

---

## Payments Domain

### PaymentIntent (PI)
A lifecycle object representing the intent to collect payment.

Key characteristics:
- Durable
- Tenant-scoped
- Moves through controlled state transitions
- May accumulate multiple Charge attempts
- May have at most one succeeded Charge

Typical states (v0):
- `requires_confirmation`
- `processing`
- `succeeded`
- `failed`
- `canceled`

---

### Charge
A single attempt to collect funds for a PaymentIntent.

Key characteristics:
- Append-only
- Associated with exactly one PaymentIntent
- May succeed or fail
- Multiple failed Charges are allowed
- Only one succeeded Charge is allowed per PaymentIntent

---

### Terminal State
A PaymentIntent state from which no further transitions are allowed.

Terminal states (v0):
- `succeeded`
- `canceled`

Confirming a PaymentIntent in a terminal state results in `409 Conflict`.

---

## Reliability & Consistency

### Idempotency Key
A client-provided key used to make write operations safe for retries.

Behavior:
- Same tenant + same key + same request fingerprint → return original response
- Same tenant + same key + different fingerprint → `409 Conflict`

Idempotency prevents duplicate side effects during network retries.

---

### Request Fingerprint
A hash derived from:
- HTTP method
- request path
- canonicalized request body

Used to validate idempotency safety.

---

### At-Least-Once Delivery
Webhook delivery guarantee where events may be delivered more than once.

Implication: webhook receivers must be idempotent and handle duplicate deliveries safely.

---

### Dead Letter
A terminal state for a Webhook Delivery after max retry attempts are exhausted.

Dead-lettered deliveries are no longer retried but remain queryable for debugging.

---

### Fail-Closed
A degraded behavior mode where requests are rejected when a dependency is unavailable.

In PRP:  
If Redis is unavailable, requests subject to rate limiting fail with `503 Service Unavailable`.

---

### Durable State
State persisted in Postgres and considered authoritative.

Examples:
- PaymentIntents
- Charges
- Webhook Events
- Webhook Deliveries
- Idempotency records
- Risk Assessments

---

### Ephemeral State
Short-lived operational state that can be rebuilt without affecting correctness.

In PRP:
- Rate limit counters
- Velocity tracking data in Redis

---

## Webhooks

### Webhook Endpoint
A tenant-configured HTTPS URL that receives PRP event notifications.

Each endpoint has:
- Unique signing secret
- Enabled/disabled state

---

### Webhook Event
A durable record that something occurred in PRP.

Examples:
- `payment_intent.succeeded`
- `charge.failed`

Events are persisted before delivery attempts.

---

### Webhook Delivery
A single attempt to deliver a Webhook Event to a specific Webhook Endpoint.

Tracks:
- `attempt_count`
- `status`
- `last_error`
- `next_attempt_at`

---

### Signing Secret
A per-endpoint secret used to compute an HMAC signature for webhook payloads.

Returned only at creation time (write-only).

---

## System Components

### API Service
Synchronous HTTP service handling authentication, validation, and durable state changes.

---

### Worker Service
Asynchronous processor responsible for retrying webhook deliveries and background tasks.

Stateless and restart-safe.

---

### Source of Truth
The authoritative storage layer for durable state.

In PRP:  
Postgres.