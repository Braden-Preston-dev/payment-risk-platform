from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.dependencies import require_admin_token
from app.core.security import generate_api_key, get_api_key_prefix, hash_api_key
from app.db import get_db
from app.models.api_key import APIKey
from app.models.tenant import Tenant

router = APIRouter(dependencies=[Depends(require_admin_token)], tags=["admin"])


@router.post("/tenants/{tenant_id}/api-keys", status_code=status.HTTP_201_CREATED)
def create_api_key(tenant_id: UUID, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")

    raw_key = generate_api_key()

    api_key = APIKey(
        tenant_id=tenant_id,
        key_hash=hash_api_key(raw_key),
        prefix=get_api_key_prefix(raw_key),
    )

    db.add(api_key)
    db.flush()

    return {
        "key": raw_key,
        "prefix": api_key.prefix,
        "message": "Store this key securely. It will not be shown again.",
    }
