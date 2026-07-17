"""FastAPI entrypoint for the Pantheon backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agents.config import AgentConfig
from app.agents.config_loader import load_all_agent_configs
from app.api.agents import router as agents_router
from app.api.tasks import router as tasks_router
from app.core.database import SessionLocal
from app.core.scheduler import start_scheduler
from app.core.settings import settings, validate_startup
from app.models import Agent


def seed_agents(agent_configs: dict[str, AgentConfig]) -> None:
    """gives every loaded agents/*.md a row in the agents table -- keyed on name, so reboots update instead of duplicating.

    Existing rows keep done/failed on purpose: a "failed" from last night should still be on the
    status page this morning, not wiped back to idle by a restart. "running" is the exception --
    nothing survives a restart, so a running row is a stale lie and gets reset.
    """
    with SessionLocal() as session:
        for config in agent_configs.values():
            agent = session.query(Agent).filter(Agent.name == config.name).one_or_none()
            if agent is None:
                session.add(Agent(name=config.name, role=config.role, model=config.model))
                continue
            # config file is the source of truth for these two -- an .md edit should show up on next boot
            agent.role = config.role
            agent.model = config.model
            # the backstop for a hard crash mid-run: whatever was working is definitely not working now
            if agent.status == "running":
                agent.status = "idle"
        session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # crash on boot, not on the first request -- a leaked cred or a missing one should
    # fail the deploy, not get discovered by whoever hits the API first
    validate_startup(settings)
    # same fail-fast philosophy -- a bad agents/*.md fails the boot, not the first task that needs it
    app.state.agent_configs = load_all_agent_configs(settings.agent_config_dir)
    # the agents table has had a schema since step 4 but nothing ever filled it -- this is where it starts being real
    seed_agents(app.state.agent_configs)
    # the poller that actually runs tasks -- starts on boot, shuts down cleanly on exit
    scheduler = start_scheduler(app.state.agent_configs)
    try:
        yield
    finally:
        scheduler.shutdown()


app = FastAPI(title="Pantheon", lifespan=lifespan)
app.include_router(tasks_router)
app.include_router(agents_router)


@app.get("/health")
def health() -> dict:
    """Liveness check used by the repo-skeleton test and future deploy checks."""
    return {"status": "ok", "mode": settings.mode}
