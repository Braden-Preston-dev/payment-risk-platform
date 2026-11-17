from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import CurrentTenant, DatabaseSession
from app.models.customer import Customer
from app.schemas import CustomerCreate, CustomerResponse
from app.services.serialization import customer_response


router = APIRouter(prefix="/v1/customers", tags=["customers"])


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
def create_customer(
    payload: CustomerCreate,
    tenant: CurrentTenant,
    db: DatabaseSession,
) -> CustomerResponse:
    customer = Customer(
        tenant_id=tenant.id,
        external_id=payload.external_id,
        email=payload.email,
        name=payload.name,
        metadata_=payload.metadata,
    )
    db.add(customer)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Customer external_id already exists",
        ) from exc
    return customer_response(customer)


@router.get("/{customer_id}", response_model=CustomerResponse)
def get_customer(
    customer_id: UUID,
    tenant: CurrentTenant,
    db: DatabaseSession,
) -> CustomerResponse:
    customer = db.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.tenant_id == tenant.id,
        )
    )
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer_response(customer)
