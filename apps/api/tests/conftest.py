from collections.abc import Generator
import asyncio

import anyio.to_thread
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.redis import get_redis
from app.core.security import hash_api_key
from app.db import get_db
from app.db.base import Base
from app.main import app
from app.models.api_key import APIKey
from app.models.tenant import Tenant


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}

    def eval(self, _: str, __: int, key: str, ttl_ms: int) -> list[int]:
        self.values[key] = self.values.get(key, 0) + 1
        return [self.values[key], int(ttl_ms)]


class ASGITestClient:
    def request(self, method: str, url: str, **kwargs) -> httpx.Response:
        async def send() -> httpx.Response:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                return await client.request(method, url, **kwargs)

        return asyncio.run(send())

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self.request("POST", url, **kwargs)


@pytest.fixture()
def test_context(monkeypatch) -> Generator[dict, None, None]:
    # The execution environment's AnyIO worker threads stall. Running the small,
    # in-memory SQLite test calls inline keeps the ASGI behavior deterministic.
    async def run_sync_inline(function, *args, **kwargs):
        return function(*args)

    monkeypatch.setattr(anyio.to_thread, "run_sync", run_sync_inline)
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)

    with TestingSession.begin() as db:
        tenant_a = Tenant(name="Tenant A")
        tenant_b = Tenant(name="Tenant B")
        db.add_all((tenant_a, tenant_b))
        db.flush()
        db.add_all(
            (
                APIKey(
                    tenant_id=tenant_a.id,
                    key_hash=hash_api_key("key-a"),
                    prefix="key-a",
                ),
                APIKey(
                    tenant_id=tenant_b.id,
                    key_hash=hash_api_key("key-b"),
                    prefix="key-b",
                ),
            )
        )

    fake_redis = FakeRedis()

    def override_db() -> Generator[Session, None, None]:
        db = TestingSession()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_redis] = lambda: fake_redis
    yield {
        "client": ASGITestClient(),
        "session_factory": TestingSession,
        "redis": fake_redis,
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "headers_a": {"Authorization": "Bearer key-a"},
        "headers_b": {"Authorization": "Bearer key-b"},
    }
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
