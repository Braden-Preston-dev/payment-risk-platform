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
