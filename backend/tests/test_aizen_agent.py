"""AizenAgent, Anthropic client mocked throughout -- no real calls in this suite.

Same pattern as test_hermes_agent.py, with the twist that Aizen has two jobs: the tests cover
both task_types plus the failure paths (unknown task_type, malformed JSON, no text block).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.aizen_agent import AizenAgent
from app.agents.config import AgentConfig

WRITEUP_JSON = json.dumps(
    {
        "changelog_entry": "Added the Aizen writer agent.",
        "commit_message": "Add Aizen, the docs/content writer",
        "shareable_post": "Just wired up the writer agent in my multi-agent build...",
        "summary_for_assist": "Aizen is built and writes up finished changes.",
    }
)

SCHEMA_JSON = json.dumps({"diagram": "erDiagram\n    tasks ||--o{ tasks : spawns"})


def _aizen_config() -> AgentConfig:
    return AgentConfig(
        name="Aizen",
        role="writer",
        model="claude-sonnet-5",
        tools=[],
        schedule="on-demand",
        system_prompt="you are a test aizen",
    )


def _mock_anthropic_client(response_text: str) -> MagicMock:
    # thinking block before the text block, same as a real adaptive-thinking reply
    thinking_block = MagicMock(type="thinking")
    text_block = MagicMock(type="text", text=response_text)
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[thinking_block, text_block])
    return client


# ===== WRITEUP JOB =====


def test_writeup_returns_all_four_fields() -> None:
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(WRITEUP_JSON)):
        agent = AizenAgent(_aizen_config())
        result = agent.run(
            {"task_type": "writeup", "code": "def foo(): ...", "review_verdict": "looks correct"}
        )

    assert agent.state == "done"
    assert set(result) == {"changelog_entry", "commit_message", "shareable_post", "summary_for_assist"}


def test_writeup_feeds_code_and_verdict_into_the_prompt() -> None:
    # both inputs have to actually reach Claude, or the writeup is written blind
    client = _mock_anthropic_client(WRITEUP_JSON)
    with patch("anthropic.Anthropic", return_value=client):
        AizenAgent(_aizen_config()).execute(
            {"task_type": "writeup", "code": "SENTINEL_CODE", "review_verdict": "SENTINEL_VERDICT"}
        )

    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "SENTINEL_CODE" in user_content
    assert "SENTINEL_VERDICT" in user_content


def test_writeup_allows_null_shareable_post() -> None:
    # a mundane change gets shareable_post: null -- that's a valid result, not a failure
    mundane = json.dumps(
        {
            "changelog_entry": "Bumped a version string.",
            "commit_message": "Bump version",
            "shareable_post": None,
            "summary_for_assist": "Nothing portfolio-worthy here.",
        }
    )
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(mundane)):
        agent = AizenAgent(_aizen_config())
        result = agent.run({"task_type": "writeup", "code": "x", "review_verdict": "fine"})

    assert agent.state == "done"
    assert result["shareable_post"] is None


# ===== SCHEMA DIAGRAM JOB =====


def test_schema_diagram_returns_a_diagram() -> None:
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(SCHEMA_JSON)):
        agent = AizenAgent(_aizen_config())
        result = agent.run({"task_type": "schema_diagram"})

    assert agent.state == "done"
    assert set(result) == {"diagram"}
    assert "erDiagram" in result["diagram"]


def test_schema_diagram_prompt_carries_both_foreign_keys_and_forbids_invented_ones() -> None:
    # the finding from the pre-build check: the description must name BOTH FKs (parent_task_id
    # AND events.task_id) and say assigned_to is not a relationship, or the diagram comes out wrong
    client = _mock_anthropic_client(SCHEMA_JSON)
    with patch("anthropic.Anthropic", return_value=client):
        AizenAgent(_aizen_config()).execute({"task_type": "schema_diagram"})

    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "parent_task_id -> tasks.id" in user_content
    assert "events.task_id -> tasks.id" in user_content
    assert "assigned_to" in user_content  # explicitly called out as NOT a foreign key


# ===== FAILURE PATHS =====


def test_unknown_task_type_lands_failed_with_a_clear_message() -> None:
    # no Claude call should even happen -- a bad task_type is a caller bug, caught before the API
    with patch("anthropic.Anthropic") as mock_client:
        agent = AizenAgent(_aizen_config())
        agent.run({"task_type": "not_a_real_job"})

    assert agent.state == "failed"
    assert "unknown task_type" in agent.error
    mock_client.return_value.messages.create.assert_not_called()


def test_missing_task_type_lands_failed() -> None:
    agent = AizenAgent(_aizen_config())
    agent.run({"code": "x"})  # forgot task_type entirely

    assert agent.state == "failed"
    assert "unknown task_type" in agent.error


def test_execute_raises_on_malformed_json() -> None:
    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client("not json")):
        with pytest.raises(ValueError, match="invalid JSON"):
            AizenAgent(_aizen_config()).execute({"task_type": "schema_diagram"})


def test_execute_raises_clear_error_when_no_text_block_at_all() -> None:
    # the step-7 regression, guarded for Aizen too
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[], stop_reason="max_tokens")
    with patch("anthropic.Anthropic", return_value=client):
        with pytest.raises(ValueError, match="no text block"):
            AizenAgent(_aizen_config()).execute({"task_type": "writeup"})
