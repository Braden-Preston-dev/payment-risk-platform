from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeEngine


def json_type() -> TypeEngine:
    return JSON().with_variant(JSONB(), "postgresql")
