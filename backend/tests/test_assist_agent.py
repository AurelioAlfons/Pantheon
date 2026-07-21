"""AssistAgent, Anthropic client mocked throughout -- no real calls in this suite.

Mirrors test_hermes_agent.py's shape (one job, one call). The one ASSIST-specific thing worth
testing hard is the target guard: an LLM that picks Aizen/Khepri for a single_agent dispatch must
be rejected in code, not just discouraged in the prompt.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.assist_agent import AssistAgent
from app.agents.config import AgentConfig

FULL_PIPELINE_DECISION = json.dumps(
    {
        "mode": "full_pipeline",
        "target_agent": None,
        "use_hermes_research": False,
        "brief": "Build a todo app with add/complete/delete.",
        "reasoning": "Plain build request, no auto-run phrasing, no research angle.",
    }
)

SINGLE_AGENT_DECISION = json.dumps(
    {
        "mode": "single_agent",
        "target_agent": "Hermes",
        "use_hermes_research": False,
        "brief": "Research multi-agent orchestration tools.",
        "reasoning": "Owner asked for Hermes only, nothing downstream.",
    }
)


def _assist_config() -> AgentConfig:
    return AgentConfig(
        name="ASSIST",
        role="overseer",
        model="claude-sonnet-5",
        tools=[],
        schedule="on-demand",
        system_prompt="you are a test assist",
    )


def _mock_anthropic_client(response_text: str) -> MagicMock:
    thinking_block = MagicMock(type="thinking")
    text_block = MagicMock(type="text", text=response_text)
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[thinking_block, text_block])
    return client


# ===== HAPPY PATH =====


def test_execute_calls_claude_with_own_system_prompt_and_model() -> None:
    client = _mock_anthropic_client(FULL_PIPELINE_DECISION)
    with patch("anthropic.Anthropic", return_value=client):
        AssistAgent(_assist_config()).execute({"request": "build a todo app", "agent_status": {}})

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["system"].startswith("you are a test assist")


def test_execute_feeds_request_and_agent_status_into_the_prompt() -> None:
    # ASSIST reasons over who's busy -- both the request and the status snapshot must reach the call
    client = _mock_anthropic_client(FULL_PIPELINE_DECISION)
    with patch("anthropic.Anthropic", return_value=client):
        AssistAgent(_assist_config()).execute(
            {"request": "SENTINEL_REQUEST", "agent_status": {"Prometheus": "SENTINEL_STATUS"}}
        )

    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "SENTINEL_REQUEST" in user_content
    assert "SENTINEL_STATUS" in user_content


def test_returns_full_decision_schema_on_full_pipeline() -> None:
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(FULL_PIPELINE_DECISION)):
        agent = AssistAgent(_assist_config())
        result = agent.run({"request": "build a todo app", "agent_status": {}})

    assert agent.state == "done"
    assert set(result) == {"mode", "target_agent", "use_hermes_research", "brief", "reasoning"}
    assert result["mode"] == "full_pipeline"


def test_returns_full_decision_schema_on_single_agent() -> None:
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(SINGLE_AGENT_DECISION)):
        agent = AssistAgent(_assist_config())
        result = agent.run({"request": "have Hermes research X, that's it", "agent_status": {}})

    assert agent.state == "done"
    assert result["mode"] == "single_agent"
    assert result["target_agent"] == "Hermes"


# ===== THE TARGET GUARD =====


@pytest.mark.parametrize("bad_target", ["Aizen", "Khepri"])
def test_single_agent_target_of_aizen_or_khepri_is_rejected(bad_target: str) -> None:
    # the defensive guard -- these two can't be cold-dispatched, and a prompt alone won't guarantee it
    bad_decision = json.dumps(
        {
            "mode": "single_agent",
            "target_agent": bad_target,
            "use_hermes_research": False,
            "brief": "x",
            "reasoning": "x",
        }
    )
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(bad_decision)):
        agent = AssistAgent(_assist_config())
        agent.run({"request": "x", "agent_status": {}})

    assert agent.state == "failed"
    assert "invalid single_agent target" in agent.error


def test_full_pipeline_with_null_target_is_not_rejected() -> None:
    # the guard only applies to single_agent -- a null target on full_pipeline is correct, not an error
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(FULL_PIPELINE_DECISION)):
        agent = AssistAgent(_assist_config())
        agent.run({"request": "build a todo app", "agent_status": {}})

    assert agent.state == "done"


# ===== FAILURE PATHS =====


def test_execute_raises_on_malformed_json() -> None:
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client("not json")):
        with pytest.raises(ValueError, match="invalid JSON"):
            AssistAgent(_assist_config()).execute({"request": "x", "agent_status": {}})


def test_execute_raises_clear_error_when_no_text_block_at_all() -> None:
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[], stop_reason="max_tokens")
    with patch("anthropic.Anthropic", return_value=client):
        with pytest.raises(ValueError, match="no text block"):
            AssistAgent(_assist_config()).execute({"request": "x", "agent_status": {}})
