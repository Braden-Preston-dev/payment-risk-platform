import secrets
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import RateLimitUnavailableError, increment_counter
from app.core.redis import RedisClient, get_redis
from app.core.security import hash_api_key
from app.db import get_db
from app.models.api_key import APIKey
from app.models.tenant import Tenant


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_tenant(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
    redis: Annotated[RedisClient, Depends(get_redis)],
) -> Tenant:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant = db.scalar(
        select(Tenant)
        .join(APIKey, APIKey.tenant_id == Tenant.id)
        .where(
            APIKey.key_hash == hash_api_key(credentials.credentials),
            APIKey.is_active.is_(True),
        )
    )
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        result = increment_counter(
            redis,
            key=f"prp:rate:{tenant.id}",
            window_seconds=settings.RATE_LIMIT_WINDOW_SECONDS,
        )
    except RateLimitUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rate limit service unavailable",
        ) from exc

    if result.count > settings.RATE_LIMIT_REQUESTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )

    request.state.tenant_id = str(tenant.id)
    return tenant


def require_admin_token(
    token: Annotated[str | None, Header(alias="X-Admin-Token")] = None,
) -> None:
    if settings.ADMIN_TOKEN is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if token is None or not secrets.compare_digest(token, settings.ADMIN_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
DatabaseSession = Annotated[Session, Depends(get_db)]
RedisDependency = Annotated[RedisClient, Depends(get_redis)]
