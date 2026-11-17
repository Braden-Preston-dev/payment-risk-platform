from datetime import UTC, datetime
from uuid import UUID as PyUUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, IDMixin, TimestampMixin
from app.models.types import json_type


class WebhookEndpoint(Base, IDMixin, TimestampMixin):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (
        UniqueConstraint("tenant_id", "url", name="uq_webhook_endpoint_tenant_url"),
    )

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    signing_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )


class WebhookEvent(Base, IDMixin, CreatedAtMixin):
    __tablename__ = "webhook_events"
    __table_args__ = (Index("ix_webhook_events_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(json_type(), nullable=False)


class WebhookDelivery(Base, IDMixin, CreatedAtMixin):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','delivered','failed','dead_lettered')",
            name="ck_webhook_delivery_status",
        ),
        UniqueConstraint("event_id", "endpoint_id", name="uq_delivery_event_endpoint"),
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
        Index("ix_webhook_deliveries_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("webhook_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attempt_count: Mapped[int] = mapped_column(nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
