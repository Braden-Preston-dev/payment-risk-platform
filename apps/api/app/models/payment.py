from uuid import UUID as PyUUID

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, IDMixin, TimestampMixin
from app.models.types import json_type


PAYMENT_INTENT_STATUSES = (
    "requires_confirmation",
    "processing",
    "succeeded",
    "failed",
    "canceled",
)
CHARGE_STATUSES = ("pending", "succeeded", "failed")


class PaymentIntent(Base, IDMixin, TimestampMixin):
    __tablename__ = "payment_intents"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_payment_intents_amount_positive"),
        CheckConstraint(
            "status IN ('requires_confirmation','processing','succeeded','failed','canceled')",
            name="ck_payment_intents_status",
        ),
        Index("ix_payment_intents_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="requires_confirmation",
    )
    payment_method_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="card",
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        json_type(),
        nullable=False,
        default=dict,
    )


class Charge(Base, IDMixin, CreatedAtMixin):
    __tablename__ = "charges"
    __table_args__ = (
        CheckConstraint("amount > 0", name="ck_charges_amount_positive"),
        CheckConstraint(
            "status IN ('pending','succeeded','failed')",
            name="ck_charges_status",
        ),
        Index("ix_charges_tenant_created", "tenant_id", "created_at"),
        Index(
            "uq_charges_one_success_per_intent",
            "payment_intent_id",
            unique=True,
            postgresql_where=text("status = 'succeeded'"),
            sqlite_where=text("status = 'succeeded'"),
        ),
    )

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_intent_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("payment_intents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
