from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select

from app.core.redis import get_redis
from app.main import app
from app.models.idempotency import IdempotencyKey
from app.models.payment import Charge
from app.models.risk import RiskAssessment
from app.models.webhook import WebhookDelivery, WebhookEvent


def test_health_and_request_id(test_context):
    response = test_context["client"].get("/health", headers={"X-Request-Id": "test-request"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-Id"] == "test-request"


def test_v1_requires_valid_api_key(test_context):
    client = test_context["client"]
    assert client.get("/v1/customers/00000000-0000-0000-0000-000000000000").status_code == 401
    assert (
        client.get(
            "/v1/customers/00000000-0000-0000-0000-000000000000",
            headers={"Authorization": "Bearer invalid"},
        ).status_code
        == 401
    )


def test_customer_is_tenant_scoped(test_context):
    client = test_context["client"]
    created = client.post(
        "/v1/customers",
        headers=test_context["headers_a"],
        json={"email": "buyer@example.com", "metadata": {"tier": "gold"}},
    )
    assert created.status_code == 201
    customer_id = created.json()["id"]
    assert client.get(f"/v1/customers/{customer_id}", headers=test_context["headers_a"]).status_code == 200
    assert client.get(f"/v1/customers/{customer_id}", headers=test_context["headers_b"]).status_code == 404


def test_payment_create_idempotency_and_conflict(test_context):
    client = test_context["client"]
    headers = {**test_context["headers_a"], "Idempotency-Key": "create-1"}
    first = client.post(
        "/v1/payment_intents",
        headers=headers,
        json={"amount": 1500, "currency": "USD"},
    )
    replay = client.post(
        "/v1/payment_intents",
        headers=headers,
        json={"currency": "USD", "amount": 1500},
    )
    conflict = client.post(
        "/v1/payment_intents",
        headers=headers,
        json={"amount": 1600, "currency": "USD"},
    )
    assert first.status_code == 201
    assert replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert first.json() == replay.json()
    assert conflict.status_code == 409

    with test_context["session_factory"]() as db:
        assert db.scalar(select(func.count(IdempotencyKey.id))) == 1


def test_confirm_is_transactional_idempotent_and_terminal(test_context):
    client = test_context["client"]
    created = client.post(
        "/v1/payment_intents",
        headers=test_context["headers_a"],
        json={"amount": 1500, "currency": "usd"},
    ).json()
    headers = {**test_context["headers_a"], "Idempotency-Key": "confirm-1"}
    first = client.post(
        f"/v1/payment_intents/{created['id']}/confirm",
        headers=headers,
    )
    replay = client.post(
        f"/v1/payment_intents/{created['id']}/confirm",
        headers=headers,
        json={},
    )
    terminal = client.post(
        f"/v1/payment_intents/{created['id']}/confirm",
        headers=test_context["headers_a"],
        json={},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "succeeded"
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert terminal.status_code == 409

    with test_context["session_factory"]() as db:
        assert db.scalar(select(func.count(Charge.id))) == 1
        assert db.scalar(select(func.count(RiskAssessment.id))) == 1
        assert db.scalar(select(func.count(WebhookEvent.id))) == 2


def test_failed_charges_can_be_retried(test_context):
    client = test_context["client"]
    created = client.post(
        "/v1/payment_intents",
        headers=test_context["headers_a"],
        json={"amount": 2000, "currency": "usd", "payment_method_type": "card_declined"},
    ).json()
    url = f"/v1/payment_intents/{created['id']}/confirm"
    first = client.post(url, headers=test_context["headers_a"], json={})
    second = client.post(url, headers=test_context["headers_a"], json={})
    assert first.json()["status"] == "failed"
    assert second.json()["status"] == "failed"
    with test_context["session_factory"]() as db:
        assert db.scalar(select(func.count(Charge.id))) == 2


def test_fraud_decision_changes_payment_outcome(test_context):
    client = test_context["client"]
    created = client.post(
        "/v1/payment_intents",
        headers=test_context["headers_a"],
        json={"amount": 1_000_000, "currency": "usd"},
    ).json()
    confirmed = client.post(
        f"/v1/payment_intents/{created['id']}/confirm",
        headers=test_context["headers_a"],
        json={},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "failed"
    assert body["latest_risk_assessment"]["decision"] == "block"
    assert body["latest_charge"]["failure_code"] == "risk_block"


def test_webhook_secret_is_write_only_and_events_create_deliveries(test_context, monkeypatch):
    monkeypatch.setattr("app.api.routes.webhooks.validate_webhook_url", lambda _: None)
    client = test_context["client"]
    endpoint = client.post(
        "/v1/webhook_endpoints",
        headers=test_context["headers_a"],
        json={"url": "https://hooks.example.test/payments"},
    )
    assert endpoint.status_code == 201
    assert endpoint.json()["signing_secret"].startswith("whsec_")
    listed = client.get("/v1/webhook_endpoints", headers=test_context["headers_a"])
    assert "signing_secret" not in listed.json()[0]

    payment = client.post(
        "/v1/payment_intents",
        headers=test_context["headers_a"],
        json={"amount": 1200, "currency": "usd"},
    ).json()
    client.post(
        f"/v1/payment_intents/{payment['id']}/confirm",
        headers=test_context["headers_a"],
        json={},
    )
    with test_context["session_factory"]() as db:
        assert db.scalar(select(func.count(WebhookDelivery.id))) == 2


def test_redis_failure_is_fail_closed(test_context):
    class BrokenRedis:
        def eval(self, *args, **kwargs):
            raise RedisConnectionError("offline")

    app.dependency_overrides[get_redis] = lambda: BrokenRedis()
    response = test_context["client"].post(
        "/v1/customers",
        headers=test_context["headers_a"],
        json={},
    )
    assert response.status_code == 503


def test_request_body_limit(test_context):
    response = test_context["client"].post(
        "/v1/customers",
        headers=test_context["headers_a"],
        content=b"x" * 1_048_577,
    )
    assert response.status_code == 413
