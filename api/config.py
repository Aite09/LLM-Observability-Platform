"""
Application configuration — single source of truth for all env vars.

Every other module calls get_settings() instead of reading os.environ directly.
This means:
  - Config is validated at startup (bad value → clear error, not silent bug)
  - @lru_cache ensures the Settings object is created once, not on every call
  - Tests can override settings by clearing the cache: get_settings.cache_clear()
"""

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ── Database ───────────────────────────────────────────────────────────────
    # Must use postgresql+asyncpg:// scheme — asyncpg is the async driver.
    # psycopg2:// would block the event loop.
    database_url: str

    # ── Redis ──────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── LLM Judge (eval scorer) ────────────────────────────────────────────────
    # "mock" = free deterministic heuristic (default — $0 guarantee)
    # "anthropic" = real Claude judge; requires anthropic_api_key
    judge_provider: str = "mock"
    judge_model: str = "claude-haiku-4-5"
    anthropic_api_key: str = ""

    # ── Embeddings (local, free) ───────────────────────────────────────────────
    embedding_model: str = "BAAI/bge-small-en-v1.5"  # 384-dim, ONNX via fastembed
    embedding_dims: int = 384

    # ── Workers ────────────────────────────────────────────────────────────────
    metrics_interval_seconds: int = 300
    drift_check_interval_seconds: int = 3600

    # ── Drift detection ────────────────────────────────────────────────────────
    drift_baseline_days: int = 7
    drift_min_baseline: int = 50
    drift_min_current: int = 20

    # ── Webhook signing ────────────────────────────────────────────────────────
    webhook_secret: str = ""

    # ── OTEL ───────────────────────────────────────────────────────────────────
    otel_exporter_otlp_endpoint: str = ""

    # ── Eval Gate ──────────────────────────────────────────────────────────────
    # CI deploy is blocked if eval pass_rate < this value
    eval_gate_threshold: float = 0.8

    # ── Drift Detection ────────────────────────────────────────────────────────
    # Optional — leave unset to disable webhook firing
    drift_webhook_url: str | None = None

    # ── App ────────────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    app_name: str = "llm-observability"

    @field_validator("database_url")
    @classmethod
    def must_be_async(cls, v: str) -> str:
        """Fail fast if someone accidentally uses a sync driver URL."""
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "database_url must use postgresql+asyncpg:// scheme. "
                f"Got: {v!r}"
            )
        return v

    @field_validator("judge_provider")
    @classmethod
    def judge_provider_known(cls, v: str) -> str:
        if v not in ("mock", "anthropic"):
            raise ValueError(f"judge_provider must be 'mock' or 'anthropic', got {v!r}")
        return v

    @model_validator(mode="after")
    def anthropic_needs_key(self) -> "Settings":
        if self.judge_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError(
                "judge_provider=anthropic requires ANTHROPIC_API_KEY. "
                "Use judge_provider=mock for free operation."
            )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # Ignore extra env vars — shared .env files may have keys we don't use
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Return the cached Settings instance.

    @lru_cache = constructed once per process lifetime.
    To reset in tests: get_settings.cache_clear()
    """
    return Settings()
