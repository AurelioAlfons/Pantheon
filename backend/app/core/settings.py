"""Single source of truth for config -- nothing else in the app should touch os.getenv directly."""

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# settings.py sits at backend/app/core/settings.py -- three parents up lands on the repo root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    mode: Literal["demo", "personal"] = "demo"
    agent_config_dir: Path = REPO_ROOT / "agents"

    # database's built now (step 4) -- no default means Settings() crashes at import if
    # DATABASE_URL is missing, same as any other required config, no more quiet ""
    database_url: str
    # required in every mode, unlike gmail (personal-only) -- no version of this product
    # ships with agents that don't actually think, so no separate validate_startup() branch
    anthropic_api_key: str
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""

    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""

    rate_limit_per_minute: int = 10
    demo_max_tasks_per_session: int = 5

    admin_password_hash: str = ""
    session_secret: str = ""

    max_task_chain_depth: int = 10
    scheduler_poll_interval_seconds: int = 5  # how often the poller sweeps the tasks table for pending rows

    @field_validator("agent_config_dir", mode="after")
    @classmethod
    def _anchor_relative_dir_to_repo_root(cls, value: Path) -> Path:
        # uvicorn/pytest both run with cwd=backend/, so a relative "./agents" would silently
        # resolve to backend/agents (doesn't exist) instead of the real repo-root agents/
        if value.is_absolute():
            return value
        return (REPO_ROOT / value).resolve()


settings = Settings()


def validate_startup(config: Settings) -> None:
    """fail fast at boot -- demo can't leak real creds, personal can't run without them"""
    if config.mode == "personal":
        required = {
            "GMAIL_CLIENT_ID": config.gmail_client_id,
            "GMAIL_CLIENT_SECRET": config.gmail_client_secret,
            "GMAIL_REFRESH_TOKEN": config.gmail_refresh_token,
            "ADMIN_PASSWORD_HASH": config.admin_password_hash,
            "SESSION_SECRET": config.session_secret,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise RuntimeError(
                f"MODE=personal is missing required credentials: {', '.join(missing)}"
            )

    if config.mode == "demo":
        # a real credential showing up here means someone's about to deploy secrets to the public demo
        leakable = {
            "GMAIL_CLIENT_ID": config.gmail_client_id,
            "GMAIL_CLIENT_SECRET": config.gmail_client_secret,
            "GMAIL_REFRESH_TOKEN": config.gmail_refresh_token,
            "SUPABASE_SERVICE_KEY": config.supabase_service_key,
        }
        leaked = [name for name, value in leakable.items() if value]
        if leaked:
            raise RuntimeError(
                f"MODE=demo must not have real credentials set, found: {', '.join(leaked)}"
            )

    # both modes need somewhere real to load agent configs from, or there's no team to run
    if not config.agent_config_dir.exists() or not any(config.agent_config_dir.glob("*.md")):
        raise RuntimeError(
            f"agent_config_dir '{config.agent_config_dir}' doesn't exist or has no .md files"
        )
