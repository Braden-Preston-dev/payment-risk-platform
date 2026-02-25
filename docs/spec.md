# Payment Risk Platform -- Product & Technical Spec (v0)

## 1) Overview

**Payment Risk Platform (PRP)** is a production-style payment processor simulator inspired by Stripe. It exposes a tenant-scoped API for creating and confirming payments, evaluates fraud risk, applies rate limits / velocity controls, processes background jobs, and delivers signed webhooks with reliable retry semantics.

This system is intentionally designed to demonstrate backend/infra engineering depth:
- multi-tenant SaaS architecture
- API key auth + tenant isolation
- idempotent write endpoints
- payment lifecycle modeling (PaymentIntent + Charge)
- Redis for rate limiting + velocity tracking
- background job processing with retries
- fraud scoring (rules-based first)
- signed webhooks with delivery logs + dead-letter behavior
- Postgres as source of truth
- dockerized local dev environment

**Non-goal:** UI, dashboards, and CRUD demo scaffolding.

## 2) Goals (What success looks like)

By v0 completion, PRP should:
1. Support multiple tenants with strict data isolation.
2. Provide API key authentication with tenant context propagation.
3. Support idempotent payment endpoints where retries are safe.
4. Model a realistic PaymentIntent → Charge lifecycle with state transitions.
5. Enforce rate limits and maintain velocity counters using Redis.
6. Run background jobs in a separate worker service with retry behavior.
7. Evaluate fraud risk using a deterministic rules engine and persist assessments.
8. Deliver signed webhooks to tenant endpoints with:
   - delivery logs
   - exponential backoff retries
   - max attempts
   - dead-letter behavior
9. Be runnable locally with Docker Compose: API + Postgres + Redis + Worker.

## 3) Non-Goals (Explicitly out of scope for v0)

- No user accounts / UI login system
- No frontend dashboard
- No real card networks or PCI scope
- No real money movement or real chargebacks
- No multi-region deployment
- No high-scale performance benchmarks (but design should be scalable)
- ML fraud model is not required until EPIC 10

## 4) System Actors

- **Tenant**: a customer organization using PRP.
- **Tenant Admin (out of band)**: creates API keys and configures webhook endpoints (for v0, can be seeded via migration/seed scripts).
- **API Client**: service calling PRP endpoints (simulating a checkout flow).
- **Worker**: background processor for async tasks (captures, webhook delivery, fraud evaluation if async).
- **Webhook Receiver**: tenant-owned HTTP endpoint that receives PRP event notifications.

## 5) Core Concepts / Data Model (high level)

### 5.1 Tenant
Represents an isolated customer (organization). Every object in the system is scoped to a tenant.

### 5.2 API Key
Secret credential tied to a tenant. Used for authentication and request scoping.

### 5.3 Customer
Represents an end user of a tenant. Tenant-scoped.

### 5.4 PaymentIntent (PI)
Represents the intent to collect a payment. This is the primary object clients interact with.

A PaymentIntent models the *lifecycle* of a payment, not just a single charge attempt.

Illustrative fields:
- id
- tenant_id
- amount
- currency
- status (`requires_confirmation`, `processing`, `succeeded`, `failed`, `canceled`)
- payment_method_type (simulated)
- metadata (jsonb)
- created_at, updated_at

### 5.5 Charge
Represents a single attempt to charge funds for a PaymentIntent.

A PaymentIntent may have zero, one, or multiple Charges over its lifetime.

Illustrative fields:
- id
- tenant_id
- payment_intent_id
- amount
- currency
- status (`pending`, `succeeded`, `failed`)
- failure_code, failure_message
- created_at

### 5.6 Idempotency Key
Represents a stored idempotency record for safe retries on write endpoints.

Illustrative fields:
- id
- tenant_id
- key
- request_fingerprint (hash of method + path + body)
- response_status
- response_body
- created_at

### 5.7 Risk Assessment
Represents the fraud evaluation result for a payment attempt.

