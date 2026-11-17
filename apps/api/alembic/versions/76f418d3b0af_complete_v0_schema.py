"""complete v0 schema

Revision ID: 76f418d3b0af
Revises: b2aae8380cd7
Create Date: 2026-11-16 18:45:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "76f418d3b0af"
down_revision: Union[str, Sequence[str], None] = "b2aae8380cd7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "api_keys",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "api_keys",
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])

    op.create_table(
        "customers",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "external_id", name="uq_customers_tenant_external"),
    )
    op.create_index("ix_customers_tenant_id", "customers", ["tenant_id"])
    op.create_index("ix_customers_tenant_created", "customers", ["tenant_id", "created_at"])

    op.create_table(
        "payment_intents",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=True),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payment_method_type", sa.String(length=64), nullable=False),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_payment_intents_amount_positive"),
        sa.CheckConstraint(
            "status IN ('requires_confirmation','processing','succeeded','failed','canceled')",
            name="ck_payment_intents_status",
        ),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_intents_tenant_id", "payment_intents", ["tenant_id"])
    op.create_index("ix_payment_intents_customer_id", "payment_intents", ["customer_id"])
    op.create_index(
        "ix_payment_intents_tenant_created",
        "payment_intents",
        ["tenant_id", "created_at"],
    )

    op.create_table(
        "charges",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("payment_intent_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.String(length=500), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("amount > 0", name="ck_charges_amount_positive"),
        sa.CheckConstraint("status IN ('pending','succeeded','failed')", name="ck_charges_status"),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"], ["payment_intents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_charges_tenant_id", "charges", ["tenant_id"])
    op.create_index("ix_charges_payment_intent_id", "charges", ["payment_intent_id"])
    op.create_index("ix_charges_tenant_created", "charges", ["tenant_id", "created_at"])
    op.create_index(
        "uq_charges_one_success_per_intent",
        "charges",
        ["payment_intent_id"],
        unique=True,
        postgresql_where=sa.text("status = 'succeeded'"),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.SmallInteger(), nullable=False),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "key", name="uq_idempotency_tenant_key"),
    )
    op.create_index("ix_idempotency_keys_tenant_id", "idempotency_keys", ["tenant_id"])
    op.create_index(
        "ix_idempotency_tenant_created", "idempotency_keys", ["tenant_id", "created_at"]
    )

    op.create_table(
        "risk_assessments",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("payment_intent_id", sa.UUID(), nullable=False),
        sa.Column("charge_id", sa.UUID(), nullable=True),
        sa.Column("risk_score", sa.SmallInteger(), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("triggered_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("risk_score >= 0 AND risk_score <= 100", name="ck_risk_score"),
        sa.CheckConstraint("decision IN ('allow','review','block')", name="ck_risk_decision"),
        sa.ForeignKeyConstraint(["charge_id"], ["charges.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["payment_intent_id"], ["payment_intents.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_risk_assessments_tenant_id", "risk_assessments", ["tenant_id"])
    op.create_index(
        "ix_risk_assessments_payment_intent_id", "risk_assessments", ["payment_intent_id"]
    )
    op.create_index("ix_risk_assessments_charge_id", "risk_assessments", ["charge_id"])
    op.create_index(
        "ix_risk_tenant_created", "risk_assessments", ["tenant_id", "created_at"]
    )

    op.create_table(
        "webhook_endpoints",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("signing_secret", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "url", name="uq_webhook_endpoint_tenant_url"),
    )
    op.create_index("ix_webhook_endpoints_tenant_id", "webhook_endpoints", ["tenant_id"])

    op.create_table(
        "webhook_events",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=128), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_webhook_events_tenant_id", "webhook_events", ["tenant_id"])
    op.create_index(
        "ix_webhook_events_tenant_created", "webhook_events", ["tenant_id", "created_at"]
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("endpoint_id", sa.UUID(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending','delivered','failed','dead_lettered')",
            name="ck_webhook_delivery_status",
        ),
        sa.ForeignKeyConstraint(["endpoint_id"], ["webhook_endpoints.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["webhook_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "endpoint_id", name="uq_delivery_event_endpoint"),
    )
    op.create_index("ix_webhook_deliveries_tenant_id", "webhook_deliveries", ["tenant_id"])
    op.create_index("ix_webhook_deliveries_event_id", "webhook_deliveries", ["event_id"])
    op.create_index("ix_webhook_deliveries_endpoint_id", "webhook_deliveries", ["endpoint_id"])
    op.create_index(
        "ix_webhook_deliveries_due", "webhook_deliveries", ["status", "next_attempt_at"]
    )
    op.create_index(
        "ix_webhook_deliveries_tenant_created",
        "webhook_deliveries",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("webhook_deliveries")
    op.drop_table("webhook_events")
    op.drop_table("webhook_endpoints")
    op.drop_table("risk_assessments")
    op.drop_table("idempotency_keys")
    op.drop_table("charges")
    op.drop_table("payment_intents")
    op.drop_table("customers")
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_column("api_keys", "last_used_at")
    op.drop_column("api_keys", "is_active")
