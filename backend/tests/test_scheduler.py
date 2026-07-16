"""poll_pending_tasks -- the real step-8 proof: a row processed with no API request, straight from the table.

Inserts rows directly via SessionLocal (no TestClient, no POST /tasks), mocks the agent's
execute(), and calls the poller by hand. That's the "manually inserted row gets processed" test.
"""

import uuid
from unittest.mock import patch

import pytest

from app.agents.config import AgentConfig
from app.core.database import SessionLocal
from app.core.scheduler import poll_pending_tasks
from app.models import Task

# a real PRD with an empty task_breakdown -- so a done Prometheus task spawns no children,
# keeping this test to exactly one row in / one row out, nothing to clean up but the one insert
EMPTY_PRD = {"scope": "x", "requirements": [], "constraints": [], "task_breakdown": [], "open_questions": []}


def _prometheus_config() -> AgentConfig:
    return AgentConfig(
        name="Prometheus",
        role="project manager",
        model="claude-sonnet-5",
        tools=[],
        schedule="on-demand",
        system_prompt="you are a test prometheus",
    )


@pytest.fixture
def cleanup_task_ids():
    ids: list[uuid.UUID] = []
    yield ids
    with SessionLocal() as session:
        for task_id in ids:
            task = session.get(Task, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


def _insert_pending_task(assigned_to: str) -> uuid.UUID:
    with SessionLocal() as session:
        task = Task(status="pending", created_by="owner", assigned_to=assigned_to, payload={"request": "x"})
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.id


def test_poll_processes_manually_inserted_pending_row(cleanup_task_ids: list[uuid.UUID]) -> None:
    task_id = _insert_pending_task("Prometheus")
    cleanup_task_ids.append(task_id)

    with patch("app.agents.prometheus_agent.PrometheusAgent.execute", return_value=EMPTY_PRD):
        poll_pending_tasks({"Prometheus": _prometheus_config()})

    with SessionLocal() as session:
        assert session.get(Task, task_id).status == "done"


def test_poll_skips_row_with_unknown_agent(cleanup_task_ids: list[uuid.UUID]) -> None:
    # a hand-inserted row naming an agent that isn't loaded -- the poller skips it, no crash,
    # and it stays pending rather than taking down the whole tick
    task_id = _insert_pending_task("Ghost")
    cleanup_task_ids.append(task_id)

    poll_pending_tasks({"Prometheus": _prometheus_config()})

    with SessionLocal() as session:
        assert session.get(Task, task_id).status == "pending"
