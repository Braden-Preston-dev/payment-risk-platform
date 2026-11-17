from uuid import UUID as PyUUID

from sqlalchemy import ForeignKey, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, IDMixin
from app.models.types import json_type


class IdempotencyKey(Base, IDMixin, CreatedAtMixin):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_idempotency_tenant_key"),
        Index("ix_idempotency_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    response_body: Mapped[dict] = mapped_column(json_type(), nullable=False)
