"""POST /tasks kicks off an agent run in a FastAPI background task; GET /tasks/{id} lets you poll the result.

No scheduler yet (that's step 8) -- the background task is an interim mechanism for this step only.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from app.agents.base_agent import BaseAgent
from app.agents.config import AgentConfig
from app.agents.prometheus_agent import PrometheusAgent
from app.core.database import SessionLocal
from app.models import Task

router = APIRouter()

# plain explicit mapping -- only one real agent exists so far, a config-driven registry
# isn't worth building until step 7 (Asmoday) adds a second one
AGENT_CLASSES: dict[str, type[BaseAgent]] = {"Prometheus": PrometheusAgent}


class TaskCreateRequest(BaseModel):
    created_by: str
    assigned_to: str
    payload: dict | None = None
    project_id: uuid.UUID | None = None


class TaskResponse(BaseModel):
    id: uuid.UUID
    status: str
    payload: dict | None
    result: dict | None
    created_by: str
    assigned_to: str
    parent_task_id: uuid.UUID | None
    project_id: uuid.UUID | None
    depth: int

    model_config = {"from_attributes": True}


def _run_agent_task(task_id: uuid.UUID, assigned_to: str, config: AgentConfig, payload: dict | None) -> None:
    """the background job -- opens its own session, since the request's session is already closed by the time this runs"""
    session = SessionLocal()
    try:
        task = session.get(Task, task_id)
        task.status = "running"
        session.commit()

        agent_class = AGENT_CLASSES.get(assigned_to, BaseAgent)
        agent = agent_class(config)
        result = agent.run(payload or {})

        task.status = agent.state
        task.result = result if agent.state == "done" else {"error": agent.error}
        session.commit()
    finally:
        session.close()


@router.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(body: TaskCreateRequest, request: Request, background_tasks: BackgroundTasks) -> Task:
    agent_configs: dict[str, AgentConfig] = request.app.state.agent_configs
    if body.assigned_to not in agent_configs:
        raise HTTPException(status_code=422, detail=f"'{body.assigned_to}' isn't a loaded agent")

    session = SessionLocal()
    try:
        task = Task(
            status="pending",
            payload=body.payload,
            created_by=body.created_by,
            assigned_to=body.assigned_to,
            project_id=body.project_id,
        )
        session.add(task)
        session.commit()
        session.refresh(task)

        background_tasks.add_task(
            _run_agent_task, task.id, body.assigned_to, agent_configs[body.assigned_to], body.payload
        )

        return task
    finally:
        session.close()


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: uuid.UUID) -> Task:
    session = SessionLocal()
    try:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return task
    finally:
        session.close()
