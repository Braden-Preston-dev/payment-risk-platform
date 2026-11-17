from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import Boolean, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import IDMixin, TimestampMixin


class APIKey(Base, IDMixin, TimestampMixin):
    __tablename__ = "api_keys"

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        index=True,
    )

    key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    # Represents the first 8 characters of the API key for display purposes.
    prefix: Mapped[str] = mapped_column(String(8), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