Illustrative fields:
- id
- tenant_id
- payment_intent_id
- charge_id (optional)
- risk_score (0–100)
- decision (`allow`, `review`, `block`)
- triggered_rules (jsonb)
- created_at

### 5.8 Webhook Endpoint
Represents a tenant-configured destination for webhook events.

Illustrative fields:
- id
- tenant_id
- url
- signing_secret
- enabled
- created_at

### 5.9 Webhook Event
Represents a durable record that something happened in the system.

Illustrative fields:
- id
- tenant_id
- type (`payment_intent.succeeded`, `charge.failed`, etc.)
- payload (jsonb)
- created_at

### 5.10 Webhook Delivery
Represents a single attempt to deliver an event to a webhook endpoint.

Illustrative fields:
- id
- tenant_id
- event_id
- endpoint_id
- attempt_count
- status (`pending`, `delivered`, `failed`, `dead_lettered`)
- last_error
- next_attempt_at
- last_attempt_at

## 6) API Surface (v0)

All endpoints are tenant-scoped via API key auth.

### Authentication
- `Authorization: Bearer <API_KEY>`

### 6.1 Health
- `GET /health` → 200 `{ "status": "ok" }`

### 6.2 Customers
- `POST /v1/customers`
- `GET /v1/customers/{id}`

### 6.3 PaymentIntents
- `POST /v1/payment_intents`
- `POST /v1/payment_intents/{id}/confirm`
- `GET /v1/payment_intents/{id}`

### 6.4 Charges
- `GET /v1/charges/{id}`

### 6.5 Webhook Endpoints (v0 can be seed-only or admin-only)
- (Optional) `POST /v1/webhook_endpoints`
- (Optional) `GET /v1/webhook_endpoints`

## 7) Key Behaviors & Guarantees

This section defines system invariants and reliability guarantees. These behaviors are considered part of the external contract and must be preserved as the system evolves.

### 7.1 Tenant Isolation Guarantee
A request authenticated as tenant A must never read or write objects belonging to tenant B.

Enforcement:
- API key authentication resolves a single `tenant_id` per request.
- All reads/updates/deletes must include `tenant_id = current_tenant_id` scoping.
- Cross-tenant resource access returns **404 Not Found** (do not reveal existence).

### 7.2 Authentication Guarantee
All `/v1/*` endpoints require API key authentication:
- Invalid or missing API key → **401 Unauthorized**
- Valid API key but resource not in tenant → **404 Not Found**

### 7.3 Idempotency Guarantee (Write Endpoints)
For write endpoints that create or mutate state, clients may provide an `Idempotency-Key` header.

Required behavior:
- Same tenant + same idempotency key + same request fingerprint → return the **original response** (status + body).
- Same tenant + same idempotency key + different request fingerprint → **409 Conflict**.
- Idempotency must be safe under concurrency (no duplicate side effects).

Applies to (v0 minimum):
- `POST /v1/payment_intents`
- `POST /v1/payment_intents/{id}/confirm`
(Optional) `POST /v1/customers`, `POST /v1/webhook_endpoints`

### 7.4 Payment State Machine Guarantee
PaymentIntent status transitions are validated and illegal transitions are rejected.

Example (simplified):
- `requires_confirmation` → `processing` → `succeeded`
- `requires_confirmation` → `canceled`
- `processing` → `succeeded` | `failed`

Rules:
- Client cannot arbitrarily set status.
- Confirming an already terminal PaymentIntent (e.g., 
- Confirm is allowed only when status is `requires_confirmation` or `failed` (retry).
- Confirming a terminal PaymentIntent (`succeeded`, `canceled`) returns **409 Conflict**.
- A PaymentIntent may have multiple failed Charges but at most one succeeded Charge.`succeeded`, `canceled`) returns **409 Conflict**.

### 7.5 Rate Limiting & Velocity Guarantee

Requests are rate-limited per tenant using Redis.

- Exceeding the limit returns **429 Too Many Requests**.
- Velocity counters are tracked in Redis with TTLs.
- Redis stores only ephemeral data.

Degraded mode:
- If Redis is unavailable, the system fails closed and returns **503 Service Unavailable**.

