"""POST /tasks + GET /tasks/{id} (+ /children), driving the scheduler poller by hand so no real Claude call fires.

Two things differ from the step-7 version:
- POST /tasks no longer runs the agent -- it just inserts a pending row. Nothing reaches "done"
  until a poll tick runs, so tests call poll_pending_tasks() explicitly where they used to just POST.
- A full Prometheus -> Asmoday chain takes TWO ticks: tick one runs Prometheus and spawns pending
  children, tick two runs those children. So the children test polls twice.

Real rows are committed (the poller opens its own connection and must see them), then cleaned up.
The client fixture patches out start_scheduler so the real background poller doesn't race these.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.scheduler import poll_pending_tasks
from app.main import app
from app.models import Task

VALID_PRD = {
    "scope": "a todo app",
    "requirements": ["add tasks"],
    "constraints": [],
    "task_breakdown": [{"title": "build API", "description": "CRUD endpoints"}],
    "open_questions": [],
}

VALID_CODE_RESULT = {"code": "def build_api(): ..."}


@pytest.fixture(scope="module")
def client():
    # patch out the real background poller -- otherwise it ticks every few seconds against
    # these rows and races the explicit poll_pending_tasks() calls the tests make by hand.
    # the "with" form still runs the lifespan, so app.state.agent_configs is set.
    with patch("app.main.start_scheduler"):
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def created_task_ids():
    # a Prometheus task spawns real Asmoday children -- delete those first, the FK on
    # parent_task_id rejects deleting a parent while a child still references it
    ids: list[str] = []
    yield ids
    with SessionLocal() as session:
        for task_id in ids:
            for child in session.query(Task).filter(Task.parent_task_id == task_id).all():
                session.delete(child)
        session.commit()
        for task_id in ids:
            task = session.get(Task, task_id)
            if task is not None:
                session.delete(task)
        session.commit()


def _mock_agents():
    return (
        patch("app.agents.prometheus_agent.PrometheusAgent.execute", return_value=VALID_PRD),
        patch("app.agents.asmoday_agent.AsmodayAgent.execute", return_value=VALID_CODE_RESULT),
    )


def test_post_tasks_returns_201_and_stays_pending(client: TestClient, created_task_ids: list[str]) -> None:
    # no poll tick -- so the row must still be pending, proving POST doesn't process anymore
    response = client.post(
        "/tasks",
        json={"created_by": "owner", "assigned_to": "Prometheus", "payload": {"request": "plan a todo app"}},
    )

    assert response.status_code == 201
    body = response.json()
    created_task_ids.append(body["id"])
    assert body["assigned_to"] == "Prometheus"
    assert body["status"] == "pending"


def test_poll_tick_flips_task_to_done_with_structured_result(client: TestClient, created_task_ids: list[str]) -> None:
    mock_prometheus, mock_asmoday = _mock_agents()
    with mock_prometheus, mock_asmoday:
        post_response = client.post(
            "/tasks",
            json={"created_by": "owner", "assigned_to": "Prometheus", "payload": {"request": "plan a todo app"}},
        )
        task_id = post_response.json()["id"]
        created_task_ids.append(task_id)

        poll_pending_tasks(app.state.agent_configs)  # one tick runs the Prometheus task

    get_response = client.get(f"/tasks/{task_id}")

    assert get_response.status_code == 200
    body = get_response.json()
    assert body["status"] == "done"
    assert body["result"] == VALID_PRD


def test_two_ticks_run_prometheus_then_its_asmoday_children(client: TestClient, created_task_ids: list[str]) -> None:
    mock_prometheus, mock_asmoday = _mock_agents()
    with mock_prometheus, mock_asmoday:
        post_response = client.post(
            "/tasks",
            json={"created_by": "owner", "assigned_to": "Prometheus", "payload": {"request": "plan a todo app"}},
        )
        task_id = post_response.json()["id"]
        created_task_ids.append(task_id)

        poll_pending_tasks(app.state.agent_configs)  # tick 1: runs Prometheus, spawns children pending
        poll_pending_tasks(app.state.agent_configs)  # tick 2: runs the spawned Asmoday children

    children_response = client.get(f"/tasks/{task_id}/children")

    assert children_response.status_code == 200
    children = children_response.json()
    assert len(children) == len(VALID_PRD["task_breakdown"])
    child = children[0]
    assert child["assigned_to"] == "Asmoday"
    assert child["parent_task_id"] == task_id
    assert child["depth"] == 1
    assert child["status"] == "done"
    assert child["result"] == VALID_CODE_RESULT


def test_post_tasks_unknown_agent_returns_422(client: TestClient) -> None:
    response = client.post(
        "/tasks",
        json={"created_by": "owner", "assigned_to": "NotARealAgent", "payload": {}},
    )
    assert response.status_code == 422


def test_get_task_unknown_id_returns_404(client: TestClient) -> None:
    response = client.get("/tasks/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_get_task_children_empty_for_task_with_no_children(client: TestClient, created_task_ids: list[str]) -> None:
    # Asmoday spawns no children -- its children list is empty whether or not it has run yet,
    # so no poll tick is needed for this assertion
    response = client.post(
        "/tasks",
        json={"created_by": "owner", "assigned_to": "Asmoday", "payload": {"request": "build X"}},
    )
    task_id = response.json()["id"]
    created_task_ids.append(task_id)

    children_response = client.get(f"/tasks/{task_id}/children")

    assert children_response.status_code == 200
    assert children_response.json() == []
