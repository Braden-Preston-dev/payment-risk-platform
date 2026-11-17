from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentTenant, DatabaseSession
from app.core.security import generate_webhook_secret
from app.models.webhook import WebhookDelivery, WebhookEndpoint
from app.schemas import (
    WebhookDeliveryResponse,
    WebhookEndpointCreate,
    WebhookEndpointCreated,
    WebhookEndpointResponse,
)
from app.services.webhooks import UnsafeWebhookURLError, validate_webhook_url


router = APIRouter(prefix="/v1", tags=["webhooks"])


def _endpoint_response(endpoint: WebhookEndpoint) -> WebhookEndpointResponse:
    return WebhookEndpointResponse(
        id=endpoint.id,
        url=endpoint.url,
        enabled=endpoint.enabled,
        created_at=endpoint.created_at,
        updated_at=endpoint.updated_at,
    )


@router.post(
    "/webhook_endpoints",
    response_model=WebhookEndpointCreated,
    status_code=status.HTTP_201_CREATED,
)
def create_webhook_endpoint(
    payload: WebhookEndpointCreate,
    tenant: CurrentTenant,
    db: DatabaseSession,
) -> WebhookEndpointCreated:
    try:
        validate_webhook_url(payload.url)
    except UnsafeWebhookURLError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    secret = generate_webhook_secret()
    endpoint = WebhookEndpoint(
        tenant_id=tenant.id,
        url=payload.url,
        signing_secret=secret,
        enabled=True,
    )
    db.add(endpoint)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Webhook endpoint already exists",
        ) from exc
    response = _endpoint_response(endpoint)
    return WebhookEndpointCreated(**response.model_dump(), signing_secret=secret)


@router.get("/webhook_endpoints", response_model=list[WebhookEndpointResponse])
def list_webhook_endpoints(
    tenant: CurrentTenant,
    db: DatabaseSession,
) -> list[WebhookEndpointResponse]:
    endpoints = db.scalars(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.tenant_id == tenant.id)
        .order_by(WebhookEndpoint.created_at.desc())
    ).all()
    return [_endpoint_response(endpoint) for endpoint in endpoints]


@router.get("/webhook_deliveries", response_model=list[WebhookDeliveryResponse])
def list_webhook_deliveries(
    tenant: CurrentTenant,
    db: DatabaseSession,
    limit: int = 100,
) -> list[WebhookDeliveryResponse]:
    limit = min(max(limit, 1), 500)
    deliveries = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.tenant_id == tenant.id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    ).all()
    return [
        WebhookDeliveryResponse(
            id=item.id,
            event_id=item.event_id,
            endpoint_id=item.endpoint_id,
            attempt_count=item.attempt_count,
            status=item.status,
            last_error=item.last_error,
            next_attempt_at=item.next_attempt_at,
            last_attempt_at=item.last_attempt_at,
            created_at=item.created_at,
        )
        for item in deliveries
    ]
