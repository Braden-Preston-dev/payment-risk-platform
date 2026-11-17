import json
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from starlette.requests import Request

from app.api.routes.payments import create_payment_intent, confirm_payment_intent
from app.models.payment import Charge, PaymentIntent
from app.models.tenant import Tenant
from app.schemas import PaymentIntentConfirm, PaymentIntentCreate


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL is required for PostgreSQL concurrency testing",
)


class ThreadSafeRedis:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.values: dict[str, int] = {}

    def eval(self, _: str, __: int, key: str, ttl_ms: int) -> list[int]:
        with self.lock:
            self.values[key] = self.values.get(key, 0) + 1
            return [self.values[key], int(ttl_ms)]


def _request(method: str, path: str) -> Request:
    request = Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "root_path": "",
            "scheme": "http",
            "query_string": b"",
            "headers": [],
            "client": ("test", 1),
            "server": ("test", 80),
        }
    )
    request.state.request_id = str(uuid4())
    return request


def test_postgres_serializes_idempotent_create_and_concurrent_confirm():
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "DATABASE_URL": os.environ["TEST_DATABASE_URL"], "PYTHONPATH": str(root)}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(root / "alembic.ini"), "upgrade", "head"],
        cwd=root,
        env=env,
        check=True,
    )

    engine = create_engine(os.environ["TEST_DATABASE_URL"], pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    with Session.begin() as db:
        tenant = Tenant(name=f"Concurrency {uuid4()}")
        db.add(tenant)
        db.flush()
        tenant_id = tenant.id

    create_barrier = threading.Barrier(2)

    def create_once() -> dict:
        with Session() as db:
            tenant = db.get(Tenant, tenant_id)
            create_barrier.wait()
            response = create_payment_intent(
                payload=PaymentIntentCreate(amount=2000, currency="usd"),
                request=_request("POST", "/v1/payment_intents"),
                tenant=tenant,
                db=db,
                idempotency_key="postgres-concurrent-create",
            )
            db.commit()
            return json.loads(response.body)

    with ThreadPoolExecutor(max_workers=2) as executor:
        created = list(executor.map(lambda _: create_once(), range(2)))
    assert created[0]["id"] == created[1]["id"]
    payment_id = UUID(created[0]["id"])

    confirm_barrier = threading.Barrier(2)
    redis = ThreadSafeRedis()

    def confirm_once() -> int:
        with Session() as db:
            tenant = db.get(Tenant, tenant_id)
            confirm_barrier.wait()
            try:
                response = confirm_payment_intent(
                    payment_intent_id=payment_id,
                    request=_request("POST", f"/v1/payment_intents/{payment_id}/confirm"),
                    tenant=tenant,
                    db=db,
                    redis=redis,
                    payload=PaymentIntentConfirm(),
                    idempotency_key=None,
                )
                db.commit()
                return response.status_code
            except HTTPException as exc:
                db.rollback()
                return exc.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = sorted(executor.map(lambda _: confirm_once(), range(2)))
    assert statuses == [200, 409]

    with Session.begin() as db:
        assert db.scalar(
            select(func.count(PaymentIntent.id)).where(PaymentIntent.tenant_id == tenant_id)
        ) == 1
        assert db.scalar(
            select(func.count(Charge.id)).where(
                Charge.tenant_id == tenant_id,
                Charge.status == "succeeded",
            )
        ) == 1
        tenant = db.get(Tenant, tenant_id)
        db.delete(tenant)
    engine.dispose()
