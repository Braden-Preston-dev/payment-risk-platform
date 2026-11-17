from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.models.payment import Charge, PaymentIntent
from app.models.risk import RiskAssessment
from app.schemas import (
    ChargeResponse,
    CustomerResponse,
    PaymentIntentResponse,
    RiskAssessmentResponse,
)


def customer_response(customer: Customer) -> CustomerResponse:
    return CustomerResponse(
        id=customer.id,
        external_id=customer.external_id,
        email=customer.email,
        name=customer.name,
        metadata=customer.metadata_,
        created_at=customer.created_at,
        updated_at=customer.updated_at,
    )


def charge_response(charge: Charge) -> ChargeResponse:
    return ChargeResponse(
        id=charge.id,
        payment_intent_id=charge.payment_intent_id,
        amount=charge.amount,
        currency=charge.currency,
        status=charge.status,
        failure_code=charge.failure_code,
        failure_message=charge.failure_message,
        created_at=charge.created_at,
    )


def payment_intent_response(db: Session, payment: PaymentIntent) -> PaymentIntentResponse:
    latest_charge = db.scalar(
        select(Charge)
        .where(
            Charge.tenant_id == payment.tenant_id,
            Charge.payment_intent_id == payment.id,
        )
        .order_by(Charge.created_at.desc(), Charge.id.desc())
        .limit(1)
    )
    latest_risk = db.scalar(
        select(RiskAssessment)
        .where(
            RiskAssessment.tenant_id == payment.tenant_id,
            RiskAssessment.payment_intent_id == payment.id,
        )
        .order_by(RiskAssessment.created_at.desc(), RiskAssessment.id.desc())
        .limit(1)
    )
    return PaymentIntentResponse(
        id=payment.id,
        customer_id=payment.customer_id,
        amount=payment.amount,
        currency=payment.currency,
        status=payment.status,
        payment_method_type=payment.payment_method_type,
        metadata=payment.metadata_,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        latest_charge=charge_response(latest_charge) if latest_charge else None,
        latest_risk_assessment=(
            RiskAssessmentResponse(
                id=latest_risk.id,
                risk_score=latest_risk.risk_score,
                decision=latest_risk.decision,
                triggered_rules=latest_risk.triggered_rules,
                created_at=latest_risk.created_at,
            )
            if latest_risk
            else None
        ),
    )
