from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    DATABASE_URL: str = "postgresql+psycopg://postgres:postgres@localhost:5432/payments"
    REDIS_URL: str = "redis://localhost:6379/0"
    API_PEPPER: str = "development-only-change-me"
    ADMIN_TOKEN: str | None = None

    RATE_LIMIT_REQUESTS: int = Field(default=120, ge=1)
    RATE_LIMIT_WINDOW_SECONDS: int = Field(default=60, ge=1)
    VELOCITY_CONFIRM_LIMIT: int = Field(default=10, ge=1)
    VELOCITY_WINDOW_SECONDS: int = Field(default=60, ge=1)

    MAX_REQUEST_BODY_BYTES: int = Field(default=1_048_576, ge=1)
    WEBHOOK_MAX_ATTEMPTS: int = Field(default=5, ge=1)
    WEBHOOK_TIMEOUT_MS: int = Field(default=5_000, ge=100)
    WEBHOOK_MAX_RESPONSE_BYTES: int = Field(default=65_536, ge=1)
    WEBHOOK_BACKOFF_BASE_SECONDS: int = Field(default=5, ge=1)
    WORKER_POLL_INTERVAL_SECONDS: float = Field(default=1.0, ge=0.1)
    ML_MODEL_PATH: str | None = "models/fraud_model.json"

    SEED_TENANT_NAME: str = "Demo Tenant"


settings = Settings()
