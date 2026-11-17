import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.idempotency import IdempotencyKey


_KEY_PATTERN = re.compile(r"^[\x21-\x7E]{1,255}$")


@dataclass(frozen=True)
class StoredResponse:
    status_code: int
    body: dict[str, Any]


def request_fingerprint(method: str, path: str, body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    value = f"{method.upper()}\n{path}\n{canonical}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def acquire_idempotency(
    db: Session,
    *,
    tenant_id: UUID,
    key: str | None,
    fingerprint: str,
) -> StoredResponse | None:
    if key is None:
        return None
    if not _KEY_PATTERN.fullmatch(key):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key must be 1-255 visible ASCII characters",
        )

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        lock_digest = hashlib.sha256(f"{tenant_id}:{key}".encode("utf-8")).digest()[:8]
        lock_id = int.from_bytes(lock_digest, byteorder="big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})

    existing = db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.tenant_id == tenant_id,
            IdempotencyKey.key == key,
        )
    )
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key was already used with a different request",
        )
    return StoredResponse(existing.response_status, existing.response_body)


def store_idempotency(
    db: Session,
    *,
    tenant_id: UUID,
    key: str | None,
    fingerprint: str,
    status_code: int,
    body: dict[str, Any],
) -> None:
    if key is None:
        return
    db.add(
        IdempotencyKey(
            tenant_id=tenant_id,
            key=key,
            request_fingerprint=fingerprint,
            response_status=status_code,
            response_body=body,
        )
    )
    db.flush()
