"""GET /agents/status -- boot seeding, and an agent's status tracking a real task's lifecycle.

Same shape as test_tasks_api.py: real rows against the real DB, Anthropic mocked so no Claude
call fires, and start_scheduler patched out so the background poller doesn't race the hand-driven
poll ticks.

Agent rows are NOT cleaned up -- unlike tasks, they're permanent app data that boot seeds anyway.
Task rows still are.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.scheduler import poll_pending_tasks
from app.main import app, seed_agents
from app.models import Agent, Task

EXPECTED_AGENTS = {"ASSIST", "Prometheus", "Asmoday", "Hermes", "Aizen", "Khepri"}

VALID_PRD = {
    "scope": "a todo app",
    "requirements": ["add tasks"],
    "constraints": [],
    "task_breakdown": [],  # empty on purpose -- no Asmoday children to clean up, this test is about status
    "open_questions": [],
}


@pytest.fixture(scope="module")
def client():
    with patch("app.main.start_scheduler"):
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def created_task_ids():
    ids: list[str] = []
    yield ids
    with SessionLocal() as session:
        for task_id in ids:
            task = session.get(Task, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


def _status_of(client: TestClient, name: str) -> str:
    rows = client.get("/agents/status").json()
    return next(row["status"] for row in rows if row["name"] == name)


def test_boot_seeds_all_six_agents(client: TestClient) -> None:
    response = client.get("/agents/status")

    assert response.status_code == 200
    rows = response.json()
    assert {row["name"] for row in rows} == EXPECTED_AGENTS
    for row in rows:
        assert row["role"]
        assert row["model"]
        assert row["status"] in {"idle", "running", "done", "failed"}


def test_seeding_twice_does_not_duplicate_rows(client: TestClient) -> None:
    # the whole point of keying on name -- every restart re-runs this, rows must not pile up
    seed_agents(app.state.agent_configs)

    with SessionLocal() as session:
        assert session.query(Agent).filter(Agent.name.in_(EXPECTED_AGENTS)).count() == len(EXPECTED_AGENTS)


def test_task_run_flips_agent_to_running_then_settles_on_done(
    client: TestClient, created_task_ids: list[str]
) -> None:
    seen_mid_run: list[str] = []

    def peek_then_finish(payload):
        # read the agent's status from a separate session while the run is in flight --
        # proves "running" is actually committed during the task, not just set after it
        seen_mid_run.append(_status_of(client, "Prometheus"))
        return VALID_PRD

    with patch("app.agents.prometheus_agent.PrometheusAgent.execute", side_effect=peek_then_finish):
        post_response = client.post(
            "/tasks",
            json={"created_by": "owner", "assigned_to": "Prometheus", "payload": {"request": "plan a todo app"}},
        )
        created_task_ids.append(post_response.json()["id"])

        poll_pending_tasks(app.state.agent_configs)

    assert seen_mid_run == ["running"]
    assert _status_of(client, "Prometheus") == "done"

    # a tick with nothing pending must leave it alone -- status settles at done, never back to idle
    poll_pending_tasks(app.state.agent_configs)
    assert _status_of(client, "Prometheus") == "done"


def test_failed_task_leaves_agent_status_failed(client: TestClient, created_task_ids: list[str]) -> None:
    with patch("app.agents.asmoday_agent.AsmodayAgent.execute", side_effect=ValueError("claude said no")):
        post_response = client.post(
            "/tasks",
            json={"created_by": "owner", "assigned_to": "Asmoday", "payload": {"request": "build X"}},
        )
        created_task_ids.append(post_response.json()["id"])

        poll_pending_tasks(app.state.agent_configs)

    assert _status_of(client, "Asmoday") == "failed"


def test_crash_outside_agent_run_lands_on_failed_not_stuck_running(
    client: TestClient, created_task_ids: list[str]
) -> None:
    # BaseAgent.run() swallows the agent's own errors, so this fakes the other kind: something
    # blowing up AROUND it (a dropped connection, a bad commit). without the except in
    # _run_agent_task both rows would sit at "running" forever -- the poller only queries "pending"
    post_response = client.post(
        "/tasks",
        json={"created_by": "owner", "assigned_to": "Prometheus", "payload": {"request": "plan a todo app"}},
    )
    task_id = post_response.json()["id"]
    created_task_ids.append(task_id)

    with patch("app.api.tasks._spawn_asmoday_children", side_effect=RuntimeError("supabase fell over")):
        with patch("app.agents.prometheus_agent.PrometheusAgent.execute", return_value=VALID_PRD):
            poll_pending_tasks(app.state.agent_configs)

    assert _status_of(client, "Prometheus") == "failed"
    task = client.get(f"/tasks/{task_id}").json()
    assert task["status"] == "failed"
    assert "supabase fell over" in task["result"]["error"]


def test_boot_resets_stale_running_but_keeps_failed(client: TestClient) -> None:
    # a hard crash mid-run can't run the except path, so seed_agents is the backstop.
    # failed/done must survive a restart though -- that's the whole "failures stay visible" decision
    with SessionLocal() as session:
        session.query(Agent).filter(Agent.name == "Hermes").one().status = "running"
        session.query(Agent).filter(Agent.name == "Khepri").one().status = "failed"
        session.commit()

    seed_agents(app.state.agent_configs)  # what a reboot does

    assert _status_of(client, "Hermes") == "idle"
    assert _status_of(client, "Khepri") == "failed"
