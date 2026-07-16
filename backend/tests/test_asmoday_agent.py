"""AsmodayAgent, with the Anthropic client mocked throughout -- no real API call happens in this suite."""

from unittest.mock import MagicMock, patch

import pytest

from app.agents.asmoday_agent import AsmodayAgent
from app.agents.config import AgentConfig


def _asmoday_config() -> AgentConfig:
    return AgentConfig(
        name="Asmoday",
        role="developer",
        model="claude-sonnet-5",
        tools=[],
        schedule="on-demand",
        system_prompt="you are a test asmoday",
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
    config = _asmoday_config()
    agent = AsmodayAgent(config)
    mock_client = _mock_anthropic_client("def build_api(): ...")

    with patch("app.agents.asmoday_agent.anthropic.Anthropic", return_value=mock_client):
        agent.execute({"request": "build the CRUD API"})

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == config.model
    assert call_kwargs["system"] == config.system_prompt
    assert call_kwargs["messages"] == [{"role": "user", "content": "build the CRUD API"}]


def test_execute_returns_code_result() -> None:
    agent = AsmodayAgent(_asmoday_config())
    mock_client = _mock_anthropic_client("def build_api(): ...")

    with patch("app.agents.asmoday_agent.anthropic.Anthropic", return_value=mock_client):
        result = agent.execute({"request": "build the CRUD API"})

    assert result == {"code": "def build_api(): ..."}


def test_run_ends_done_with_code_in_result() -> None:
    agent = AsmodayAgent(_asmoday_config())
    mock_client = _mock_anthropic_client("def build_api(): ...")

    with patch("app.agents.asmoday_agent.anthropic.Anthropic", return_value=mock_client):
        result = agent.run({"request": "build the CRUD API"})

    assert agent.state == "done"
    assert result == {"code": "def build_api(): ..."}


def test_execute_raises_clear_error_when_no_text_block_at_all() -> None:
    # a real failure mode, hit in manual step-7 verification: thinking eats the whole
    # max_tokens budget before any text comes out, leaving content with no text block --
    # next(...) alone would raise a bare StopIteration with an empty message
    agent = AsmodayAgent(_asmoday_config())
    thinking_only_client = MagicMock()
    thinking_only_client.messages.create.return_value = MagicMock(
        content=[MagicMock(type="thinking")], stop_reason="max_tokens"
    )

    with patch("app.agents.asmoday_agent.anthropic.Anthropic", return_value=thinking_only_client):
        with pytest.raises(ValueError, match="no text block"):
            agent.execute({"request": "build the CRUD API"})