### 7.6 Webhook Delivery Semantics

Webhook delivery is **at-least-once**.

Delivery behavior:
- HTTP POST is sent to the configured endpoint.
- Only 2xx responses are treated as success.
- Redirect responses (3xx) are treated as failures.
- Delivery attempts use strict timeouts.
- After `max_attempts`, delivery transitions to **dead_lettered**.

Delivery behavior:
- A delivery attempt includes an HMAC signature header derived from the endpoint secret.
- Non-2xx responses and network errors are retried with backoff.
- After `max_attempts`, delivery transitions to **dead_lettered** and stops retrying.
- Delivery attempts are recorded (attempt_count, last_error, timestamps).

### 7.7 Webhook Signing Guarantee
Each webhook endpoint has a per-endpoint signing secret.

- Webhook requests include:
  - signature header (e.g., `PRP-Signature`)
  - timestamp header (recommended)
- Signature is computed as HMAC over a canonical payload (e.g., `timestamp + "." + raw_body`).
- Tenants can verify signatures independently.

Secret handling:
- `signing_secret` is returned only at endpoint creation time (and optionally on rotation).
- Secret is never returned in list/get endpoints.

### 7.8 Webhook Endpoint URL Safety (SSRF Mitigations)
To reduce SSRF risk, endpoint registration enforces:
- Only `https://` URLs are allowed.
- Host must not resolve to loopback, link-local, or private IP ranges.
- URL length and request body size limits are enforced.
- Delivery uses strict timeouts and does not follow redirects (or limits redirects to a small fixed count).

### 7.9 Background Worker Semantics
A separate worker service processes asynchronous jobs (e.g., webhook delivery, async payment tasks).

- Jobs are retried on failure with backoff.
- Worker must be safe to restart (no lost durable events; retries continue).
- Poison jobs can be dead-lettered (or marked failed) after max attempts.

### 7.10 Consistency Model
- Postgres is the source of truth for all durable state (payments, events, deliveries, risk assessments).
- Redis stores ephemeral counters/limits and may be rebuilt without data loss.
- The system prioritizes correctness and auditability over raw throughput.

## 8) Failure Modes

This section documents expected behavior when dependencies fail or unreliable network conditions occur.

### 8.1 Client Retries / Timeouts
If a client retries a write request due to timeout or network failure:
- With the same `Idempotency-Key` and identical request fingerprint, the API returns the original response.
- With the same `Idempotency-Key` but a different fingerprint, the API returns **409 Conflict**.

### 8.2 Postgres Unavailable
If Postgres is unavailable:
- The API returns **503 Service Unavailable** for endpoints that require DB access.
- The system does not attempt to accept writes without durable persistence.

### 8.3 Redis Unavailable (Fail-Closed)
If Redis is unavailable:
- Requests subject to rate limiting/velocity enforcement fail closed with **503 Service Unavailable**.

### 8.4 Worker Crash / Restart
If the worker crashes or restarts:
- Durable Webhook Events and Webhook Deliveries remain in Postgres.
- On restart, the worker resumes processing deliveries that are due for retry.

### 8.5 Webhook Receiver Failures
Webhook delivery may fail due to:
- network timeouts
- DNS failures
- connection errors
- non-2xx HTTP responses
- 3xx redirect responses (treated as failure)

Behavior:
- Failures are retried with backoff until `max_attempts` is reached.
- After `max_attempts`, delivery is marked **dead_lettered** and no further attempts occur.
- Each attempt updates delivery logs (attempt_count, last_error, timestamps).

### 8.6 Partial Failures During State Transitions
When confirming a PaymentIntent:
- The system ensures the PaymentIntent/Charge state transitions are durable in Postgres.
- Webhook delivery is asynchronous; webhook failures do not roll back successful payment state changes.

## 9) Security Considerations (v0)

### 9.1 API Key Handling
- API keys are required for all `/v1/*` endpoints.
- API keys should not be stored in plaintext in the database. Store a hashed form (e.g., HMAC with a server-side pepper) and compare hashes on lookup.
- The API must never log full API keys or `Authorization` headers.

