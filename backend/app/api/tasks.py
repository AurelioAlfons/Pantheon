"""POST /tasks inserts a pending row and returns; the scheduler poller (core/scheduler.py) does the actual work.

GET /tasks/{id} polls one task's status/result; GET /tasks/{id}/children lists what it spawned.
"""

import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agents.aizen_agent import AizenAgent
from app.agents.asmoday_agent import AsmodayAgent
from app.agents.assist_agent import AssistAgent
from app.agents.base_agent import BaseAgent
from app.agents.config import AgentConfig
from app.agents.hermes_agent import HermesAgent
from app.agents.khepri_agent import KhepriAgent
from app.agents.prometheus_agent import PrometheusAgent
from app.api.assist_dispatch import RESEARCH_PURPOSE, dispatch_from_decision, spawn_prometheus_from_research
from app.api.task_chain import spawn_child_task
from app.core.database import SessionLocal
from app.models import Agent, Task

router = APIRouter()

# plain explicit mapping -- all six agents now. small and readable, a config-driven registry
# still wouldn't buy anything at this size
AGENT_CLASSES: dict[str, type[BaseAgent]] = {
    "ASSIST": AssistAgent,
    "Prometheus": PrometheusAgent,
    "Asmoday": AsmodayAgent,
    "Hermes": HermesAgent,
    "Aizen": AizenAgent,
    "Khepri": KhepriAgent,
}


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
    """one pending Asmoday child per task_breakdown item -- the scheduler's next tick runs them.

    A failed spawn (e.g. depth cap) is skipped, not fatal to the batch.
    """
    scope = prd.get("scope", "")
    for item in prd.get("task_breakdown", []):
        child_payload = {
            "request": (
                f"Project scope: {scope}\n\n"
                f"Your assigned task: {item.get('title', '')}\n{item.get('description', '')}"
            )
        }
        try:
            spawn_child_task(session, parent, "Asmoday", child_payload)
        except ValueError:
            continue


def _build_agent_status(session: Session) -> dict[str, str]:
    """snapshot of who's idle/busy from the live agents table -- handed to ASSIST so it never reads the DB itself"""
    return {agent.name: agent.status for agent in session.query(Agent).all()}


def _run_completion_hooks(
    session: Session, task: Task, assigned_to: str, result: dict, agent_configs: dict[str, AgentConfig]
) -> None:
    """what happens after an agent finishes -- the relay's handoffs live here, one branch per hop.

    All three spawn pending child rows the next poll tick runs; none of them run an agent inline.
    """
    if assigned_to == "ASSIST":
        # ASSIST's decision becomes real task rows -- single dispatch, or the start of a relay
        dispatch_from_decision(session, task, result)
    elif assigned_to == "Hermes" and (task.payload or {}).get("purpose") == RESEARCH_PURPOSE:
        # the research bridge: only fires for ASSIST-spawned research, never a standalone Mode Three Hermes task
        spawn_prometheus_from_research(session, task, result)
    elif assigned_to == "Prometheus" and (task.payload or {}).get("auto_continue", True):
        # gated now: a full_pipeline (check-in) task sets auto_continue False and waits for /approve.
        # default True keeps every pre-ASSIST Prometheus task (direct POST, no auto_continue key) spawning as before
        _spawn_asmoday_children(session, task, result, agent_configs)


def _mark_failed(session: Session, task_id: uuid.UUID, assigned_to: str, error: str) -> None:
    """lands the task + its agent on failed after something blew up outside the agent's own error handling"""
    try:
        task = session.get(Task, task_id)
        if task is not None:
            task.status = "failed"
            task.result = {"error": error}  # same shape as the agent-failure path, one thing for a reader to learn
        agent_row = session.query(Agent).filter(Agent.name == assigned_to).one_or_none()
        if agent_row is not None:
            agent_row.status = "failed"
        session.commit()
    except Exception:
        # the DB itself is unreachable, so there's nowhere to write the failure -- give up here and
        # let seed_agents' boot-time reset be the backstop. re-raising would just kill the poll tick
        session.rollback()


