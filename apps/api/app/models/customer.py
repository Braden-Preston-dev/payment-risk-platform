from uuid import UUID as PyUUID

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IDMixin, TimestampMixin
from app.models.types import json_type


class Customer(Base, IDMixin, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_customers_tenant_external"),
        Index("ix_customers_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
        default=dict,
    )
