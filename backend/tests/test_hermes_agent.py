"""HermesAgent, with the adapters and the Anthropic client mocked -- no real calls in this suite.

Same pattern as test_prometheus_agent.py, plus one thing that only matters for Hermes: it must
call the adapters through the factory and never learn whether it got real or mock ones.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.agents.config import AgentConfig
from app.agents.hermes_agent import HermesAgent

WEB_FINDINGS = [
    {"title": "A post", "url": "https://example.com/a", "note": "relevant because X", "date": "2026-06"}
]
GITHUB_FINDINGS = [
    {
        "repo": "example-org/thing",
        "url": "https://github.com/example-org/thing",
        "note": "does a thing",
        "last_activity": "2026-07-01",
    }
]

VALID_RESEARCH_JSON = json.dumps(
    {
        "summary": "the space is moving toward custom orchestration",
        "web_findings": WEB_FINDINGS,
        "github_findings": GITHUB_FINDINGS,
        "recommendations": ["read the orchestrator repo before building"],
    }
)


def _hermes_config() -> AgentConfig:
    return AgentConfig(
        name="Hermes",
        role="researcher",
        model="claude-sonnet-5",
        tools=["web_search", "github"],
        schedule="on-demand",
        system_prompt="you are a test hermes",
    )


def _mock_anthropic_client(response_text: str) -> MagicMock:
    # thinking block first, same as a real adaptive-thinking reply
    thinking_block = MagicMock(type="thinking")
    text_block = MagicMock(type="text", text=response_text)
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[thinking_block, text_block])
    return client


def _mock_adapters():
    web = MagicMock()
    web.search.return_value = WEB_FINDINGS
    github = MagicMock()
    github.check_activity.return_value = GITHUB_FINDINGS
    return web, github


def test_execute_pulls_adapters_from_the_factory_and_passes_the_request(monkeypatch) -> None:
    web, github = _mock_adapters()
    monkeypatch.setattr("app.agents.hermes_agent.get_web_search_adapter", lambda: web)
    monkeypatch.setattr("app.agents.hermes_agent.get_github_adapter", lambda: github)

    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(VALID_RESEARCH_JSON)):
        HermesAgent(_hermes_config()).execute({"request": "research agent orchestration"})

    web.search.assert_called_once_with("research agent orchestration")
    github.check_activity.assert_called_once_with("research agent orchestration")


def test_execute_feeds_adapter_results_into_the_synthesis_call(monkeypatch) -> None:
    # the findings have to actually reach Claude -- otherwise the adapters are decoration
    web, github = _mock_adapters()
    monkeypatch.setattr("app.agents.hermes_agent.get_web_search_adapter", lambda: web)
    monkeypatch.setattr("app.agents.hermes_agent.get_github_adapter", lambda: github)
    client = _mock_anthropic_client(VALID_RESEARCH_JSON)

    with patch("anthropic.Anthropic", return_value=client):
        HermesAgent(_hermes_config()).execute({"request": "research agent orchestration"})

    user_message = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "https://example.com/a" in user_message
    assert "example-org/thing" in user_message


def test_execute_calls_claude_with_own_system_prompt_and_model(monkeypatch) -> None:
    web, github = _mock_adapters()
    monkeypatch.setattr("app.agents.hermes_agent.get_web_search_adapter", lambda: web)
    monkeypatch.setattr("app.agents.hermes_agent.get_github_adapter", lambda: github)
    client = _mock_anthropic_client(VALID_RESEARCH_JSON)

    with patch("anthropic.Anthropic", return_value=client):
        HermesAgent(_hermes_config()).execute({"request": "x"})

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["system"].startswith("you are a test hermes")


def test_run_ends_done_with_the_research_schema(monkeypatch) -> None:
    web, github = _mock_adapters()
    monkeypatch.setattr("app.agents.hermes_agent.get_web_search_adapter", lambda: web)
    monkeypatch.setattr("app.agents.hermes_agent.get_github_adapter", lambda: github)

    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client(VALID_RESEARCH_JSON)):
        agent = HermesAgent(_hermes_config())
        result = agent.run({"request": "research agent orchestration"})

    assert agent.state == "done"
    assert set(result) == {"summary", "web_findings", "github_findings", "recommendations"}
    # the recency fields are the owner's addition to the drafted schema -- they have to survive
    assert result["web_findings"][0]["date"] == "2026-06"
    assert result["github_findings"][0]["last_activity"] == "2026-07-01"


def test_run_ends_failed_when_an_adapter_blows_up(monkeypatch) -> None:
    # a dead network shouldn't crash the poll tick -- BaseAgent.run() catches it, task lands failed
    web, github = _mock_adapters()
    web.search.side_effect = ValueError("GitHub refused the search (403)")
    monkeypatch.setattr("app.agents.hermes_agent.get_web_search_adapter", lambda: web)
    monkeypatch.setattr("app.agents.hermes_agent.get_github_adapter", lambda: github)

    agent = HermesAgent(_hermes_config())
    agent.run({"request": "x"})

    assert agent.state == "failed"
    assert "403" in agent.error


def test_execute_raises_on_malformed_json(monkeypatch) -> None:
    web, github = _mock_adapters()
    monkeypatch.setattr("app.agents.hermes_agent.get_web_search_adapter", lambda: web)
    monkeypatch.setattr("app.agents.hermes_agent.get_github_adapter", lambda: github)

    with patch("anthropic.Anthropic", return_value=_mock_anthropic_client("not json")):
        with pytest.raises(ValueError, match="invalid JSON"):
            HermesAgent(_hermes_config()).execute({"request": "x"})


def test_execute_raises_clear_error_when_no_text_block_at_all(monkeypatch) -> None:
    # the step-7 regression, guarded for Hermes too
    web, github = _mock_adapters()
    monkeypatch.setattr("app.agents.hermes_agent.get_web_search_adapter", lambda: web)
    monkeypatch.setattr("app.agents.hermes_agent.get_github_adapter", lambda: github)
    client = MagicMock()
    client.messages.create.return_value = MagicMock(content=[], stop_reason="max_tokens")

    with patch("anthropic.Anthropic", return_value=client):
        with pytest.raises(ValueError, match="no text block"):
            HermesAgent(_hermes_config()).execute({"request": "x"})
