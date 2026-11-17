import json
import logging
import signal
import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.logging import configure_logging
from app.core.security import sign_webhook
from app.db.session import SessionLocal
from app.models.webhook import WebhookDelivery, WebhookEndpoint, WebhookEvent
from app.services.webhooks import UnsafeWebhookURLError, validate_webhook_url


configure_logging("worker")
logger = logging.getLogger("prp.worker")
_running = True


def _payload_bytes(event: WebhookEvent) -> bytes:
    envelope = {
        "id": str(event.id),
        "type": event.type,
        "created_at": event.created_at.isoformat(),
        "data": event.payload,
    }
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _post_webhook(endpoint: WebhookEndpoint, event: WebhookEvent) -> None:
    validate_webhook_url(endpoint.url)
    body = _payload_bytes(event)
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "PRP-Event-Id": str(event.id),
        "PRP-Timestamp": str(timestamp),
        "PRP-Signature": sign_webhook(endpoint.signing_secret, timestamp, body),
    }
    timeout = httpx.Timeout(settings.WEBHOOK_TIMEOUT_MS / 1000)
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        with client.stream("POST", endpoint.url, content=body, headers=headers) as response:
            received = 0
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > settings.WEBHOOK_MAX_RESPONSE_BYTES:
                    raise RuntimeError("Webhook response exceeded size limit")
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"Webhook returned HTTP {response.status_code}")


def _record_failure(delivery: WebhookDelivery, error: str, now: datetime) -> None:
    delivery.last_error = error[:2000]
    if delivery.attempt_count >= settings.WEBHOOK_MAX_ATTEMPTS:
        delivery.status = "dead_lettered"
        return
    delivery.status = "failed"
    delay = settings.WEBHOOK_BACKOFF_BASE_SECONDS * (2 ** (delivery.attempt_count - 1))
    delivery.next_attempt_at = now + timedelta(seconds=delay)


def process_one_delivery() -> bool:
    now = datetime.now(UTC)
    with SessionLocal() as db, db.begin():
        delivery = db.scalar(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(("pending", "failed")),
                or_(
                    WebhookDelivery.next_attempt_at.is_(None),
                    WebhookDelivery.next_attempt_at <= now,
                ),
            )
            .order_by(WebhookDelivery.next_attempt_at, WebhookDelivery.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if delivery is None:
            return False

        endpoint = db.scalar(
            select(WebhookEndpoint).where(
                WebhookEndpoint.id == delivery.endpoint_id,
                WebhookEndpoint.tenant_id == delivery.tenant_id,
            )
        )
        event = db.scalar(
            select(WebhookEvent).where(
                WebhookEvent.id == delivery.event_id,
                WebhookEvent.tenant_id == delivery.tenant_id,
            )
        )
        delivery.attempt_count += 1
        delivery.last_attempt_at = now

        if endpoint is None or event is None:
            _record_failure(delivery, "Webhook endpoint or event no longer exists", now)
        elif not endpoint.enabled:
            delivery.status = "dead_lettered"
            delivery.last_error = "Webhook endpoint is disabled"
        else:
            try:
                _post_webhook(endpoint, event)
            except (httpx.HTTPError, RuntimeError, UnsafeWebhookURLError) as exc:
                _record_failure(delivery, str(exc), now)
            else:
                delivery.status = "delivered"
                delivery.last_error = None

        logger.info(
            "webhook delivery attempted",
            extra={
                "service": "worker",
                "tenant_id": str(delivery.tenant_id),
                "event_id": str(delivery.event_id),
                "delivery_id": str(delivery.id),
                "attempt_count": delivery.attempt_count,
                "webhook_status": delivery.status,
            },
        )
        return True


def _stop(_: int, __: object) -> None:
    global _running
    _running = False


def run() -> None:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    logger.info("worker started", extra={"service": "worker"})
    while _running:
        try:
            processed = process_one_delivery()
        except OperationalError:
            logger.exception("database unavailable", extra={"service": "worker"})
            processed = False
        if not processed:
            time.sleep(settings.WORKER_POLL_INTERVAL_SECONDS)
    logger.info("worker stopped", extra={"service": "worker"})


if __name__ == "__main__":
    run()