### 9.2 Tenant Isolation
- All reads/writes must be tenant-scoped (`tenant_id = current_tenant_id`).
- Cross-tenant access must return 404 to avoid leaking resource existence.
- Tests must explicitly verify cross-tenant access is impossible.

### 9.3 Idempotency Abuse Prevention
- Idempotency keys are scoped by tenant.
- Reuse of the same idempotency key with a different request fingerprint returns 409.
- Request body size limits are enforced to prevent oversized payload abuse.

### 9.4 Webhook Signing Secrets
- Each webhook endpoint has a unique signing secret.
- Signing secrets are returned only at creation time (and optionally at rotation time).
- Secrets are never returned by list/get endpoints and must not appear in logs.

### 9.5 Webhook Endpoint URL Safety (SSRF Mitigation)
To reduce SSRF risk when tenants register webhook URLs:
- Only `https://` URLs are allowed.
- The host must not resolve to loopback, link-local, or private IP ranges.
- Requests use strict timeouts and maximum response size limits.
- Redirects are not followed (3xx treated as failure).
- (Optional) Enforce a maximum number of webhook endpoints per tenant.

### 9.6 Request & Response Limits
- Enforce maximum request size limits to protect the API and database.
- Enforce reasonable timeouts for outbound webhook delivery.
- Sanitize error messages so internal details are not leaked to clients.

### 9.7 Logging Hygiene
- Structured logs include `request_id`, `tenant_id`, and high-level event identifiers (e.g., `payment_intent_id`, `event_id`).
- Logs must avoid secrets: API keys, signing secrets, and raw authorization headers.

## 10) Observability (v0)

### 10.1 Structured Logging
The API and worker emit structured logs (JSON) to support filtering and debugging.

Log fields (minimum):
- `timestamp`
- `level`
- `service` (api|worker)
- `request_id` (API only)
- `tenant_id`
- primary entity ids when applicable (`payment_intent_id`, `charge_id`, `event_id`, `delivery_id`)
- outcome fields (`status_code`, `decision`, `webhook_status`, `attempt_count`)

Logs must not include secrets (API keys, signing secrets, authorization headers).

### 10.2 Metrics (lightweight)
The system tracks key counters (can be logs-first in v0; exportable later):
- requests_total, requests_failed_total
- rate_limit_block_total
- payment_intent_created_total
- payment_confirm_total, payment_confirm_failed_total
- fraud_decision_total (allow|review|block)
- webhook_delivery_attempt_total
- webhook_delivery_success_total
- webhook_delivery_dead_letter_total
- job_retry_total

### 10.3 Correlation / Traceability
- Each API request includes a `request_id` returned in responses (e.g., `X-Request-Id`).
- Worker logs include correlation fields (`event_id`, `delivery_id`) so webhook attempts can be traced from event creation to delivery outcomes.

## 11) Local Dev & Deployment

### 11.1 Local Environment
The system must run locally via Docker Compose, including:
- `api` (FastAPI)
- `postgres` (source of truth)
- `redis` (rate limiting + velocity)
- `worker` (async processing)

Developer workflow:
- `docker compose up` boots all services.
- `/health` returns `{"status":"ok"}` when the API is running.
- Database migrations are applied on startup (or via a dedicated migrate command).
- Seed data may create an initial tenant and API key for local development.

### 11.2 Configuration
Configuration is provided via environment variables:
- `DATABASE_URL`
- `REDIS_URL`
- `API_PEPPER` (for API key hashing, if used)
- `WEBHOOK_MAX_ATTEMPTS`
- `WEBHOOK_TIMEOUT_MS`
- `RATE_LIMIT_*` settings

A `.env.example` file documents required variables.

### 11.3 Deployment (future)
Production deployment targets container-based infrastructure (e.g., AWS ECS/Fargate):
- API and Worker run as separate services.
- Postgres provided by managed database (e.g., RDS).
- Redis provided by managed cache (e.g., ElastiCache).
- Logs emitted to platform logging (e.g., CloudWatch).