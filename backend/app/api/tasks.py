"""POST /tasks kicks off an agent run in a FastAPI background task; GET /tasks/{id} lets you poll the result.

No scheduler yet (that's step 8) -- the background task is an interim mechanism for this step only.
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.asmoday_agent import AsmodayAgent
from app.agents.base_agent import BaseAgent
from app.agents.config import AgentConfig
from app.agents.prometheus_agent import PrometheusAgent
from app.api.task_chain import spawn_child_task
from app.core.database import SessionLocal
from app.models import Task

router = APIRouter()

# plain explicit mapping -- a config-driven registry isn't worth building until step 10
# brings on the remaining agents, two entries doesn't justify one yet
AGENT_CLASSES: dict[str, type[BaseAgent]] = {"Prometheus": PrometheusAgent, "Asmoday": AsmodayAgent}


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


def _spawn_asmoday_children(
    session: Session, parent: Task, prd: dict, agent_configs: dict[str, AgentConfig]
) -> None:
    """one Asmoday child per task_breakdown item -- a failed spawn (e.g. depth cap) is skipped, not fatal to the batch"""
    scope = prd.get("scope", "")
    for item in prd.get("task_breakdown", []):
        child_payload = {
            "request": (
                f"Project scope: {scope}\n\n"
                f"Your assigned task: {item.get('title', '')}\n{item.get('description', '')}"
            )
        }
        try:
            child = spawn_child_task(session, parent, "Asmoday", child_payload)
        except ValueError:
            continue

        # run it now, not left pending -- there's no scheduler yet (step 8) to pick it up later
        _run_agent_task(child.id, "Asmoday", agent_configs["Asmoday"], child_payload, agent_configs)


def _run_agent_task(
    task_id: uuid.UUID,
    assigned_to: str,
    config: AgentConfig,
    payload: dict | None,
    agent_configs: dict[str, AgentConfig],
) -> None:
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

        if assigned_to == "Prometheus" and agent.state == "done":
            _spawn_asmoday_children(session, task, result, agent_configs)
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
            _run_agent_task, task.id, body.assigned_to, agent_configs[body.assigned_to], body.payload, agent_configs
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


@router.get("/tasks/{task_id}/children", response_model=list[TaskResponse])
def get_task_children(task_id: uuid.UUID) -> list[Task]:
    # empty list, not 404 -- a task with no children yet (or a non-Prometheus task) is a valid state
    session = SessionLocal()
    try:
        return session.query(Task).filter(Task.parent_task_id == task_id).all()
    finally:
        session.close()
