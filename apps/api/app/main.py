from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.routes.api_key import router as api_key_router
from app.api.routes.customers import router as customers_router
from app.api.routes.health import router as health_router
from app.api.routes.payments import charge_router, router as payments_router
from app.api.routes.webhooks import router as webhooks_router
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware, RequestSizeLimitMiddleware
from app.core.redis import close_redis


configure_logging("api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    close_redis()


app = FastAPI(title="Payment Risk Platform", version="0.1.0", lifespan=lifespan)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(RequestContextMiddleware)

app.include_router(health_router)
app.include_router(api_key_router)
app.include_router(customers_router)
app.include_router(payments_router)
app.include_router(charge_router)
app.include_router(webhooks_router)


@app.exception_handler(OperationalError)
async def database_unavailable(_: Request, __: OperationalError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "Database unavailable"},
    )

