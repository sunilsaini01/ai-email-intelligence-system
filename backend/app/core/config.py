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

    # --- Security ---
    # Was a placeholder ("wired up properly in a later phase") since
    # Phase 1 -- Phase 17 is that later phase. Now the HS256 signing key
    # for every JWT app/core/security.py issues/verifies. Still must be
    # replaced before any non-local use, same as before.
    SECRET_KEY: str = Field(default="CHANGE_ME_IN_PRODUCTION")

    # --- Phase 17 (real authentication), RS256 since Phase 22 ---
    # PRD SS6.4 names RS256. Keys are PEM strings (JWT_PRIVATE_KEY /
    # JWT_PUBLIC_KEY, literal "\n"-escaped newlines accepted so they fit in a
    # single env var / k8s Secret value). Outside production, a missing
    # keypair is generated once and persisted under JWT_KEY_DIR -- see
    # app/core/security.py. Setting JWT_ALGORITHM=HS256 still works and
    # signs with SECRET_KEY, for anyone who needs the old behavior.
    JWT_ALGORITHM: str = Field(default="RS256")
    JWT_PRIVATE_KEY: str = Field(default="")
    JWT_PUBLIC_KEY: str = Field(default="")
    JWT_KEY_DIR: str = Field(default=".jwt_keys")
    # Membership security fix: public POST /auth/register can only create a
    # NEW organization. Set false for a closed deployment where every
    # account must come from an admin invitation.
    ALLOW_PUBLIC_ORGANIZATION_SIGNUP: bool = Field(default=True)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(default=60 * 24)  # 24h -- a documented development default, not a validated session-length policy; the PRD names none.

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

    # --- Phase 12 (Multi-Agent Architecture) — Kafka ---
    # docker-compose's apache/kafka service, KRaft mode, single broker --
    # see docs/kafka_architecture.md. PLAINTEXT (no auth/TLS) is consistent
    # with this project's standing no-real-auth stance (docs/architecture.md,
    # restated in docs/dashboard_security.md) -- not a new gap Phase 12
    # introduces, the same one every other phase has disclosed.
    KAFKA_BOOTSTRAP_SERVERS: str = Field(default="localhost:9092")

    # FR-66: max attempts INCLUDING the first (i.e. up to 2 retries after
    # the initial attempt is the PRD's literal "retry 3 times" only if read
    # as 3 retries; this codebase reads it as "up to 3 total attempts" --
    # see docs/retry_strategy.md "Interpreting 'retry 3 times'" for why).
    AGENT_MAX_ATTEMPTS: int = Field(default=3)
    # Exponential backoff base, seconds: attempt 1 fails -> wait
    # AGENT_RETRY_BACKOFF_BASE_SECONDS ** 1, attempt 2 fails -> ** 2, etc.
    AGENT_RETRY_BACKOFF_BASE_SECONDS: float = Field(default=2.0)

    # Consumer group prefix -- each agent gets its own group
    # (f"{prefix}-{agent_name}"), so agent replicas can scale independently
    # later without a design change now. See docs/kafka_architecture.md.
    KAFKA_CONSUMER_GROUP_PREFIX: str = Field(default="email-ai")

    # --- Phase 16B (Monitoring & Alerting, FR-72) ---
    # Port the `agents` process's own metrics HTTP server binds to
    # (app.core.metrics.start_metrics_server, called from
    # app/agents/runner.py) -- that process has no other HTTP server, see
    # k8s/agents-deployment.yaml. The `api` process does not use this
    # setting; it mounts /metrics onto its existing FastAPI app instead
    # (app/main.py), on the same port as everything else.
    METRICS_PORT: int = Field(default=9100)

    # How long a workflow may sit in RUNNING before
    # WorkflowExecutionRepository.list_stale_running() (and the
    # workflow_stuck_total gauge it feeds) flags it. A documented
    # development default, NOT a validated SLA value -- the PRD names none
    # for this. Deliberately well above the PRD's own 15s hard latency
    # limit: this threshold is for "the Orchestrator's in-memory tracker
    # was lost" (see app/agents/orchestrator.py's module docstring), a
    # different failure mode than a slow-but-progressing workflow, which
    # the latency histogram/alerts already cover on their own.
    STUCK_WORKFLOW_THRESHOLD_MINUTES: int = Field(default=10)
    STUCK_WORKFLOW_CHECK_INTERVAL_SECONDS: int = Field(default=60)

    # --- Phase 18 (Live Mailbox Ingestion, FR-01/FR-02/FR-03) ---
    # Used to build each provider's OAuth2 redirect_uri
    # (f"{APP_BASE_URL}/api/{API_VERSION}/mailbox/{provider}/callback").
    # Must exactly match the redirect URI registered with Google Cloud /
    # Azure AD -- both providers reject a mismatch outright, so this has
    # to be the URL Google/Microsoft can actually redirect the user's
    # BROWSER back to, not the internal docker-compose service name (see
    # docker-compose.yml's api port mapping, 8001 on the host -> 8000
    # in-container).
    APP_BASE_URL: str = Field(default="http://localhost:8001")

    # Google Cloud Console -> APIs & Services -> Credentials -> OAuth
    # client ID (type "Web application"), with the Gmail API enabled and
    # the `gmail.readonly` scope added on the OAuth consent screen. Empty
    # by default -- GmailProvider raises a clear "not configured" error
    # at connect-request time rather than the poller silently never
    # running, same fail-fast-not-silent stance as GroqProviderUnavailable.
    GOOGLE_CLIENT_ID: str = Field(default="")
    GOOGLE_CLIENT_SECRET: str = Field(default="")

    # Azure Portal -> App registrations -> new registration -> client ID/
    # secret, with the Microsoft Graph delegated permission `Mail.Read`
    # (+ `offline_access` for a refresh token) granted. "common" allows
    # both personal Microsoft accounts and any work/school tenant to
    # connect -- see Microsoft's own v2.0 endpoint docs on tenant values;
    # a specific tenant ID would restrict this to one organization only.
    MICROSOFT_CLIENT_ID: str = Field(default="")
    MICROSOFT_CLIENT_SECRET: str = Field(default="")
    MICROSOFT_TENANT_ID: str = Field(default="common")

    # Symmetric key mailbox refresh/access tokens are encrypted with at
    # rest (app/core/token_encryption.py) -- separate from SECRET_KEY
    # (which signs JWTs, a different trust boundary: SECRET_KEY leaking
    # forges login sessions, this key leaking decrypts stored mailbox
    # credentials) even though both currently need the same
    # "CHANGE_ME_IN_PRODUCTION before any non-local use" operator action.
    MAILBOX_TOKEN_ENCRYPTION_KEY: str = Field(default="CHANGE_ME_IN_PRODUCTION")

    # Periodic poll, same reasoning as STUCK_WORKFLOW_CHECK_INTERVAL_SECONDS
    # above: neither Gmail Pub/Sub push nor Graph webhook subscriptions are
    # reachable from this project's current deployment (no public HTTPS
    # endpoint -- see docs/architecture_mailbox_ingestion.md "Why Polling,
    # Not Push"), so a background poll is the only mechanism that works
    # against a local Docker Compose stack today.
    MAILBOX_POLL_INTERVAL_SECONDS: int = Field(default=60)
    # Safety cap per connection per poll cycle -- protects against one
    # connection with a huge unread backlog (e.g. the very first sync)
    # starving every other connection's poll turn and the rest of the
    # agents process's event loop.
    MAILBOX_MAX_MESSAGES_PER_POLL: int = Field(default=20)

    # --- Phase 22 (PRD gap closure) -- agents-process periodic jobs ---
    # See app/services/scheduled_jobs.py. Development defaults, not
    # validated operational values.
    SLA_SWEEP_INTERVAL_SECONDS: int = Field(default=300)
    DRIFT_CHECK_INTERVAL_SECONDS: int = Field(default=3600)
    RETRAINING_POLL_INTERVAL_SECONDS: int = Field(default=60)
    RETENTION_PURGE_INTERVAL_SECONDS: int = Field(default=24 * 3600)
    REPORT_CHECK_INTERVAL_SECONDS: int = Field(default=3600)
    # 0 = Monday. The weekly report covers the previous Monday-Sunday.
    WEEKLY_REPORT_WEEKDAY: int = Field(default=0)

    # --- Phase 22 -- API rate limiting (PRD SS13.1: 1,000 req/min per
    # organization, configurable). Per API process; see
    # app/middleware/rate_limit.py for the multi-replica caveat.
    RATE_LIMIT_PER_MINUTE: int = Field(default=1000)
    RATE_LIMIT_ENABLED: bool = Field(default=True)

    # Where the per-module `*_feedback.jsonl` correction logs live. Empty =
    # the repo's artifacts/ dir (the original behavior). Kubernetes sets
    # this to a writable volume because the container root filesystem is
    # read-only there.
    FEEDBACK_LOG_DIR: str = Field(default="")


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
