"""Settings read from environment variables only (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Kazi Hakika"
    app_tagline: str = "verified roles, tracked your way."
    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"

    # Public URL used in emails (verification and reset links).
    base_url: str = "http://localhost:8000"

    # The app connects as a non-superuser role so RLS always applies.
    database_url: str = "postgresql+psycopg://kazi_app:kazi_app@localhost:5432/kazi_hakika"

    # Signs nothing on its own today; kept for future token signing. Must be set in production.
    secret_key: SecretStr = SecretStr("dev-only-not-secret")

    # Email (Resend). With no key, emails are logged as "skipped" and never sent.
    resend_api_key: SecretStr | None = None
    email_from: str = "Kazi Hakika <onboarding@resend.dev>"
    email_daily_limit: int = Field(default=90, ge=0, le=100)

    # Size caps.
    max_body_bytes: int = 64 * 1024

    # Sessions.
    session_days: int = Field(default=14, ge=1, le=90)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _production_needs_real_secrets(self) -> "Settings":
        if self.is_production:
            if self.secret_key.get_secret_value() in ("", "dev-only-not-secret"):
                raise ValueError("SECRET_KEY must be set in production")
            if not self.base_url.startswith("https://"):
                raise ValueError("BASE_URL must be https in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
