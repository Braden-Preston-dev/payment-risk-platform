from uuid import UUID as PyUUID

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import ForeignKey, String

from app.db.base import Base
from app.models.mixins import TimestampMixin, IDMixin


class APIKey(Base, IDMixin, TimestampMixin):
    __tablename__ = "api_keys"

    tenant_id: Mapped[PyUUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        unique=True,
    )

    key_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    # Represemts the first 8 characters of the API key for display purposes 
    prefix: Mapped[str] = mapped_column(String(8), nullable=False)

    
