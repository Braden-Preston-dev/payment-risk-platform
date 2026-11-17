# Helpful Commands

All commands are run from the repo root unless noted.

## Alembic

```bash
# Generate a new migration
alembic -c apps/api/alembic.ini revision --autogenerate -m "<description>"

# Apply all pending migrations
alembic -c apps/api/alembic.ini upgrade head

# Rollback one migration
alembic -c apps/api/alembic.ini downgrade -1

# Show current migration state
alembic -c apps/api/alembic.ini current

# Show migration history
alembic -c apps/api/alembic.ini history
```

> **Note:** If you get `ModuleNotFoundError: No module named 'app'`, prefix the command with `PYTHONPATH=apps/api`.

## Docker

```bash
# Start all services
docker compose up -d

# Stop all services
docker compose down

# Rebuild and start
docker compose up -d --build

# View logs
docker compose logs -f api
```

## API (FastAPI)

```bash
# Run the API locally (from apps/api/)
uvicorn app.main:app --reload
```

## Tests

```bash
PYTHONPATH=apps/api .venv/bin/python -m pytest apps/api/tests
```

Set `TEST_DATABASE_URL` to an empty disposable Postgres database to include the
migration downgrade/upgrade round-trip test.

## Seed and demo

```bash
PYTHONPATH=apps/api .venv/bin/python -m app.seed
API_KEY=<the printed key> .venv/bin/python scripts/demo.py
.venv/bin/python scripts/generate_synthetic_data.py --rows 1000
.venv/bin/python scripts/train_fraud_model.py synthetic_payments.csv
```
