"""KhepriAgent, Anthropic client mocked throughout -- no real calls in this suite.

Same pattern as test_hermes_agent.py / test_aizen_agent.py. Khepri is the simplest of the four:
one job, one output shape, content_type only reframes the prompt. So the tests are mostly about
the framing reaching the prompt and the unknown-content_type guard firing before any Claude call.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.config import AgentConfig
from app.agents.khepri_agent import KhepriAgent

VALID_VERDICT_JSON = json.dumps(
    {
        "summary": "The code is correct and readable.",
        "issues": [{"severity": "minor", "description": "A docstring is missing on one helper."}],
        "open_questions": ["Is the empty-list case expected here?"],
        "recommendation": "proceed",
    }
)


def _khepri_config() -> AgentConfig:
    return AgentConfig(
        name="Khepri",
        role="reviewer",
        model="claude-sonnet-5",
        tools=[],
        schedule="on-demand",
        system_prompt="you are a test khepri",
    )


def _mock_anthropic_client(response_text: str) -> MagicMock:
    # thinking block before the text block, same as a real adaptive-thinking reply
    thinking_block = MagicMock(type="thinking")
    text_block = MagicMock(type="text", text=response_text)
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[thinking_block, text_block])
    return client


# ===== HAPPY PATH =====


def test_execute_calls_claude_with_own_system_prompt_and_model() -> None:
    client = _mock_anthropic_client(VALID_VERDICT_JSON)
    with patch("anthropic.Anthropic", return_value=client):
        KhepriAgent(_khepri_config()).execute({"content_type": "code", "content": "def foo(): ..."})

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["system"].startswith("you are a test khepri")


def test_execute_feeds_content_into_the_prompt() -> None:
    # the thing being reviewed has to actually reach Claude, or Khepri is reviewing nothing
    client = _mock_anthropic_client(VALID_VERDICT_JSON)
    with patch("anthropic.Anthropic", return_value=client):
        KhepriAgent(_khepri_config()).execute({"content_type": "code", "content": "SENTINEL_CONTENT"})

    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "SENTINEL_CONTENT" in user_content


@pytest.mark.parametrize(
    "content_type,expected_framing",
    [
        ("code", "reviewing code written by Asmoday"),
        ("prd", "reviewing a PRD written by Prometheus"),
        ("draft", "reviewing a draft written by Aizen"),
    ],
)
def test_each_content_type_reframes_the_prompt(content_type: str, expected_framing: str) -> None:
    client = _mock_anthropic_client(VALID_VERDICT_JSON)
    with patch("anthropic.Anthropic", return_value=client):
        KhepriAgent(_khepri_config()).execute({"content_type": content_type, "content": "x"})

    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert expected_framing in user_content


def test_run_ends_done_with_the_verdict_schema() -> None:
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(VALID_VERDICT_JSON)):
        agent = KhepriAgent(_khepri_config())
        result = agent.run({"content_type": "code", "content": "def foo(): ..."})

    assert agent.state == "done"
    assert set(result) == {"summary", "issues", "open_questions", "recommendation"}
    assert result["issues"][0]["severity"] == "minor"
    assert result["recommendation"] == "proceed"


# ===== FAILURE PATHS =====


def test_unknown_content_type_lands_failed_with_a_clear_message() -> None:
    # a bad content_type is a caller bug -- no Claude call should even happen
    with patch("anthropic.Anthropic") as mock_client:
        agent = KhepriAgent(_khepri_config())
        agent.run({"content_type": "spreadsheet", "content": "x"})

    assert agent.state == "failed"
    assert "unknown content_type" in agent.error
    mock_client.return_value.messages.create.assert_not_called()


def test_missing_content_type_lands_failed() -> None:
    agent = KhepriAgent(_khepri_config())
    agent.run({"content": "x"})  # forgot content_type entirely

    assert agent.state == "failed"
    assert "unknown content_type" in agent.error


def test_execute_raises_on_malformed_json() -> None:
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client("not json")):
        with pytest.raises(ValueError, match="invalid JSON"):
            KhepriAgent(_khepri_config()).execute({"content_type": "code", "content": "x"})


def test_execute_raises_clear_error_when_no_text_block_at_all() -> None:
    # the step-7 regression, guarded for Khepri too
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[], stop_reason="max_tokens")
    with patch("anthropic.Anthropic", return_value=client):
        with pytest.raises(ValueError, match="no text block"):
            KhepriAgent(_khepri_config()).execute({"content_type": "code", "content": "x"})
