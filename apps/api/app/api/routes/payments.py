import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentTenant, DatabaseSession, RedisDependency
from app.core.config import settings
from app.core.rate_limit import RateLimitUnavailableError, increment_counter
from app.models.customer import Customer
from app.models.payment import Charge, PaymentIntent
from app.models.risk import RiskAssessment
from app.schemas import (
    ChargeResponse,
    PaymentIntentConfirm,
    PaymentIntentCreate,
    PaymentIntentResponse,
)
from app.services.idempotency import (
    acquire_idempotency,
    request_fingerprint,
    store_idempotency,
)
from app.services.ml import predict_ml_score
from app.services.risk import evaluate_risk
from app.services.serialization import charge_response, payment_intent_response
from app.services.webhooks import create_webhook_event


router = APIRouter(prefix="/v1/payment_intents", tags=["payment_intents"])
charge_router = APIRouter(prefix="/v1/charges", tags=["charges"])
logger = logging.getLogger("prp.payments")


def _replayed_response(status_code: int, body: dict) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=body,
        headers={"Idempotency-Replayed": "true"},
    )


@router.post("", response_model=PaymentIntentResponse, status_code=status.HTTP_201_CREATED)
def create_payment_intent(
    payload: PaymentIntentCreate,
    request: Request,
    tenant: CurrentTenant,
    db: DatabaseSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    payload_body = payload.model_dump(mode="json")
    fingerprint = request_fingerprint(request.method, request.url.path, payload_body)
    replay = acquire_idempotency(
        db,
        tenant_id=tenant.id,
        key=idempotency_key,
        fingerprint=fingerprint,
    )
    if replay:
        return _replayed_response(replay.status_code, replay.body)

    if payload.customer_id is not None:
        customer_exists = db.scalar(
            select(Customer.id).where(
                Customer.id == payload.customer_id,
                Customer.tenant_id == tenant.id,
            )
        )
        if customer_exists is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

    payment = PaymentIntent(
        tenant_id=tenant.id,
        customer_id=payload.customer_id,
        amount=payload.amount,
        currency=payload.currency,
        payment_method_type=payload.payment_method_type,
        metadata_=payload.metadata,
    )
    db.add(payment)
    db.flush()
    body = payment_intent_response(db, payment).model_dump(mode="json")
    store_idempotency(
        db,
        tenant_id=tenant.id,
        key=idempotency_key,
        fingerprint=fingerprint,
        status_code=status.HTTP_201_CREATED,
        body=body,
    )
    logger.info(
        "payment intent created",
        extra={
            "service": "api",
            "tenant_id": str(tenant.id),
            "request_id": request.state.request_id,
            "payment_intent_id": str(payment.id),
        },
    )
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=body)


@router.post("/{payment_intent_id}/confirm", response_model=PaymentIntentResponse)
def confirm_payment_intent(
    payment_intent_id: UUID,
    request: Request,
    tenant: CurrentTenant,
    db: DatabaseSession,
    redis: RedisDependency,
    payload: Annotated[PaymentIntentConfirm, Body()] = PaymentIntentConfirm(),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> JSONResponse:
    payload_body = payload.model_dump(mode="json")
    fingerprint = request_fingerprint(request.method, request.url.path, payload_body)
    replay = acquire_idempotency(
        db,
        tenant_id=tenant.id,
        key=idempotency_key,
        fingerprint=fingerprint,
    )
    if replay:
        return _replayed_response(replay.status_code, replay.body)

    payment = db.scalar(
        select(PaymentIntent)
        .where(
            PaymentIntent.id == payment_intent_id,
            PaymentIntent.tenant_id == tenant.id,
        )
        .with_for_update()
    )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PaymentIntent not found",
        )
    if payment.status not in {"requires_confirmation", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"PaymentIntent in status '{payment.status}' cannot be confirmed",
        )

    try:
        velocity = increment_counter(
            redis,
            key=f"prp:velocity:confirm:{tenant.id}",
            window_seconds=settings.VELOCITY_WINDOW_SECONDS,
        )
    except RateLimitUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Velocity service unavailable",
        ) from exc
    if velocity.count > settings.VELOCITY_CONFIRM_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Confirmation velocity limit exceeded",
            headers={"Retry-After": str(velocity.retry_after_seconds)},
        )

    if payload.payment_method_type is not None:
        payment.payment_method_type = payload.payment_method_type
    payment.status = "processing"
    charge = Charge(
        tenant_id=tenant.id,
        payment_intent_id=payment.id,
        amount=payment.amount,
        currency=payment.currency,
        status="pending",
    )
    db.add(charge)
    db.flush()

    ml_score = predict_ml_score(
        amount=payment.amount,
        velocity_count=velocity.count,
        payment_method_type=payment.payment_method_type,
    )
    risk_result = evaluate_risk(
        amount=payment.amount,
        velocity_count=velocity.count,
        ml_score=ml_score,
    )
    risk = RiskAssessment(
        tenant_id=tenant.id,
        payment_intent_id=payment.id,
        charge_id=charge.id,
        risk_score=risk_result.score,
        decision=risk_result.decision,
        triggered_rules=risk_result.triggered_rules,
    )
    db.add(risk)

    if risk_result.decision != "allow":
        charge.status = "failed"
        charge.failure_code = f"risk_{risk_result.decision}"
        charge.failure_message = "Payment rejected by risk controls"
        payment.status = "failed"
    elif payment.payment_method_type == "card_declined":
        charge.status = "failed"
        charge.failure_code = "card_declined"
        charge.failure_message = "The simulated card was declined"
        payment.status = "failed"
    else:
        charge.status = "succeeded"
        payment.status = "succeeded"

    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="PaymentIntent has already been successfully confirmed",
        ) from exc

    body = payment_intent_response(db, payment).model_dump(mode="json")
    event_data = {"object": body}
    create_webhook_event(
        db,
        tenant_id=tenant.id,
        event_type=f"payment_intent.{payment.status}",
        payload=event_data,
    )
    create_webhook_event(
        db,
        tenant_id=tenant.id,
        event_type=f"charge.{charge.status}",
        payload={"object": body["latest_charge"]},
    )
    store_idempotency(
        db,
        tenant_id=tenant.id,
        key=idempotency_key,
        fingerprint=fingerprint,
        status_code=status.HTTP_200_OK,
        body=body,
    )
    logger.info(
        "payment confirmation completed",
        extra={
            "service": "api",
            "tenant_id": str(tenant.id),
            "request_id": request.state.request_id,
            "payment_intent_id": str(payment.id),
            "charge_id": str(charge.id),
            "decision": risk_result.decision,
            "outcome": payment.status,
        },
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content=body)


@router.get("/{payment_intent_id}", response_model=PaymentIntentResponse)
def get_payment_intent(
    payment_intent_id: UUID,
    tenant: CurrentTenant,
    db: DatabaseSession,
) -> PaymentIntentResponse:
    payment = db.scalar(
        select(PaymentIntent).where(
            PaymentIntent.id == payment_intent_id,
            PaymentIntent.tenant_id == tenant.id,
        )
    )
    if payment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="PaymentIntent not found",
        )
    return payment_intent_response(db, payment)


@charge_router.get("/{charge_id}", response_model=ChargeResponse)
def get_charge(
    charge_id: UUID,
    tenant: CurrentTenant,
    db: DatabaseSession,
) -> ChargeResponse:
    charge = db.scalar(
        select(Charge).where(
            Charge.id == charge_id,
            Charge.tenant_id == tenant.id,
        )
    )
    if charge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Charge not found")
    return charge_response(charge)
