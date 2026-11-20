"""Settings read from environment variables only (see .env.example)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

WEAK_SECRETS = frozenset({"", "dev-only-not-secret", "change-me", "changeme", "secret"})


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
    # Migrations run as the table owner (not the app role). Falls back to DATABASE_URL.
    migrations_database_url: str | None = None
    db_pool_size: int = Field(default=5, ge=1, le=20)
    db_statement_timeout_ms: int = Field(default=5000, ge=100)

    # Signs nothing on its own today; kept for future token signing. Must be set in production.
    secret_key: SecretStr = SecretStr("dev-only-not-secret")

    # Email (Resend). With no key, emails are logged as "skipped" and never sent.
    resend_api_key: SecretStr | None = None
    email_from: str = "Kazi Hakika <onboarding@resend.dev>"
    email_daily_limit: int = Field(default=90, ge=0, le=100)
    # Held back for the daily digest: other emails stop at limit - reserve.
    email_digest_reserve: int = Field(default=30, ge=0, le=100)

    # Size caps.
    max_body_bytes: int = 64 * 1024

    # Sessions.
    session_days: int = Field(default=14, ge=1, le=90)

    # How many reverse proxies sit in front of the app and append to
    # X-Forwarded-For (Railway's edge: 1). 0 trusts no forwarded header.
    trusted_proxy_hops: int = Field(default=0, ge=0, le=5)

    @property
    def session_cookie_name(self) -> str:
        # __Host- pins the cookie to this exact host, https only, path /.
        return "__Host-kh_session" if self.is_production else "kh_session"

    @field_validator("database_url", "migrations_database_url")
    @classmethod
    def _use_psycopg_driver(cls, value: str | None) -> str | None:
        """Railway hands out postgresql:// URLs; SQLAlchemy needs the driver named."""
        if value is None:
            return None
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value.removeprefix(prefix)
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @model_validator(mode="after")
    def _production_needs_real_secrets(self) -> Settings:
        if self.is_production:
            secret = self.secret_key.get_secret_value()
            if len(secret) < 32 or secret.lower() in WEAK_SECRETS:
                raise ValueError(
                    "SECRET_KEY must be a random string of 32+ characters in production"
                )
            if not self.base_url.startswith("https://"):
                raise ValueError("BASE_URL must be https in production")
            if "trusted_proxy_hops" not in self.model_fields_set:
                # Left at 0 behind Railway's proxy, every visitor would share
                # one rate-limit bucket and 5 logins a minute would block all.
                raise ValueError("Set TRUSTED_PROXY_HOPS in production (1 on Railway)")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
