import ipaddress
import socket
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.webhook import WebhookDelivery, WebhookEndpoint, WebhookEvent


class UnsafeWebhookURLError(ValueError):
    pass


def validate_webhook_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise UnsafeWebhookURLError("Webhook URL must use https")
    if parsed.username or parsed.password:
        raise UnsafeWebhookURLError("Webhook URL must not contain credentials")
    if parsed.fragment:
        raise UnsafeWebhookURLError("Webhook URL must not contain a fragment")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise UnsafeWebhookURLError("Webhook URL host is not publicly routable")

    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, parsed.port or 443)}
    except (OSError, ValueError) as exc:
        raise UnsafeWebhookURLError("Webhook URL host could not be resolved") from exc
    if not addresses:
        raise UnsafeWebhookURLError("Webhook URL host could not be resolved")

    for address in addresses:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        if not ip.is_global:
            raise UnsafeWebhookURLError("Webhook URL host is not publicly routable")


def create_webhook_event(
    db: Session,
    *,
    tenant_id: UUID,
    event_type: str,
    payload: dict,
) -> WebhookEvent:
    event = WebhookEvent(tenant_id=tenant_id, type=event_type, payload=payload)
    db.add(event)
    db.flush()

    endpoints = db.scalars(
        select(WebhookEndpoint).where(
            WebhookEndpoint.tenant_id == tenant_id,
            WebhookEndpoint.enabled.is_(True),
        )
    ).all()
    for endpoint in endpoints:
        db.add(
            WebhookDelivery(
                tenant_id=tenant_id,
                event_id=event.id,
                endpoint_id=endpoint.id,
            )
        )
    db.flush()
    return event
