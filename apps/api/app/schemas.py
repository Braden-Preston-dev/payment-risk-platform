from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CustomerCreate(BaseModel):
    external_id: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    name: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CustomerResponse(CustomerCreate):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class PaymentIntentCreate(BaseModel):
    amount: int = Field(gt=0, le=9_999_999_999_999)
    currency: str = Field(min_length=3, max_length=3)
    customer_id: UUID | None = None
    payment_method_type: str = Field(default="card", min_length=1, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        if not value.isalpha():
            raise ValueError("currency must contain exactly three letters")
        return value.lower()


class PaymentIntentConfirm(BaseModel):
    payment_method_type: str | None = Field(default=None, min_length=1, max_length=64)


class ChargeResponse(BaseModel):
    id: UUID
    payment_intent_id: UUID
    amount: int
    currency: str
    status: str
    failure_code: str | None
    failure_message: str | None
    created_at: datetime


class RiskAssessmentResponse(BaseModel):
    id: UUID
    risk_score: int
    decision: str
    triggered_rules: list[dict[str, Any]]
    created_at: datetime


class PaymentIntentResponse(BaseModel):
    id: UUID
    customer_id: UUID | None
    amount: int
    currency: str
    status: str
    payment_method_type: str
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    latest_charge: ChargeResponse | None = None
    latest_risk_assessment: RiskAssessmentResponse | None = None


class WebhookEndpointCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class WebhookEndpointResponse(BaseModel):
    id: UUID
    url: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class WebhookEndpointCreated(WebhookEndpointResponse):
    signing_secret: str


class WebhookDeliveryResponse(BaseModel):
    id: UUID
    event_id: UUID
    endpoint_id: UUID
    attempt_count: int
    status: str
    last_error: str | None
    next_attempt_at: datetime
    last_attempt_at: datetime | None
    created_at: datetime
