"""Run a small end-to-end payment lifecycle against a running PRP API."""

import json
import os
from uuid import uuid4

import httpx


def main() -> None:
    api_key = os.environ.get("API_KEY")
    if not api_key:
        raise SystemExit("Set API_KEY to a seeded PRP API key")
    base_url = os.environ.get("PRP_BASE_URL", "http://localhost:8000")
    headers = {"Authorization": f"Bearer {api_key}"}

    with httpx.Client(base_url=base_url, headers=headers, timeout=10) as client:
        customer = client.post(
            "/v1/customers",
            json={"email": "demo@example.com", "metadata": {"source": "demo"}},
        )
        customer.raise_for_status()

        create_key = f"demo-create-{uuid4()}"
        payment_payload = {
            "amount": 2500,
            "currency": "usd",
            "customer_id": customer.json()["id"],
        }
        payment = client.post(
            "/v1/payment_intents",
            headers={"Idempotency-Key": create_key},
            json=payment_payload,
        )
        payment.raise_for_status()
        replay = client.post(
            "/v1/payment_intents",
            headers={"Idempotency-Key": create_key},
            json=payment_payload,
        )
        replay.raise_for_status()
        assert replay.headers["Idempotency-Replayed"] == "true"
        assert replay.json() == payment.json()
        conflict = client.post(
            "/v1/payment_intents",
            headers={"Idempotency-Key": create_key},
            json={**payment_payload, "amount": 2600},
        )
        assert conflict.status_code == 409

        confirm_key = f"demo-confirm-{uuid4()}"
        confirmed = client.post(
            f"/v1/payment_intents/{payment.json()['id']}/confirm",
            headers={"Idempotency-Key": confirm_key},
            json={},
        )
        confirmed.raise_for_status()
        confirm_replay = client.post(
            f"/v1/payment_intents/{payment.json()['id']}/confirm",
            headers={"Idempotency-Key": confirm_key},
            json={},
        )
        confirm_replay.raise_for_status()
        assert confirm_replay.headers["Idempotency-Replayed"] == "true"
        assert confirm_replay.json() == confirmed.json()
        print(json.dumps(confirmed.json(), indent=2))


if __name__ == "__main__":
    main()
