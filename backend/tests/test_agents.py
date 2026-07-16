"""Step 5: config loader, state transitions, and DummyAgent's happy/failure paths."""

from pathlib import Path

import pytest

from app.agents.config import AgentConfig
from app.agents.config_loader import load_all_agent_configs
from app.agents.dummy_agent import DummyAgent
from app.agents.state import transition

# agents/ lives at repo root, two levels up from backend/tests/
REPO_AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


def _dummy_config() -> AgentConfig:
    return AgentConfig(
        name="TestDummy",
        role="tester",
        model="claude-sonnet-5",
        tools=[],
        schedule="on-demand",
        system_prompt="test prompt",
    )


def test_load_all_agent_configs_returns_all_six_keyed_by_name() -> None:
    configs = load_all_agent_configs(REPO_AGENTS_DIR)

    assert set(configs) == {"ASSIST", "Prometheus", "Asmoday", "Hermes", "Aizen", "Khepri"}

    prometheus = configs["Prometheus"]
    assert prometheus.role == "Project manager — PRDs, plans, diagrams, task breakdown for Asmoday"
    assert prometheus.model == "claude-sonnet-5"
    assert prometheus.schedule == "on-demand"
    assert prometheus.tools == []


def test_transition_allows_happy_path() -> None:
    state = transition("idle", "running")
    state = transition(state, "done")
    assert state == "done"


def test_transition_rejects_illegal_jump() -> None:
    # done -> running should never happen -- fail loud, not quiet
    with pytest.raises(ValueError, match="invalid transition: done -> running"):
        transition("done", "running")


def test_dummy_agent_happy_path_ends_done() -> None:
    agent = DummyAgent(_dummy_config())
    result = agent.run({"hello": "world"})

    assert agent.state == "done"
    assert result == {"echo": {"hello": "world"}}


def test_dummy_agent_failure_path_ends_failed_without_raising() -> None:
    agent = DummyAgent(_dummy_config(), fail=True)
    result = agent.run({})  # must not raise -- run() swallows it into the failed state

    assert agent.state == "failed"
    assert result is None
    assert agent.error == "dummy failure for testing"
