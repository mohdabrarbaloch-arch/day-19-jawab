"""Application settings, loaded from the environment only.

Nothing here has a secret baked in. Every value that matters in production
comes from an env var, and the defaults are the ones that make a fresh
`git clone && uvicorn` work on a laptop.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- identity -------------------------------------------------------
    app_name: str = "Jawab"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False

    # --- storage --------------------------------------------------------
    # SQLite by default so the app runs with zero setup. Point this at a
    # postgresql+psycopg:// URL in production (docker-compose does).
    database_url: str = f"sqlite:///{BASE_DIR / 'data' / 'jawab.db'}"
    static_dir: Path = BASE_DIR / "app" / "static"

    # --- auth -----------------------------------------------------------
    jwt_secret: str = "dev-only-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # a week; this is a reading app

    # --- retrieval ------------------------------------------------------
    # How many results to ask the search provider for, and how many of
    # those we actually download and read. Reading is the slow part.
    search_results: int = 8
    fetch_pages: int = 5
    fetch_timeout_seconds: float = 6.0
    max_page_bytes: int = 900_000
    user_agent: str = (
        "Mozilla/5.0 (compatible; JawabBot/1.0; +https://github.com/mohdabrarbaloch-arch)"
    )

    # --- answer synthesis ----------------------------------------------
    max_answer_sentences: int = 7
    min_sentence_chars: int = 45
    max_sentence_chars: int = 320
    followup_count: int = 4

    # --- rate limiting --------------------------------------------------
    rate_limit_requests: int = 30
    rate_limit_window_seconds: int = 60

    # --- cors -----------------------------------------------------------
    cors_origins: str = "*"

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
