# Payment Risk Platform

Payment Risk Platform (PRP) is a production-style, multi-tenant payment
processor simulator built with FastAPI, PostgreSQL, Redis, SQLAlchemy, Alembic,
and a separate webhook worker. It models the parts of a payment system where
correctness matters most: authentication, tenant isolation, safe retries,
concurrent state transitions, fraud decisions, durable event creation, and
at-least-once webhook delivery.

PRP does not move real money or connect to card networks. It is intended for
backend, infrastructure, reliability, and fraud-system development.

## Contents

- [Capabilities](#capabilities)
- [Quick start](#quick-start)
- [Architecture](#architecture)
- [How requests flow through the system](#how-requests-flow-through-the-system)
- [Payment lifecycle](#payment-lifecycle)
- [API reference](#api-reference)
- [Data model](#data-model)
- [Function and module reference](#function-and-module-reference)
- [Reliability and consistency](#reliability-and-consistency)
- [Security model](#security-model)
- [Performance characteristics](#performance-characteristics)
- [Configuration](#configuration)
- [Development and testing](#development-and-testing)
- [Operational commands](#operational-commands)
- [Project layout](#project-layout)

## Capabilities

- HMAC-peppered API-key authentication.
- Shared-table multi-tenancy with tenant-scoped reads and writes.
- Customer, PaymentIntent, Charge, risk, and webhook APIs.
- Concurrency-safe idempotency using PostgreSQL advisory transaction locks.
- PaymentIntent row locking during confirmation.
- A database-level partial unique index that allows only one successful Charge
  per PaymentIntent.
- Per-tenant Redis rate limits and confirmation velocity controls.
- Fail-closed behavior when Redis is unavailable.
- Deterministic fraud rules combined with a cached logistic-regression model.
- Persist-first webhook events and delivery records.
- HMAC-SHA256 webhook signing.
- HTTPS-only webhook endpoints with SSRF-oriented address validation.
- Retry backoff, strict HTTP timeouts, response-size limits, and dead-lettering.
- Structured JSON logs with request and entity correlation IDs.
- Docker Compose development environment with health checks and automatic
  migrations.

## Quick start

### Requirements

- Docker Engine with Docker Compose.
- Python 3.12 if running scripts or tests outside Docker.

### Start the complete stack

```bash
cp .env.example .env
# Replace API_PEPPER and ADMIN_TOKEN before using the environment.
docker compose up -d --build
docker compose ps
```

The API container applies Alembic migrations before starting Uvicorn. Compose
waits for PostgreSQL and Redis to become healthy, then starts the API and worker.

### Seed a tenant and API key

```bash
docker compose exec api python -m app.seed
```

The seed command prints the raw API key once. PRP stores only its keyed digest;
the raw key cannot be retrieved later.

```bash
export API_KEY=prp_replace_with_the_seeded_key
curl http://localhost:8000/health
```

### Create and confirm a payment

```bash
PAYMENT_RESPONSE=$(curl -sS -X POST http://localhost:8000/v1/payment_intents \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: checkout-001" \
  -H "Content-Type: application/json" \
  -d '{"amount":2500,"currency":"usd","payment_method_type":"card"}')

echo "$PAYMENT_RESPONSE"
```

Use the returned PaymentIntent ID to confirm it:

```bash
curl -X POST http://localhost:8000/v1/payment_intents/<payment_intent_id>/confirm \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: confirm-001" \
  -H "Content-Type: application/json" \
  -d '{}'
```

Interactive OpenAPI documentation is available at
`http://localhost:8000/docs`.

## Architecture

```mermaid
flowchart LR
    Client[API client] -->|Bearer API key| API[FastAPI service]
    API -->|durable transactions| PG[(PostgreSQL)]
    API -->|rate and velocity counters| Redis[(Redis)]
    Worker[Webhook worker] -->|poll due deliveries| PG
    Worker -->|signed HTTPS POST| Receiver[Webhook receiver]
    Receiver -->|2xx or failure| Worker
```

### Component responsibilities

| Component | Responsibility | State model |
|---|---|---|
| FastAPI API | Authentication, validation, tenant scoping, payment transitions, fraud evaluation, and durable event creation | Stateless between requests |
| PostgreSQL | Payments, customers, idempotency records, risk assessments, events, and delivery state | Authoritative durable state |
| Redis | Request rate counters and confirmation velocity counters | Ephemeral, TTL-bound state |
| Worker | Due-delivery polling, signing, outbound HTTP, retry scheduling, and dead-lettering | Stateless; retry state lives in PostgreSQL |
| Webhook receiver | Consumes tenant events and verifies signatures | External and non-authoritative |

The API and worker can be restarted without losing accepted payment or webhook
state. Redis can be rebuilt without losing durable business data, although the
service intentionally rejects rate-limited requests while Redis is unavailable.

## How requests flow through the system

### Common `/v1` request path

Every `/v1` request follows the same outer path:

1. `RequestSizeLimitMiddleware` rejects a body larger than the configured limit.
2. `RequestContextMiddleware` accepts a safe incoming `X-Request-Id` or creates
   one, adds it to the response, and emits a completion log.
3. `get_db()` opens a SQLAlchemy Session for the request.
4. `get_current_tenant()` parses the Bearer token, computes its HMAC digest, and
   finds an active API key and tenant.
5. `get_current_tenant()` performs one atomic Redis counter operation for the
   tenant-wide request limit.
6. The route executes tenant-scoped domain logic.
7. `get_db()` commits after a successful route or rolls back if any exception
   leaves the request.

Missing or invalid credentials return `401`. A resource belonging to another
tenant is indistinguishable from a missing resource and returns `404`.

### PaymentIntent creation

`POST /v1/payment_intents` connects the following functions:

1. `PaymentIntentCreate` validates amount, currency, customer ID, payment method,
   and metadata.
2. `request_fingerprint()` canonicalizes and hashes method, path, and body.
3. `acquire_idempotency()` takes a tenant/key advisory transaction lock when an
   `Idempotency-Key` is present.
4. A matching stored fingerprint replays the original status and body.
5. A different fingerprint for the same tenant/key returns `409`.
6. An optional customer reference is checked with `tenant_id` in the predicate.
7. The route inserts the PaymentIntent in `requires_confirmation` state.
8. `payment_intent_response()` builds the public representation.
9. `store_idempotency()` persists the response in the same transaction.
10. The request dependency commits the transaction.

No durable side effect exists outside the transaction, so another request using
the same idempotency key cannot observe or create a partial result.

### PaymentIntent confirmation

`POST /v1/payment_intents/{id}/confirm` is the main transactional workflow:

1. The request goes through authentication and the tenant request-rate counter.
2. Idempotency is acquired before payment state is changed.
3. The PaymentIntent is selected by both `id` and `tenant_id` using
   `SELECT ... FOR UPDATE`.
4. Only `requires_confirmation` and `failed` intents are confirmable.
5. A second Redis counter records confirmation velocity.
6. A pending Charge is inserted.
7. `extract_features()` derives the three ML features.
8. `predict_ml_score()` runs the cached JSON logistic model if it is available.
9. `evaluate_risk()` combines deterministic rules and the ML score.
10. A RiskAssessment is inserted for the Charge attempt.
11. The Charge and PaymentIntent become either `succeeded` or `failed`.
12. `create_webhook_event()` writes a PaymentIntent event and a Charge event,
    plus one delivery per enabled endpoint for each event.
13. The complete response is stored under the idempotency key.
14. PostgreSQL commits the payment, risk, events, deliveries, and idempotency
    record atomically.

Webhook HTTP calls never run in the API transaction. A webhook outage therefore
cannot roll back a successful payment.

### Webhook worker path

The worker repeatedly calls `process_one_delivery()`:

1. Select one due `pending` or `failed` delivery.
2. Use `FOR UPDATE SKIP LOCKED` so multiple workers do not process the same row
   concurrently.
3. Load the endpoint and event using their tenant IDs.
4. Increment `attempt_count` and set `last_attempt_at`.
5. Revalidate the endpoint URL before connecting.
6. Serialize a deterministic event envelope in `_payload_bytes()`.
7. Sign `timestamp + "." + raw_body` using the endpoint secret.
8. Send a non-redirecting HTTPS POST with a strict timeout.
9. Accept only 2xx responses and enforce a maximum response-body size.
10. Mark the row `delivered`, schedule a retry, or mark it `dead_lettered`.

The database row lock remains held during the outbound request. This makes
restart and duplicate-worker behavior simple and correct, but it is also an
important throughput tradeoff discussed in the performance section.

## Payment lifecycle

### PaymentIntent states

| Current state | Operation | Result |
|---|---|---|
| `requires_confirmation` | Confirm, allowed payment | `succeeded` |
| `requires_confirmation` | Confirm, decline/risk rejection | `failed` |
| `failed` | Retry confirmation | `succeeded` or `failed` |
| `succeeded` | Confirm | `409 Conflict` |
| `canceled` | Confirm | `409 Conflict` |

The implementation uses `processing` inside the confirmation transaction. It is
normally not externally visible because the final state is committed with the
same transaction.

### Charge rules

- A confirmation creates a new Charge attempt.
- Failed Charges are append-only and may accumulate across retries.
- The database partial unique index
  `uq_charges_one_success_per_intent` permits at most one succeeded Charge for a
  PaymentIntent, even if application-level concurrency logic regresses.
- `payment_method_type=card_declined` deterministically creates a failed Charge.

### Risk decisions

| Score | Decision | Payment result |
|---:|---|---|
| `0-49` | `allow` | May succeed unless the simulated payment method declines |
| `50-74` | `review` | Failed because v0 has no manual-review workflow |
| `75-100` | `block` | Failed with a risk failure code |

Rules currently score very high amounts, high amounts, and rapid confirmation
velocity. The final score is the greater of the rules score and model score.
If the model file is missing or invalid, PRP continues with rules only.

## API reference

All `/v1` routes require:

```http
Authorization: Bearer <API_KEY>
```

| Method and path | Purpose | Important behavior |
|---|---|---|
| `GET /health` | Liveness endpoint | Does not require authentication |
| `GET /db/ping` | Execute `SELECT 1` | Development database diagnostic |
| `POST /v1/customers` | Create a customer | Tenant-scoped; duplicate external ID returns `409` |
| `GET /v1/customers/{id}` | Retrieve a customer | Cross-tenant access returns `404` |
| `POST /v1/payment_intents` | Create a PaymentIntent | Supports `Idempotency-Key`; returns `201` |
| `POST /v1/payment_intents/{id}/confirm` | Create a Charge and evaluate risk | Supports `Idempotency-Key`; terminal states return `409` |
| `GET /v1/payment_intents/{id}` | Retrieve an intent with latest Charge and risk | Tenant-scoped |
| `GET /v1/charges/{id}` | Retrieve a Charge | Tenant-scoped |
| `POST /v1/webhook_endpoints` | Register an HTTPS endpoint | Returns signing secret once; validates public routing |
| `GET /v1/webhook_endpoints` | List endpoints | Never returns signing secrets |
| `GET /v1/webhook_deliveries` | List delivery state | Limit is clamped to `1-500` |
| `POST /tenants/{tenant_id}/api-keys` | Create a tenant API key | Requires `X-Admin-Token`; disabled with `404` if admin token is unset |

### Idempotency response behavior

- Same tenant, key, method, path, and canonical body: original response replayed.
- Same tenant and key with any different request fingerprint: `409 Conflict`.
- Replayed responses include `Idempotency-Replayed: true`.
- Keys must contain `1-255` visible ASCII characters.

### Webhook request format

```http
Content-Type: application/json
PRP-Event-Id: <event UUID>
PRP-Timestamp: <Unix timestamp>
PRP-Signature: t=<timestamp>,v1=<hex HMAC-SHA256>
```

Receivers should recompute HMAC-SHA256 over:

```text
<timestamp>.<exact raw request body>
```

Receivers must also deduplicate by event ID because delivery is at least once.

## Data model

| Model | Purpose | Important constraints/indexes |
|---|---|---|
| `Tenant` | Organization boundary | Unique indexed name |
| `APIKey` | Hashed tenant credential | Unique indexed digest; tenant index; active flag |
| `Customer` | Tenant end user | Tenant index; unique `(tenant_id, external_id)` |
| `PaymentIntent` | Payment lifecycle object | Positive amount; state check; tenant/customer indexes |
| `Charge` | Individual payment attempt | Positive amount; state check; one-success partial unique index |
| `IdempotencyKey` | Stored request fingerprint and response | Unique `(tenant_id, key)` |
| `RiskAssessment` | Score, decision, and triggered rules | Score range and decision checks |
| `WebhookEndpoint` | Tenant destination and signing secret | Unique `(tenant_id, url)` |
| `WebhookEvent` | Durable event payload | Tenant/creation-time index |
| `WebhookDelivery` | Per-event endpoint retry state | Unique `(event_id, endpoint_id)`; due-work index |

All business tables carry `tenant_id`. The API never relies on a client-provided
tenant ID for business-data access.

## Function and module reference

### Application entrypoint

[`apps/api/app/main.py`](apps/api/app/main.py)

| Function/object | Role |
|---|---|
| `lifespan()` | Runs application shutdown cleanup, including Redis connection-pool closure |
| `database_unavailable()` | Converts SQLAlchemy operational failures into sanitized `503` responses |
| `app` | Registers middleware, exception handlers, and all routers |

### Configuration and logging

[`apps/api/app/core/config.py`](apps/api/app/core/config.py)

- `Settings` parses environment variables with bounds for numeric controls.
- `settings` is the process-wide validated configuration instance.

[`apps/api/app/core/logging.py`](apps/api/app/core/logging.py)

- `JsonFormatter.format()` emits timestamp, level, service, message, and any
  structured correlation fields as compact JSON.
- `configure_logging()` installs the JSON formatter for the API or worker.

### Middleware

[`apps/api/app/core/middleware.py`](apps/api/app/core/middleware.py)

| Class/function | Role |
|---|---|
| `RequestSizeLimitMiddleware` | Enforces `Content-Length` and streamed-body byte limits before domain logic |
| `RequestContextMiddleware` | Creates/propagates request IDs, adds `X-Request-Id`, measures duration, and logs completion |
| `RequestBodyTooLarge` | Internal control-flow exception for streamed requests that cross the body limit |

The request-context middleware deliberately avoids logging Authorization headers,
API keys, webhook secrets, or request bodies.

### Security helpers

[`apps/api/app/core/security.py`](apps/api/app/core/security.py)

| Function | Role |
|---|---|
| `generate_api_key()` | Creates a cryptographically random `prp_` credential |
| `hash_api_key()` | Produces an HMAC-SHA256 digest using `API_PEPPER` |
| `verify_api_key()` | Constant-time comparison of a raw key and stored digest |
| `get_api_key_prefix()` | Returns the display-safe first eight characters |
| `generate_webhook_secret()` | Creates a random `whsec_` signing secret |
| `sign_webhook()` | Computes the timestamped HMAC signature header |

### Database lifecycle

[`apps/api/app/db/session.py`](apps/api/app/db/session.py) creates the shared
SQLAlchemy engine and Session factory. `pool_pre_ping=True` detects stale pooled
connections before use.

[`apps/api/app/db/__init__.py`](apps/api/app/db/__init__.py)

- `get_db()` yields one Session per request.
- A successful request commits during dependency cleanup.
- Any exception rolls the transaction back before closing the Session.

This dependency is the transaction boundary used by the API routes.

### Authentication and route dependencies

[`apps/api/app/api/dependencies.py`](apps/api/app/api/dependencies.py)

| Function/type | Role |
|---|---|
| `get_current_tenant()` | Authenticates the API key, loads the tenant, enforces the Redis request limit, and attaches tenant ID to request state |
| `require_admin_token()` | Constant-time verification for the out-of-band API-key creation route |
| `CurrentTenant` | Reusable typed FastAPI dependency |
| `DatabaseSession` | Reusable typed Session dependency |
| `RedisDependency` | Reusable typed Redis dependency |

### Redis counters

[`apps/api/app/core/redis.py`](apps/api/app/core/redis.py)

- `get_redis()` creates and caches a decoded Redis client with one-second socket
  and connection timeouts.
- `close_redis()` closes the cached client during API shutdown.
- `RedisClient` is a small protocol that keeps rate logic testable.

[`apps/api/app/core/rate_limit.py`](apps/api/app/core/rate_limit.py)

- `increment_counter()` executes one Lua script that performs `INCR`, sets the
  TTL on first use, reads the remaining TTL, and returns count plus retry time.
- `RateLimitUnavailableError` separates Redis dependency failures from normal
  limit rejection.
- `CounterResult` transports count and `Retry-After` data.

### Route functions

[`apps/api/app/api/routes/customers.py`](apps/api/app/api/routes/customers.py)

- `create_customer()` inserts a tenant Customer and converts duplicate external
  IDs into `409`.
- `get_customer()` retrieves by both customer ID and tenant ID.

[`apps/api/app/api/routes/payments.py`](apps/api/app/api/routes/payments.py)

- `_replayed_response()` returns stored idempotent responses with the replay
  header.
- `create_payment_intent()` performs customer validation, PaymentIntent insert,
  response serialization, and optional idempotency storage.
- `confirm_payment_intent()` owns row locking, velocity control, Charge creation,
  fraud integration, state changes, event creation, and response storage.
- `get_payment_intent()` retrieves a tenant PaymentIntent with latest attempt and
  assessment.
- `get_charge()` retrieves a tenant Charge.

[`apps/api/app/api/routes/webhooks.py`](apps/api/app/api/routes/webhooks.py)

- `_endpoint_response()` creates the secret-free endpoint representation.
- `create_webhook_endpoint()` validates the URL, creates a unique secret, and
  returns the secret only in the creation response.
- `list_webhook_endpoints()` lists tenant endpoints without secrets.
- `list_webhook_deliveries()` lists recent tenant delivery state.

[`apps/api/app/api/routes/api_key.py`](apps/api/app/api/routes/api_key.py)

- `create_api_key()` is an admin-protected bootstrap operation. It checks tenant
  existence, stores only the digest and prefix, and returns the raw key once.

[`apps/api/app/api/routes/health.py`](apps/api/app/api/routes/health.py)

- `health()` provides a dependency-free liveness response.
- `db_ping()` runs `SELECT 1` for a database connectivity check.

### Idempotency service

[`apps/api/app/services/idempotency.py`](apps/api/app/services/idempotency.py)

| Function/class | Role |
|---|---|
| `request_fingerprint()` | SHA-256 of method, path, and canonical JSON body |
| `acquire_idempotency()` | Validates the key, takes a PostgreSQL advisory transaction lock, detects conflicts, and returns stored responses |
| `store_idempotency()` | Stores status and JSON body inside the active business transaction |
| `StoredResponse` | Immutable stored-response value object |

The advisory-lock ID is derived from tenant ID plus idempotency key. Requests for
different keys do not block each other.

### Fraud rules and model

[`apps/api/app/services/risk.py`](apps/api/app/services/risk.py)

- `evaluate_risk()` applies amount and velocity rules, applies a higher ML score,
  clamps to `0-100`, and maps to allow/review/block.
- `RiskResult` carries the score, decision, and explainable triggered rules.

[`apps/api/app/services/ml.py`](apps/api/app/services/ml.py)

| Function/class | Role |
|---|---|
| `extract_features()` | Normalizes amount, velocity, and declined-method state |
| `LinearFraudModel.predict_score()` | Calculates a bounded logistic probability and converts it to `0-100` |
| `load_model()` | Loads and validates the JSON model; cached by path with `lru_cache` |
| `predict_ml_score()` | Rules-safe model entrypoint; returns `None` if the model cannot load |

The default model is stored at
[`models/fraud_model.json`](models/fraud_model.json). JSON is used instead of
pickle so model contents are inspectable and do not execute code when loaded.

### Webhook service

[`apps/api/app/services/webhooks.py`](apps/api/app/services/webhooks.py)

- `validate_webhook_url()` requires HTTPS, rejects credentials/fragments, resolves
  DNS, and rejects loopback, private, link-local, and other non-global addresses.
- `create_webhook_event()` inserts an event and fan-outs durable delivery rows to
  enabled endpoints in the current transaction.
- `UnsafeWebhookURLError` produces safe endpoint-validation errors.

### Response serialization

[`apps/api/app/services/serialization.py`](apps/api/app/services/serialization.py)

- `customer_response()` maps an ORM Customer to its public schema.
- `charge_response()` maps an ORM Charge to its public schema.
- `payment_intent_response()` loads the latest Charge and RiskAssessment and
  builds the nested API response.

### Worker functions

[`apps/api/app/worker.py`](apps/api/app/worker.py)

| Function | Role |
|---|---|
| `_payload_bytes()` | Creates deterministic compact JSON for signing and delivery |
| `_post_webhook()` | Validates URL, signs body, sends HTTPS without redirects, and enforces timeout/response limit |
| `_record_failure()` | Stores the error, applies exponential backoff, or dead-letters the row |
| `process_one_delivery()` | Claims and processes one due delivery transactionally |
| `_stop()` | Handles SIGTERM/SIGINT for a graceful loop exit |
| `run()` | Polls continuously and handles temporary PostgreSQL outages |

### Seed, demo, and model scripts

| Script/function | Role |
|---|---|
| `app.seed.seed()` | Creates or reuses the demo tenant and issues a new API key |
| `scripts/demo.py:main()` | Runs a real customer/payment flow and asserts idempotent replay/conflict behavior |
| `generate_synthetic_data.py:generate()` | Creates deterministic labeled payment scenarios |
| `train_fraud_model.py:train()` | Trains a small logistic model and writes auditable JSON weights |

## Reliability and consistency

### Transaction boundaries

Payment confirmation commits the following together:

- PaymentIntent state.
- Charge attempt.
- RiskAssessment.
- PaymentIntent and Charge webhook events.
- Delivery rows for enabled endpoints.
- Idempotency response.

If any database operation fails, all of these changes roll back. Redis counters
are intentionally outside the database transaction and may still increment on a
failed database request; they are ephemeral operational controls, not business
records.

### Concurrency behavior

- The idempotency advisory lock serializes only one tenant/key pair.
- The PaymentIntent row lock serializes confirmations for one intent.
- A second concurrent confirmation observes the committed terminal state and
  returns `409`.
- The Charge partial unique index is the final database invariant against two
  successful Charges.
- Worker `SKIP LOCKED` claims allow multiple worker processes to poll the same
  delivery table without waiting on already-claimed rows.

### Failure behavior

| Failure | Behavior |
|---|---|
| PostgreSQL unavailable | Database-backed API operations return sanitized `503` |
| Redis unavailable | Authenticated rate-limited routes fail closed with `503` |
| Invalid/missing API key | `401` with Bearer challenge |
| Cross-tenant lookup | `404` without revealing existence |
| Duplicate idempotency key, same request | Original status/body replayed |
| Duplicate idempotency key, changed request | `409` |
| Webhook network/non-2xx/3xx failure | Error recorded and retry scheduled |
| Worker crash during attempt | Transaction rolls back; due delivery is eligible again |
| Maximum webhook attempts reached | Delivery becomes `dead_lettered` |

## Security model

- API keys are generated with `secrets.token_urlsafe()` and prefixed with `prp_`.
- API keys are stored as HMAC-SHA256 digests keyed by `API_PEPPER`.
- Comparisons for credentials use constant-time functions.
- Authorization headers, raw API keys, and signing secrets are not logged.
- Signing secrets appear only in the endpoint-creation response.
- Request bodies default to a maximum of 1 MiB.
- Webhook endpoints must resolve only to globally routable addresses and are
  revalidated immediately before delivery.
- HTTP redirects are not followed.
- Outbound response bodies and connection time are bounded.
- Error responses avoid database and network internals.

For a production deployment, store `API_PEPPER`, `ADMIN_TOKEN`, database
credentials, and webhook secrets in a managed secret system. Encryption at rest
for webhook signing secrets would be a logical next hardening step.

## Performance characteristics

### What has been verified

The repository has been validated with:

- 18 local API, service, signing, risk, worker, and model tests.
- A real PostgreSQL migration upgrade/downgrade/upgrade test.
- A real PostgreSQL concurrency test proving that concurrent idempotent creates
  collapse to one PaymentIntent and concurrent confirms yield one success.
- A live Docker Compose payment flow with creation replay, conflict detection,
  confirmation replay, Charge creation, and risk persistence.
- A live worker claim that durably transitioned a delivery.

These are correctness checks, not a capacity benchmark. No requests-per-second
or percentile-latency claim should be inferred from them.

### Single-run smoke observations

The structured API logs from one warm local Docker Compose validation run
reported the following server-side durations. Each row is one request, with no
concurrent load, so these values are useful only for understanding relative work
in the current implementation.

| Operation | Observed duration |
|---|---:|
| Customer creation | `8.12 ms` |
| PaymentIntent creation with idempotency | `10.26 ms` |
| PaymentIntent idempotent replay | `4.31 ms` |
| Changed-body idempotency conflict | `4.24 ms` |
| PaymentIntent confirmation | `14.29 ms` |
| Confirmation idempotent replay | `3.93 ms` |

These are not p50, p95, or p99 measurements. They exclude meaningful sustained
load, network diversity, slow webhook receivers, database growth, and resource
contention, and should not be used as a capacity target.

### Execution model

- API routes use synchronous SQLAlchemy Sessions. FastAPI executes synchronous
  route and dependency functions in its worker-thread pool.
- PostgreSQL connection management uses SQLAlchemy's QueuePool defaults with
  `pool_pre_ping` enabled. Pool sizes are not yet exposed as PRP settings.
- One API process is started by the development container. Additional API
  containers can share PostgreSQL and Redis because no request state is local.
- One worker process handles one delivery at a time in the provided Compose file.

### Hot-path operations

The following counts are approximate and exclude commit protocol details:

| Path | Redis work | PostgreSQL work | Growth characteristic |
|---|---:|---|---|
| Any authenticated request | 1 atomic `EVAL` | 1 indexed API-key/tenant lookup | Constant per request |
| Create PaymentIntent without customer/idempotency | Included above | 1 insert plus latest Charge/risk response lookups | Constant |
| Create with idempotency | Included above | Advisory lock, idempotency lookup, PaymentIntent insert, response insert | Constant; same key serializes |
| Confirm PaymentIntent | Request counter + velocity counter | Idempotency lookup, row lock, Charge/risk writes, latest lookups, 2 event writes, endpoint fan-out | `O(E)` for `E` enabled endpoints |
| Retrieve PaymentIntent | Included above | Intent lookup plus latest Charge and risk lookups | Constant in returned rows; may sort matching attempts |
| Worker delivery | None | Due-row claim, endpoint/event lookups, delivery update | One row per loop iteration |

Redis counter work is `O(1)` and one network round trip because increment, TTL
initialization, and TTL retrieval run in one Lua script.

### CPU cost

- API-key hashing and webhook signing are HMAC-SHA256 over small inputs.
- Request fingerprints are SHA-256 over a body capped at 1 MiB.
- Fraud inference is `O(F)` with three features and cached model weights.
- Webhook serialization is proportional to event-payload size.

For normal payment payloads, storage and network latency should dominate these
CPU operations. This expectation should still be confirmed with workload-specific
profiling before setting production capacity.

### Locking and contention

| Lock | Scope | Performance effect |
|---|---|---|
| Idempotency advisory transaction lock | One tenant and key | Duplicate retries wait; unrelated keys proceed |
| PaymentIntent `FOR UPDATE` | One PaymentIntent row | Concurrent confirms serialize by intent |
| Delivery `FOR UPDATE SKIP LOCKED` | One due delivery row | Other workers skip instead of waiting |

Holding a delivery row lock across the outbound HTTP call favors simple,
restart-safe correctness. Its costs are longer transactions, one occupied
database connection per in-flight delivery, and possible table bloat under a
large slow-webhook workload.

### Webhook throughput and latency

With one provided worker, steady-state webhook throughput is approximately
bounded by:

```text
1 / (database claim time + DNS/TLS/HTTP time + database update time)
```

The worker currently:

- Processes one delivery per loop call.
- Opens a new `httpx.Client` for every attempt, so it does not reuse HTTP/TLS
  connections.
- Sleeps for `WORKER_POLL_INTERVAL_SECONDS` only when no row was processed.
- Uses exponential retry delay:
  `WEBHOOK_BACKOFF_BASE_SECONDS * 2^(attempt_count - 1)`.
- Caps a single attempt with `WEBHOOK_TIMEOUT_MS`.

Horizontal workers improve parallelism because of `SKIP LOCKED`, up to limits
set by PostgreSQL connections, external endpoint latency, and local network
capacity.

Likely worker optimizations, in priority order, are:

1. Reuse a process-wide HTTP client for connection pooling.
2. Claim rows briefly, commit a lease, and perform HTTP outside the database
   transaction.
3. Process multiple deliveries concurrently with a bounded concurrency limit.
4. Add per-endpoint concurrency and circuit-breaker controls.
5. Partition or archive a very large delivery table.

### Database indexing and query growth

Current indexes cover tenant lookups, foreign keys, due delivery selection,
idempotency uniqueness, and successful-Charge uniqueness. The latest Charge and
RiskAssessment response queries filter by tenant/PaymentIntent and order by
creation time. At very high attempt counts, composite indexes such as
`(tenant_id, payment_intent_id, created_at DESC)` should be evaluated with
`EXPLAIN (ANALYZE, BUFFERS)`.

Webhook fan-out inserts two events per confirmation and up to `2 * E` delivery
rows for `E` enabled endpoints. Tenants with many endpoints increase confirmation
transaction time linearly.

### Scaling guidance

- Scale API containers horizontally when request concurrency exceeds one
  process's thread pool or database-pool capacity.
- Size the PostgreSQL pool across all API and worker replicas so aggregate
  maximum connections remain below the database limit.
- Scale workers separately from APIs based on due-delivery backlog and webhook
  latency.
- Monitor rate-limit Redis latency because every authenticated request depends
  on it and the service fails closed.
- Keep PostgreSQL and Redis close to the API network-wise; both are on the
  synchronous request path.
- Add retention/archival for events, deliveries, and idempotency records before
  long-running high-volume operation.

### Recommended benchmark method

A meaningful performance test should use a dedicated environment and report:

- Requests per second and error rate.
- API latency p50, p95, and p99.
- PostgreSQL query latency, lock wait time, connection utilization, and WAL rate.
- Redis command latency and connection errors.
- Worker attempts per second, delivery latency, retry backlog, and dead letters.
- CPU and memory per API/worker replica.

Use at least these workloads separately:

1. Authenticated reads.
2. Non-idempotent PaymentIntent creation.
3. Unique-key idempotent creation.
4. Duplicate retries of the same key.
5. Confirmations across many PaymentIntents.
6. Concurrent confirmations of one PaymentIntent.
7. Webhook delivery with fast, slow, failing, and timing-out receivers.

Do not benchmark against the default development Compose resource allocation and
then treat the result as production capacity.

## Configuration

Configuration is loaded from environment variables by `Settings`.

| Variable | Default | Purpose and performance impact |
|---|---:|---|
| `DATABASE_URL` | Local PostgreSQL URL | Durable source-of-truth connection |
| `REDIS_URL` | `redis://localhost:6379/0` | Rate/velocity Redis connection |
| `API_PEPPER` | Development-only placeholder | Keyed API-key digest; replace outside local development |
| `ADMIN_TOKEN` | Unset | Enables the admin API-key route when configured |
| `RATE_LIMIT_REQUESTS` | `120` | Tenant requests allowed per window |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Request-counter TTL/window |
| `VELOCITY_CONFIRM_LIMIT` | `10` | Confirms allowed per tenant velocity window |
| `VELOCITY_WINDOW_SECONDS` | `60` | Confirmation-counter TTL/window |
| `MAX_REQUEST_BODY_BYTES` | `1048576` | Maximum inbound body; bounds memory/hash work |
| `WEBHOOK_MAX_ATTEMPTS` | `5` | Attempts before dead-lettering |
| `WEBHOOK_TIMEOUT_MS` | `5000` | Maximum outbound attempt duration |
| `WEBHOOK_MAX_RESPONSE_BYTES` | `65536` | Maximum receiver response read |
| `WEBHOOK_BACKOFF_BASE_SECONDS` | `5` | First exponential retry delay |
| `WORKER_POLL_INTERVAL_SECONDS` | `1` | Empty-queue polling delay; lower values reduce pickup latency but increase DB polling |
| `ML_MODEL_PATH` | `models/fraud_model.json` | Optional JSON fraud model path |
| `SEED_TENANT_NAME` | `Demo Tenant` | Tenant name used by `app.seed` |

See [`.env.example`](.env.example) for a complete template.

## Development and testing

### Local Python setup

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r apps/api/requirements-dev.txt
```

### Run the normal suite

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests
```

SQLite is used for fast route/service coverage. PostgreSQL-only migration and
concurrency tests are skipped unless a disposable test database is supplied.

### Run PostgreSQL migration and concurrency tests

`TEST_DATABASE_URL` must point to a disposable database because the migration
test downgrades it to `base` before upgrading it again.

```bash
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/prp_test \
  PYTHONPATH=apps/api .venv/bin/python -m pytest \
  apps/api/tests/test_migrations.py \
  apps/api/tests/test_postgres_concurrency.py
```

### Run the live demo

```bash
API_KEY=<seeded-key> .venv/bin/python scripts/demo.py
```

The demo asserts:

- Customer creation.
- PaymentIntent creation.
- Same-request idempotency replay.
- Changed-request idempotency conflict.
- Confirmation and Charge creation.
- Confirmation replay.

### Generate data and train the fraud model

```bash
.venv/bin/python scripts/generate_synthetic_data.py \
  --rows 1000 \
  --output /tmp/training.csv

.venv/bin/python scripts/train_fraud_model.py /tmp/training.csv \
  --output models/fraud_model.json
```

Generation and training use fixed seeds so repeated runs are reproducible.

## Operational commands

### Service status and logs

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f worker
```

### Migration state

```bash
docker compose exec api alembic -c alembic.ini current
docker compose exec api alembic -c alembic.ini history
```

### Dependency checks

```bash
curl http://localhost:8000/health
curl http://localhost:8000/db/ping
docker compose exec redis redis-cli ping
```

### Stop the stack

```bash
docker compose down
```

Add `-v` only when intentionally deleting the PostgreSQL development volume.

## Project layout

```text
.
├── apps/
│   ├── api/
│   │   ├── alembic/              # Schema migrations
│   │   ├── app/
│   │   │   ├── api/              # Dependencies and route handlers
│   │   │   ├── core/             # Config, security, Redis, logging, middleware
│   │   │   ├── db/               # SQLAlchemy engine and request Session
│   │   │   ├── models/           # Durable ORM entities and constraints
│   │   │   ├── services/         # Idempotency, fraud, webhooks, serialization
│   │   │   ├── main.py           # FastAPI application
│   │   │   ├── seed.py           # Tenant/API-key seed command
│   │   │   └── worker.py         # Durable delivery worker
│   │   └── tests/                # Unit, API, migration, and concurrency tests
│   └── worker/Dockerfile          # Worker image
├── docs/                          # Product, architecture, glossary, roadmap
├── models/fraud_model.json        # Auditable fraud model artifact
├── scripts/                       # Demo, data generation, model training
├── docker-compose.yml             # API, worker, PostgreSQL, Redis
└── .env.example                   # Configuration template
```

## Further documentation

- [Product and technical specification](docs/spec.md)
- [Architecture](docs/architecture.md)
- [Roadmap](docs/roadmap.md)
- [Glossary](docs/glossary.md)
- [Helpful commands](docs/commands.md)
