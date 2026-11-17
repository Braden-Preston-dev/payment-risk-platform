import hashlib
import hmac
import socket

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from app.core.rate_limit import RateLimitUnavailableError, increment_counter
from app.core.security import sign_webhook
from app.services.ml import LinearFraudModel, extract_features
from app.services.risk import evaluate_risk
from app.services.webhooks import UnsafeWebhookURLError, validate_webhook_url


def test_webhook_signature_is_verifiable():
    body = b'{"ok":true}'
    signature = sign_webhook("secret", 1234, body)
    expected = hmac.new(b"secret", b"1234." + body, hashlib.sha256).hexdigest()
    assert signature == f"t=1234,v1={expected}"


def test_risk_rules_are_deterministic():
    assert evaluate_risk(amount=1000, velocity_count=1).decision == "allow"
    assert evaluate_risk(amount=250_000, velocity_count=1).decision == "review"
    assert evaluate_risk(amount=1_000_000, velocity_count=1).decision == "block"
    assert evaluate_risk(amount=1000, velocity_count=1, ml_score=80).decision == "block"


def test_ml_feature_extraction_and_inference():
    features = extract_features(
        amount=1_000_000,
        velocity_count=10,
        payment_method_type="card",
    )
    model = LinearFraudModel(
        intercept=-4,
        weights={"amount_ratio": 4, "velocity_ratio": 8},
    )
    assert features.amount_ratio == 1
    assert features.velocity_ratio == 1
    assert model.predict_score(features) >= 99


def test_webhook_url_rejects_private_addresses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    with pytest.raises(UnsafeWebhookURLError):
        validate_webhook_url("https://example.com/hook")


def test_webhook_url_accepts_public_https(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    validate_webhook_url("https://example.com/hook")


def test_rate_limit_dependency_failure_is_wrapped():
    class BrokenRedis:
        def eval(self, *args, **kwargs):
            raise RedisConnectionError("offline")

    with pytest.raises(RateLimitUnavailableError):
        increment_counter(BrokenRedis(), key="test", window_seconds=60)
