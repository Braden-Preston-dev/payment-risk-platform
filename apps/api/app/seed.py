from sqlalchemy import select

from app.core.config import settings
from app.core.security import generate_api_key, get_api_key_prefix, hash_api_key
from app.db.session import SessionLocal
from app.models.api_key import APIKey
from app.models.tenant import Tenant


def seed() -> None:
    with SessionLocal() as db, db.begin():
        tenant = db.scalar(select(Tenant).where(Tenant.name == settings.SEED_TENANT_NAME))
        if tenant is None:
            tenant = Tenant(name=settings.SEED_TENANT_NAME)
            db.add(tenant)
            db.flush()

        raw_key = generate_api_key()
        db.add(
            APIKey(
                tenant_id=tenant.id,
                key_hash=hash_api_key(raw_key),
                prefix=get_api_key_prefix(raw_key),
            )
        )
        db.flush()
        print(f"tenant_id={tenant.id}")
        print(f"api_key={raw_key}")
        print("Store this API key securely; it cannot be retrieved later.")


if __name__ == "__main__":
    seed()
