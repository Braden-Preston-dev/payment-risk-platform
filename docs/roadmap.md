# Payment Risk Platform (PRP) — Roadmap

This roadmap outlines the phased development plan for PRP.  
Each epic builds incrementally toward a production-style, reliable backend system.

The system evolves from a runnable infrastructure baseline into a realistic
multi-tenant payment processor simulator with reliability guarantees.

---

## EPIC 0 — Project Framing (Complete)

### Objective
Define the system contract, architecture, terminology, and implementation plan before writing production code.

### Deliverables

- `spec.md`
- `architecture.md`
- `glossary.md`
- `roadmap.md`

### Done Looks Like

- Clear behavioral guarantees documented
- High-level architecture diagram created
- System boundaries and reliability model defined
- Terminology standardized

---

## EPIC 1 — Local Infrastructure Bootstrapping (Complete)

### Objective
Establish a reproducible local development environment.

### Deliverables

- Repository structure
- FastAPI application skeleton
- Dockerfile for API
- Dockerfile for worker (placeholder)
- `docker-compose.yml` (API + Postgres + Redis + Worker)
- `/health` endpoint
- `.env.example`

### Done Looks Like

- `docker compose up --build` boots successfully
- `/health` returns `{ "status": "ok" }`
- Postgres volume persists across restarts
- Worker container runs

---

## EPIC 2 — Database Foundation

### Objective
Introduce durable storage and migration management.

### Deliverables

- SQLAlchemy setup
- Alembic migrations

Core tables:

- `tenants`
- `api_keys`

Tests:

- Migration rollback/forward tests
- Model unit tests

### Done Looks Like

- Migrations run successfully
- Tables created in Postgres
- Database layer accessible from API
- Transaction support working
- Tenant-scoped queries supported
- Tests pass

---

## EPIC 3 — Auth + Multi-Tenancy

### Objective
Implement API key authentication and strict tenant isolation.

### Deliverables

- API key middleware
- Tenant context propagation
- Tenant-scoped query enforcement
- Cross-tenant access tests

Basic logging:

- Request ID generation
- Consistent request logging

Tests:

- Auth middleware unit tests
- Cross-tenant access rejection tests
- Tenant-scoped query integration tests

### Done Looks Like

- Missing/invalid key → 401
- Cross-tenant access → 404
- All DB reads/writes include tenant_id filter
- API keys stored hashed
- Requests traceable via logs
- Tests pass

---

## EPIC 4 — Payments Core

### Objective
Model PaymentIntent + Charge lifecycle with enforced state transitions.

### Deliverables

Payment Models:

- PaymentIntent model
- Charge model

Endpoints:

- Create PaymentIntent
- Confirm PaymentIntent
- Retrieve PaymentIntent

Core Logic:

- Confirm logic
- State machine validation
- Transactional updates

Fraud Stub:

- Deterministic fraud decision stub (always allow)
- Fraud decision hook point for future engine

Tests:

- State machine transition tests
- PaymentIntent lifecycle integration tests
- Concurrent confirm attempt tests

### Done Looks Like

- PaymentIntent created successfully
- Confirm creates Charge attempt
- Only one succeeded Charge allowed
- Illegal transitions return 409
- Multiple failed Charges allowed for retry
- All operations tenant-scoped
- Transactions prevent inconsistent state
- Tests pass

---

## EPIC 5 — Idempotency

### Objective
Make write endpoints safe under retries.

### Deliverables

Database:

- `idempotency_keys` table

Infrastructure:

- Idempotency middleware
- Request fingerprint hashing
- Response replay support

Tests:

- Idempotency key replay tests
- Key conflict (same key, different body) tests
- Concurrent retry safety tests

### Done Looks Like

- Same key + same body → identical response
- Same key + different body → 409
- No duplicate Charges under concurrent retries
- Stored responses replay correctly
- Tests pass

---

## EPIC 6 — Redis Integration

### Objective
Add rate limiting and velocity controls.

### Deliverables

- Redis client integration
- Per-tenant rate limiting middleware
- Velocity counters
- TTL-based enforcement

Tests:

- Rate limit enforcement tests
- Redis unavailability fail-closed tests
- Velocity counter integration tests

### Done Looks Like

- Exceeding limits returns 429
- Redis unavailability → 503 (fail-closed)
- Redis contains no durable state
- Tenant isolation preserved
- Tests pass

---

## EPIC 7 — Background Jobs Framework

### Objective
Introduce a reliable background processing framework.

### Deliverables

Worker Infrastructure:

- Worker service boot logic
- Database polling loop
- Retry backoff implementation

Reliability Guarantees:

- Worker restart safety
- No lost jobs
- Idempotent processing

Tests:

- Job pickup and completion tests
- Retry backoff behavior tests
- Worker restart recovery tests

### Done Looks Like

- Worker polls for pending jobs
- Retry metadata updated correctly
- Worker restart does not lose state
- Failed jobs retried with backoff
- Tests pass

---

## EPIC 8 — Webhooks

### Objective
Deliver signed webhook events with durable retry semantics.

### Deliverables

Models:

- WebhookEndpoint model
- WebhookEvent model
- WebhookDelivery model

Infrastructure:

- HMAC signing
- Retry logic
- Dead-letter behavior

Tests:

- HMAC signature verification tests
- Retry and dead-letter behavior tests
- Event persistence before delivery tests

### Done Looks Like

- Events persisted before delivery
- HMAC signatures verifiable
- Non-2xx responses retried
- Dead-lettered after max attempts
- Delivery logs queryable
- Worker delivers events reliably
- Tests pass

---

## EPIC 9 — Fraud Engine (Rules-Based)

### Objective
Evaluate fraud risk deterministically before ML integration.

### Deliverables

- Rule evaluation engine
- Risk scoring
- Risk assessment persistence
- Decision mapping (allow/review/block)

Tests:

- Rule evaluation unit tests
- Risk scoring integration tests
- Fraud decision influence on payment outcome tests

### Done Looks Like

- Fraud decision stored per payment attempt
- Decision influences payment outcome
- Triggered rules persisted
- Confirm flow integrates fraud engine
- Tests pass

---

## EPIC 10 — ML Integration

### Objective
Introduce ML-based fraud scoring.

### Deliverables

- Baseline model training
- Feature extraction
- Inference integration
- Risk score override logic

Tests:

- ML inference integration tests
- Score override logic tests
- Deterministic + ML coexistence tests

### Done Looks Like

- Fraud decision incorporates ML score
- Model inference integrated into confirm flow
- Deterministic + ML scoring coexist
- Model inference latency acceptable
- Tests pass

---

## EPIC 11 — Observability + Polish + Synthetic Data

### Objective
Make the system production-grade in terms of observability, developer experience, and demo readiness.

### Deliverables

Observability:

- Structured logging improvements
- Metrics counters

Developer Experience:

- Demo script
- Example requests
- Documentation polish

Synthetic Data:

- Dataset generation scripts
- Realistic fraud scenarios

End-to-End Validation:

- Full payment lifecycle smoke test
- Cross-epic integration verification

### Done Looks Like

- Webhook delivery observable via logs
- Failure modes reproducible
- Project demo-ready for interviews
- Synthetic dataset supports demos