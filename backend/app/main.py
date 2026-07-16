"""FastAPI entrypoint for the Pantheon backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.config_loader import load_all_agent_configs
from app.core.settings import settings, validate_startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    # crash on boot, not on the first request -- a leaked cred or a missing one should
    # fail the deploy, not get discovered by whoever hits the API first
    validate_startup(settings)
    # same fail-fast philosophy -- a bad agents/*.md fails the boot, not the first task that needs it
    app.state.agent_configs = load_all_agent_configs(settings.agent_config_dir)
    yield


app = FastAPI(title="Pantheon", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    """Liveness check used by the repo-skeleton test and future deploy checks."""
    return {"status": "ok", "mode": settings.mode}
