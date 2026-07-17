"""GET /agents/status -- what the status frontend polls, and what the Phaser dashboard will read later.

Reads the agents table, which main.py seeds at boot and tasks.py updates as work runs.
"""

from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.database import SessionLocal
from app.models import Agent

router = APIRouter()


class AgentStatusResponse(BaseModel):
    name: str
    role: str
    model: str
    status: str  # idle | running | done | failed
    updated_at: datetime

    model_config = {"from_attributes": True}


@router.get("/agents/status", response_model=list[AgentStatusResponse])
def get_agents_status() -> list[Agent]:
    # sorted by name so the frontend list doesn't reshuffle between polls
    session = SessionLocal()
    try:
        return session.query(Agent).order_by(Agent.name).all()
    finally:
        session.close()
