from uuid import UUID as PyUUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.mixins import CreatedAtMixin, IDMixin
from app.models.types import json_type


class RiskAssessment(Base, IDMixin, CreatedAtMixin):
    __tablename__ = "risk_assessments"
    __table_args__ = (
        CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_risk_score"),
        CheckConstraint(
            "decision IN ('allow','review','block')",
            name="ck_risk_decision",
        ),
        Index("ix_risk_tenant_created", "tenant_id", "created_at"),
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
    charge_id: Mapped[PyUUID | None] = mapped_column(
        ForeignKey("charges.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    risk_score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    triggered_rules: Mapped[list] = mapped_column(json_type(), nullable=False, default=list)
