from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.core.config import settings
from app.worker import _payload_bytes, _record_failure


def test_worker_payload_is_canonical():
    event = SimpleNamespace(
        id=uuid4(),
        type="payment_intent.succeeded",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload={"object": {"amount": 100}},
    )
    first = _payload_bytes(event)
    second = _payload_bytes(event)
    assert first == second
    assert b'"type":"payment_intent.succeeded"' in first


def test_worker_failure_backoff_and_dead_letter():
    now = datetime.now(UTC)
    delivery = SimpleNamespace(
        attempt_count=1,
        status="pending",
        last_error=None,
        next_attempt_at=now,
    )
    _record_failure(delivery, "temporary error", now)
    assert delivery.status == "failed"
    assert delivery.next_attempt_at > now

    delivery.attempt_count = settings.WEBHOOK_MAX_ATTEMPTS
    _record_failure(delivery, "poison event", now)
    assert delivery.status == "dead_lettered"
