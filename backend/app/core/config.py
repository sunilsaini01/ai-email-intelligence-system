"""
Centralized application configuration.

Why this exists:
    Without a single Settings object, env vars get read ad-hoc via os.getenv()
    scattered across the codebase. That means: no validation (a missing DB_PORT
    fails at runtime deep in some unrelated function), no type coercion (everything
    is a string unless you remember to cast it), and no single place to see what
    configuration the app even depends on.

Pydantic's BaseSettings gives you:
    - Type validation at startup (fail fast, not 200 requests later)
    - Automatic env var -> field mapping
    - A documented, typed contract for "what this app needs to run"
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App metadata ---
    APP_NAME: str = "AI Email Intelligence System"
    APP_ENV: str = Field(default="development")  # development | staging | production
    API_VERSION: str = "v1"
    DEBUG: bool = Field(default=True)

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # --- Database ---
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "email_intelligence"

    @property
    def DATABASE_URL(self) -> str:
        # asyncpg driver for async SQLAlchemy
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # --- Logging ---
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = True  # structured JSON logs in prod; set False for readable local dev logs

    # --- Security (placeholders — wired up properly in a later phase) ---
    SECRET_KEY: str = Field(default="CHANGE_ME_IN_PRODUCTION")

    # --- Phase 11 (Manager Dashboard) — CORS ---
    # The frontend/ Vite dev server runs on a different origin (localhost:5173)
    # than this API (localhost:8000) -- without explicit CORS allowance the
    # browser blocks every dashboard fetch/WebSocket call outright. A
    # comma-separated list, not a wildcard: this project has no real auth yet
    # (see docs/dashboard_security.md), so an open CORS policy would let any
    # page on the internet call these endpoints from a user's browser.
    CORS_ORIGINS: str = Field(default="http://localhost:5173,http://127.0.0.1:5173")

    @property
    def CORS_ORIGIN_LIST(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    # --- Phase 10 (Auto-Reply Generation) — Groq ---
    # GROQ_API_KEY_2..5 are optional extra credentials GroqProvider rotates
    # to on a 429 (RateLimitError) — see app/inference/groq_provider.py.
    # Groq's rate limits are per-organization, not per-key (verified against
    # Groq's own docs before this was built), so keys from the SAME account
    # do not multiply throughput; they're only useful as genuinely separate
    # accounts/credentials, or as a resilience measure if one key is revoked.
    GROQ_API_KEY: str = Field(default="")
    GROQ_API_KEY_2: str = Field(default="")
    GROQ_API_KEY_3: str = Field(default="")
    GROQ_API_KEY_4: str = Field(default="")
    GROQ_API_KEY_5: str = Field(default="")
    GROQ_MODEL: str = Field(default="llama-3.3-70b-versatile")

    @property
    def GROQ_API_KEYS(self) -> list[str]:
        """Non-empty keys only, in rotation order."""
        return [
            k
            for k in (self.GROQ_API_KEY, self.GROQ_API_KEY_2, self.GROQ_API_KEY_3, self.GROQ_API_KEY_4, self.GROQ_API_KEY_5)
            if k
        ]

    # --- Post-Phase-10 fix #5 — Ollama fallback ---
    # No API key needed (local server). Only used when Groq raises
    # LLMRateLimitedError/LLMServiceUnavailableError (429/503) -- see
    # app/inference/fallback_llm_provider.py.
    OLLAMA_MODEL: str = Field(default="mistral:7b")
    OLLAMA_BASE_URL: str = Field(default="http://localhost:11434")

    # --- Phase 11 (Manager Dashboard & Analytics) ---
    # FR-61: how many CORRECTION feedback_events for one module must
    # accumulate (since the last trigger) before a retraining_triggers row
    # is written. A documented development default, NOT a validated
    # business threshold -- the PRD names no value for this anywhere. See
    # docs/architecture_dashboard.md "Retraining trigger".
    RETRAINING_FEEDBACK_THRESHOLD: int = Field(default=50)

    # FR-53's SLA dashboard. Documented development defaults, NOT real
    # business SLA values -- the PRD names none. Configurable per
    # environment; see docs/architecture_dashboard.md "SLA definition".
    SLA_CRITICAL_HOURS: float = Field(default=2.0)
    SLA_HIGH_HOURS: float = Field(default=8.0)
    SLA_MEDIUM_HOURS: float = Field(default=24.0)
    SLA_LOW_HOURS: float = Field(default=72.0)
    # "At risk" fires once elapsed time crosses this fraction of the
    # target, before the target itself is breached.
    SLA_AT_RISK_FRACTION: float = Field(default=0.75)

    # FR-60's low-confidence review-queue threshold. Two values, not one:
    # multi-label modules (category/intent) have per-label confidence
    # dicts that are naturally more spread out than a single-label
    # module's scalar confidence, so a lower bar avoids flooding the queue
    # with normal multi-label uncertainty. See
    # docs/architecture_dashboard.md "Review Queue ranking".
    LOW_CONFIDENCE_THRESHOLD_SINGLE_LABEL: float = Field(default=0.6)  # spam/priority/sentiment/routing
    LOW_CONFIDENCE_THRESHOLD_MULTI_LABEL: float = Field(default=0.5)  # category/intent


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor.

    Why lru_cache: Settings() re-parses and re-validates env vars every time
    it's instantiated. Since config doesn't change during the process lifetime,
    we want exactly one Settings instance, built once, reused everywhere
    (including as a FastAPI dependency — see app/api/v1/endpoints/health.py).
    """
    return Settings()