def _run_agent_task(
    task_id: uuid.UUID,
    assigned_to: str,
    config: AgentConfig,
    payload: dict | None,
    agent_configs: dict[str, AgentConfig],
) -> None:
    """runs one task to completion -- called by the scheduler poller, opens its own DB session"""
    session = SessionLocal()
    try:
        task = session.get(Task, task_id)
        task.status = "running"
        # the agent row rides along with the task's status -- every run goes through here, so the
        # status page covers scheduler-triggered runs and API-triggered ones without separate wiring
        agent_row = session.query(Agent).filter(Agent.name == assigned_to).one_or_none()
        if agent_row is not None:
            agent_row.status = "running"
        session.commit()

        # ASSIST reasons over who's idle/busy but never touches the DB -- hand it the live snapshot
        run_payload = dict(payload or {})
        if assigned_to == "ASSIST":
            run_payload["agent_status"] = _build_agent_status(session)

        agent_class = AGENT_CLASSES.get(assigned_to, BaseAgent)
        agent = agent_class(config)
        result = agent.run(run_payload)

        task.status = agent.state
        task.result = result if agent.state == "done" else {"error": agent.error}
        # settles at done/failed rather than going back to idle -- a failure has to stay
        # visible on the status page, not flash by for one poll
        if agent_row is not None:
            agent_row.status = agent.state
        session.commit()

        # relay handoffs fire here on success -- each spawns pending rows the next tick picks up
        if agent.state == "done":
            _run_completion_hooks(session, task, assigned_to, result, agent_configs)
    except Exception as exc:
        # BaseAgent.run() already swallows the agent's own failures -- this catches everything
        # AROUND it: a dropped supabase connection, a commit failing, a task row deleted mid-tick.
        # without it the row sits at "running" forever, since the poller only ever queries "pending"
        # and nothing would pick it back up. a visible failure beats a silent zombie
        session.rollback()  # a failed commit poisons the session, nothing else works until this
        _mark_failed(session, task_id, assigned_to, f"{type(exc).__name__}: {exc}")
    finally:
        session.close()


@router.post("/tasks", response_model=TaskResponse, status_code=201)
def create_task(body: TaskCreateRequest, request: Request) -> Task:
    agent_configs: dict[str, AgentConfig] = request.app.state.agent_configs
    if body.assigned_to not in agent_configs:
        raise HTTPException(status_code=422, detail=f"'{body.assigned_to}' isn't a loaded agent")

    session = SessionLocal()
    try:
        # just drop a pending row and return -- the scheduler poller runs it on the next tick
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


@router.post("/tasks/{task_id}/approve", response_model=list[TaskResponse], status_code=201)
def approve_task(task_id: uuid.UUID, request: Request) -> list[Task]:
    """the Mode One check-in: releases a gated Prometheus task to spawn its Asmoday children.

    Only valid on a done Prometheus task that was held (auto_continue False) and not already approved.
    Runs the same _spawn_asmoday_children the auto path uses -- just triggered by the owner, not a hook.
    """
    agent_configs: dict[str, AgentConfig] = request.app.state.agent_configs
    session = SessionLocal()
    try:
        task = session.get(Task, task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

        payload = task.payload or {}
        # spell out exactly why an approve is refused -- these are the only tasks a check-in applies to
        if task.assigned_to != "Prometheus":
            raise HTTPException(status_code=400, detail="only a Prometheus task can be approved")
        if task.status != "done":
            raise HTTPException(status_code=400, detail="task isn't done yet, nothing to approve")
        if payload.get("auto_continue", True):
            raise HTTPException(status_code=400, detail="task wasn't gated (auto_continue), it already continued on its own")
        if payload.get("approved"):
            raise HTTPException(status_code=400, detail="task was already approved")

        # fresh dict, not an in-place mutation -- SQLAlchemy doesn't reliably flush a mutated JSONB dict
        task.payload = {**payload, "approved": True}
        session.commit()

        _spawn_asmoday_children(session, task, task.result or {}, agent_configs)
        return session.query(Task).filter(Task.parent_task_id == task_id).all()
    finally:
        session.close()
