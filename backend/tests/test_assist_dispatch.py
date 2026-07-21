"""ASSIST dispatch orchestration -- real DB rows, real poll ticks, mirrors test_tasks_api.py.

This is where the relay wiring is proven: ASSIST's decision becoming task rows, the check-in gate
holding (or not) per mode, the Hermes-research bridge, and the approve endpoint. Every agent's
execute() is mocked, so no real Claude call fires -- the point here is the plumbing, not the LLM.

Each test ticks the poller exactly as many times as the hops it wants to run, and patches exactly
the agents that should run. An un-patched agent running would mean a real API call, so a stray tick
would fail loudly rather than silently cost money.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.scheduler import poll_pending_tasks
from app.main import app
from app.models import Task

# ===== canned agent outputs =====

VALID_PRD = {
    "scope": "a todo app",
    "requirements": ["add tasks"],
    "constraints": [],
    "task_breakdown": [{"title": "build API", "description": "CRUD endpoints"}],
    "open_questions": [],
}
VALID_CODE = {"code": "def build_api(): ..."}
RESEARCH_RESULT = {
    "summary": "custom orchestration is trending over frameworks",
    "web_findings": [],
    "github_findings": [],
    "recommendations": ["use a database-backed task queue"],
}


def _decision(**overrides) -> dict:
    """an ASSIST decision with sensible defaults -- override just the fields a test cares about"""
    base = {
        "mode": "full_pipeline",
        "target_agent": None,
        "use_hermes_research": False,
        "brief": "Build a todo app.",
        "reasoning": "test",
    }
    base.update(overrides)
    return base


# ===== fixtures =====


@pytest.fixture(scope="module")
def client():
    # patch out the real background poller so it doesn't race the hand-driven ticks (same as test_tasks_api)
    with patch("app.main.start_scheduler"):
        with TestClient(app) as test_client:
            yield test_client


def _delete_subtree(session, root_id) -> None:
    """deletes a whole task chain bottom-up -- the FK on parent_task_id rejects deleting a parent first"""
    for child in session.query(Task).filter(Task.parent_task_id == root_id).all():
        _delete_subtree(session, child.id)
    task = session.get(Task, root_id)
    if task is not None:
        session.delete(task)
    session.commit()


@pytest.fixture
def roots():
    # track root task ids; teardown wipes each one's entire chain (ASSIST -> ... -> Asmoday)
    ids: list = []
    yield ids
    with SessionLocal() as session:
        for root_id in ids:
            _delete_subtree(session, root_id)


def _post_assist(client, roots, request_text="build a todo app") -> str:
    task = client.post(
        "/tasks", json={"created_by": "owner", "assigned_to": "ASSIST", "payload": {"request": request_text}}
    ).json()
    roots.append(task["id"])
    return task["id"]


def _insert_task(roots, **fields) -> str:
    """drops a task straight into the table (used to set up a pre-done Prometheus task for approve tests)"""
    with SessionLocal() as session:
        task = Task(created_by="owner", **fields)
        session.add(task)
        session.commit()
        session.refresh(task)
        roots.append(task.id)
        return str(task.id)


def _children(client, task_id) -> list[dict]:
    return client.get(f"/tasks/{task_id}/children").json()


# ===== single_agent =====


def test_single_agent_spawns_one_task_to_the_named_agent(client, roots) -> None:
    # only ASSIST runs (one tick) -- the Hermes child stays pending, so no real Hermes call fires
    assist_id = _post_assist(client, roots, "have Hermes research X, that's it")
    with patch("app.agents.assist_agent.AssistAgent.execute", return_value=_decision(
        mode="single_agent", target_agent="Hermes", brief="Research X."
    )):
        poll_pending_tasks(app.state.agent_configs)

    children = _children(client, assist_id)
    assert len(children) == 1
    assert children[0]["assigned_to"] == "Hermes"
    assert children[0]["payload"]["request"] == "Research X."


# ===== full_pipeline / full_auto, no research =====


def test_full_pipeline_spawns_gated_prometheus(client, roots) -> None:
    assist_id = _post_assist(client, roots)
    with patch("app.agents.assist_agent.AssistAgent.execute", return_value=_decision(mode="full_pipeline")):
        poll_pending_tasks(app.state.agent_configs)

    children = _children(client, assist_id)
    assert len(children) == 1
    assert children[0]["assigned_to"] == "Prometheus"
    assert children[0]["payload"]["auto_continue"] is False  # gated -- waits for /approve


def test_full_auto_runs_prometheus_then_asmoday_with_no_approval(client, roots) -> None:
    assist_id = _post_assist(client, roots, "build a todo app, run it end to end, don't ask me")
    with patch("app.agents.assist_agent.AssistAgent.execute", return_value=_decision(mode="full_auto")), \
         patch("app.agents.prometheus_agent.PrometheusAgent.execute", return_value=VALID_PRD), \
         patch("app.agents.asmoday_agent.AsmodayAgent.execute", return_value=VALID_CODE):
        poll_pending_tasks(app.state.agent_configs)  # tick 1: ASSIST -> spawn Prometheus (auto_continue True)
        poll_pending_tasks(app.state.agent_configs)  # tick 2: Prometheus -> done -> auto-spawn Asmoday
        poll_pending_tasks(app.state.agent_configs)  # tick 3: Asmoday runs

    prometheus = _children(client, assist_id)[0]
    assert prometheus["payload"]["auto_continue"] is True
    asmoday_children = _children(client, prometheus["id"])
    assert len(asmoday_children) == len(VALID_PRD["task_breakdown"])
    assert asmoday_children[0]["assigned_to"] == "Asmoday"
    assert asmoday_children[0]["status"] == "done"  # ran with no approve call -- Mode Two is hands-off


# ===== full_pipeline WITH Hermes research bridge =====


def test_research_bridge_spawns_hermes_then_prometheus_but_holds_the_gate(client, roots) -> None:
    assist_id = _post_assist(client, roots)
    with patch("app.agents.assist_agent.AssistAgent.execute", return_value=_decision(
        mode="full_pipeline", use_hermes_research=True
    )), patch("app.agents.hermes_agent.HermesAgent.execute", return_value=RESEARCH_RESULT), \
         patch("app.agents.prometheus_agent.PrometheusAgent.execute", return_value=VALID_PRD):
        poll_pending_tasks(app.state.agent_configs)  # tick 1: ASSIST -> spawn Hermes (research marker)
        poll_pending_tasks(app.state.agent_configs)  # tick 2: Hermes -> done -> spawn Prometheus w/ findings
        poll_pending_tasks(app.state.agent_configs)  # tick 3: Prometheus -> done -> gate holds, no Asmoday

    hermes = _children(client, assist_id)[0]
    assert hermes["assigned_to"] == "Hermes"

    prometheus = _children(client, hermes["id"])[0]
    assert prometheus["assigned_to"] == "Prometheus"
    assert "custom orchestration is trending" in prometheus["payload"]["request"]  # research folded in
    assert prometheus["payload"]["auto_continue"] is False

    assert _children(client, prometheus["id"]) == []  # the check-in gate held -- no Asmoday yet


def test_standalone_hermes_without_marker_spawns_nothing(client, roots) -> None:
    # a Mode Three "have Hermes research X" task has no purpose marker -- the bridge must NOT fire
    hermes_id = _insert_task(
        roots, status="pending", assigned_to="Hermes", payload={"request": "research X"}
    )
    with patch("app.agents.hermes_agent.HermesAgent.execute", return_value=RESEARCH_RESULT):
        poll_pending_tasks(app.state.agent_configs)

    assert _children(client, hermes_id) == []  # no Prometheus spawned


# ===== approve endpoint =====


def _gated_prometheus(roots) -> str:
    """a done Prometheus task held at the check-in -- the exact state /approve is meant to release"""
    return _insert_task(
        roots, status="done", assigned_to="Prometheus", payload={"auto_continue": False}, result=VALID_PRD
    )


def test_approve_releases_the_gated_prometheus_task(client, roots) -> None:
    prometheus_id = _gated_prometheus(roots)
    response = client.post(f"/tasks/{prometheus_id}/approve")

    assert response.status_code == 201
    children = response.json()
    assert len(children) == len(VALID_PRD["task_breakdown"])
    assert children[0]["assigned_to"] == "Asmoday"


def test_approve_twice_is_refused(client, roots) -> None:
    prometheus_id = _gated_prometheus(roots)
    assert client.post(f"/tasks/{prometheus_id}/approve").status_code == 201
    second = client.post(f"/tasks/{prometheus_id}/approve")
    assert second.status_code == 400  # idempotency guard -- already approved


@pytest.mark.parametrize(
    "fields,reason",
    [
        ({"status": "done", "assigned_to": "Asmoday", "payload": {"auto_continue": False}}, "wrong agent"),
        ({"status": "pending", "assigned_to": "Prometheus", "payload": {"auto_continue": False}}, "not done"),
        ({"status": "done", "assigned_to": "Prometheus", "payload": {"auto_continue": True}}, "not gated"),
    ],
)
def test_approve_refuses_a_task_that_isnt_a_gated_prometheus(client, roots, fields, reason) -> None:
    task_id = _insert_task(roots, result=VALID_PRD, **fields)
    response = client.post(f"/tasks/{task_id}/approve")
    assert response.status_code == 400, reason
