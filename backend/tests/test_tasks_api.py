"""POST /tasks + GET /tasks/{id} (+ /children), with both agents' execute() mocked -- no real Claude call in this suite.

Can't use test_database.py's rollback-per-test fixture here: the background job that
actually runs the agent opens its own connection, separate from any transaction this
test might hold open, so it needs to see rows for real. Commit for real, clean up after.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
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
    # the plain TestClient(app) form never runs the lifespan, so app.state.agent_configs
    # stays unset -- the "with" form is what actually triggers startup/shutdown
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def created_task_ids():
    # a Prometheus task now spawns real Asmoday children -- delete those first, the FK
    # on parent_task_id would reject deleting the parent while a child still references it
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


def test_post_tasks_returns_201(client: TestClient, created_task_ids: list[str]) -> None:
    mock_prometheus, mock_asmoday = _mock_agents()
    with mock_prometheus, mock_asmoday:
        response = client.post(
            "/tasks",
            json={"created_by": "owner", "assigned_to": "Prometheus", "payload": {"request": "plan a todo app"}},
        )

    assert response.status_code == 201
    body = response.json()
    created_task_ids.append(body["id"])
    assert body["assigned_to"] == "Prometheus"
    assert body["status"] == "pending"


def test_get_task_shows_done_with_structured_result(client: TestClient, created_task_ids: list[str]) -> None:
    mock_prometheus, mock_asmoday = _mock_agents()
    with mock_prometheus, mock_asmoday:
        post_response = client.post(
            "/tasks",
            json={"created_by": "owner", "assigned_to": "Prometheus", "payload": {"request": "plan a todo app"}},
        )
    task_id = post_response.json()["id"]
    created_task_ids.append(task_id)

    get_response = client.get(f"/tasks/{task_id}")

    assert get_response.status_code == 200
    body = get_response.json()
    assert body["status"] == "done"
    assert body["result"] == VALID_PRD


def test_prometheus_done_spawns_one_asmoday_child_per_task_breakdown_item(
    client: TestClient, created_task_ids: list[str]
) -> None:
    mock_prometheus, mock_asmoday = _mock_agents()
    with mock_prometheus, mock_asmoday:
        post_response = client.post(
            "/tasks",
            json={"created_by": "owner", "assigned_to": "Prometheus", "payload": {"request": "plan a todo app"}},
        )
    task_id = post_response.json()["id"]
    created_task_ids.append(task_id)

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
    mock_prometheus, mock_asmoday = _mock_agents()
    with mock_prometheus, mock_asmoday:
        # Asmoday itself has no task_breakdown to spawn from -- its own children list stays empty
        response = client.post(
            "/tasks",
            json={"created_by": "owner", "assigned_to": "Asmoday", "payload": {"request": "build X"}},
        )
    task_id = response.json()["id"]
    created_task_ids.append(task_id)

    children_response = client.get(f"/tasks/{task_id}/children")

    assert children_response.status_code == 200
    assert children_response.json() == []
