"""PrometheusAgent, with the Anthropic client mocked throughout -- no real API call happens in this suite."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.config import AgentConfig
from app.agents.prometheus_agent import PrometheusAgent

VALID_PRD_JSON = json.dumps(
    {
        "scope": "a todo app",
        "requirements": ["add tasks", "mark done"],
        "constraints": ["no auth"],
        "task_breakdown": [{"title": "build API", "description": "CRUD endpoints"}],
        "open_questions": [],
    }
)


def _prometheus_config() -> AgentConfig:
    return AgentConfig(
        name="Prometheus",
        role="project manager",
        model="claude-sonnet-5",
        tools=[],
        schedule="on-demand",
        system_prompt="you are a test prometheus",
    )


def _mock_anthropic_client(response_text: str) -> MagicMock:
    # a real reply can have a ThinkingBlock before the TextBlock (adaptive thinking is
    # on by default) -- mock both so execute()'s block.type == "text" search is exercised
    thinking_block = MagicMock(type="thinking")
    text_block = MagicMock(type="text", text=response_text)
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[thinking_block, text_block])
    return client


def test_execute_calls_claude_with_own_system_prompt_and_model() -> None:
    config = _prometheus_config()
    agent = PrometheusAgent(config)
    mock_client = _mock_anthropic_client(VALID_PRD_JSON)

    with patch("app.agents.prometheus_agent.anthropic.Anthropic", return_value=mock_client):
        agent.execute({"request": "plan a todo app"})

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == config.model
    assert call_kwargs["system"].startswith(config.system_prompt)
    assert call_kwargs["messages"] == [{"role": "user", "content": "plan a todo app"}]


def test_execute_returns_parsed_json() -> None:
    agent = PrometheusAgent(_prometheus_config())
    mock_client = _mock_anthropic_client(VALID_PRD_JSON)

    with patch("app.agents.prometheus_agent.anthropic.Anthropic", return_value=mock_client):
        result = agent.execute({"request": "plan a todo app"})

    assert result["scope"] == "a todo app"
    assert result["task_breakdown"] == [{"title": "build API", "description": "CRUD endpoints"}]


def test_execute_raises_on_malformed_json() -> None:
    agent = PrometheusAgent(_prometheus_config())
    mock_client = _mock_anthropic_client("not json at all")

    with patch("app.agents.prometheus_agent.anthropic.Anthropic", return_value=mock_client):
        with pytest.raises(ValueError, match="invalid JSON"):
            agent.execute({"request": "plan a todo app"})


def test_run_ends_failed_with_raw_text_in_error_on_malformed_json() -> None:
    agent = PrometheusAgent(_prometheus_config())
    mock_client = _mock_anthropic_client("not json at all")

    with patch("app.agents.prometheus_agent.anthropic.Anthropic", return_value=mock_client):
        result = agent.run({"request": "plan a todo app"})

    assert agent.state == "failed"
    assert result is None
    assert "not json at all" in agent.error


def test_execute_raises_clear_error_when_no_text_block_at_all() -> None:
    # a real failure mode: thinking eats the whole max_tokens budget before any text
    # comes out, leaving content with no text block -- next(...) alone would raise a
    # bare StopIteration with an empty message, so this must be caught and re-raised
    agent = PrometheusAgent(_prometheus_config())
    thinking_only_client = MagicMock()
    thinking_only_client.messages.create.return_value = MagicMock(
        content=[MagicMock(type="thinking")], stop_reason="max_tokens"
    )

    with patch("app.agents.prometheus_agent.anthropic.Anthropic", return_value=thinking_only_client):
        with pytest.raises(ValueError, match="no text block"):
            agent.execute({"request": "plan a todo app"})
