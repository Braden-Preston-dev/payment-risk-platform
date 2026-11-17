# Payment Risk Platform

Payment Risk Platform (PRP) is a multi-tenant payment processor simulator built
with FastAPI, PostgreSQL, Redis, and a separate durable webhook worker. It
implements the contract in `docs/spec.md`: API-key authentication, tenant
isolation, idempotent payment writes, PaymentIntent/Charge lifecycle rules,
rate and velocity controls, deterministic fraud scoring, and signed at-least-once
webhook delivery. The rules engine is augmented by a small JSON logistic model;
the higher of the deterministic and model scores drives the decision.

## Run locally

```bash
cp .env.example .env
# Replace API_PEPPER and ADMIN_TOKEN in .env before use.
docker compose up --build
docker compose exec api python -m app.seed
```

The seed command prints an API key once. Store it and use it as a bearer token:

```bash
export API_KEY=prp_replace_me
curl http://localhost:8000/health
curl -X POST http://localhost:8000/v1/payment_intents \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: checkout-001" \
  -H "Content-Type: application/json" \
  -d '{"amount":2500,"currency":"usd","payment_method_type":"card"}'
```

Interactive OpenAPI documentation is available at `http://localhost:8000/docs`.

## API surface

- `GET /health`
- `POST /v1/customers`, `GET /v1/customers/{id}`
- `POST /v1/payment_intents`
- `POST /v1/payment_intents/{id}/confirm`
- `GET /v1/payment_intents/{id}`, `GET /v1/charges/{id}`
- `POST /v1/webhook_endpoints`, `GET /v1/webhook_endpoints`
- `GET /v1/webhook_deliveries`

All `/v1` endpoints require `Authorization: Bearer <API_KEY>`. Cross-tenant
lookups deliberately return 404. Creation and confirmation accept an optional
`Idempotency-Key`; reusing it with a different method/path/body returns 409.

Webhook endpoint creation returns its signing secret once. Deliveries include
`PRP-Timestamp`, `PRP-Event-Id`, and `PRP-Signature`. The signature format is
`t=<unix timestamp>,v1=<hex HMAC-SHA256>` over `timestamp + "." + raw_body`.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r apps/api/requirements-dev.txt
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests
.venv/bin/python scripts/generate_synthetic_data.py --output /tmp/training.csv
.venv/bin/python scripts/train_fraud_model.py /tmp/training.csv
```

The migration round-trip test is opt-in because it destroys its target schema:

```bash
TEST_DATABASE_URL=postgresql+psycopg://... \
  PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests/test_migrations.py
```

See [the product specification](docs/spec.md), [architecture](docs/architecture.md),
and [helpful commands](docs/commands.md) for the full contract and workflows.
