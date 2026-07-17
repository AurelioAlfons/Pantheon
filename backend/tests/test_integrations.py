"""The adapter pattern: real adapters with the network mocked, mocks checked for their canned shape.

The load-bearing test here is test_demo_mode_never_touches_the_network. The whole reason the
factory exists is so a public demo can't rack up API cost or hammer GitHub's rate limit by
accident -- if that guarantee is ever quietly broken, this is what catches it.
"""

from unittest.mock import MagicMock, patch

import pytest

from app.integrations.factory import get_github_adapter, get_web_search_adapter
from app.integrations.github import MockGitHubAdapter, RealGitHubAdapter
from app.integrations.web_search import MockWebSearchAdapter, RealWebSearchAdapter

GITHUB_API_RESPONSE = {
    "items": [
        {
            "full_name": "example-org/thing",
            "html_url": "https://github.com/example-org/thing",
            "description": "does a thing",
            "pushed_at": "2026-07-01T12:34:56Z",
        }
    ]
}

WEB_SEARCH_JSON = (
    '{"findings": [{"title": "A post", "url": "https://example.com/a", '
    '"note": "relevant because X", "date": "2026-06"}]}'
)


def _claude_reply(text: str):
    """fakes an anthropic response object -- .content is a list of blocks, not a string"""
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


# ===== REAL WEB SEARCH =====


def test_real_web_search_declares_the_current_tool_version() -> None:
    # _20260209 (dynamic filtering), not the older _20250305 basic variant
    with patch("anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = _claude_reply(WEB_SEARCH_JSON)
        RealWebSearchAdapter().search("agent orchestration")

    tools = mock_client.return_value.messages.create.call_args.kwargs["tools"]
    assert tools[0]["type"] == "web_search_20260209"
    assert tools[0]["name"] == "web_search"


def test_real_web_search_returns_findings_in_the_interface_shape(monkeypatch) -> None:
    with patch("anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = _claude_reply(WEB_SEARCH_JSON)
        findings = RealWebSearchAdapter().search("agent orchestration")

    assert findings == [
        {"title": "A post", "url": "https://example.com/a", "note": "relevant because X", "date": "2026-06"}
    ]


def test_real_web_search_raises_readable_error_on_malformed_json() -> None:
    with patch("anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = _claude_reply("not json at all")
        with pytest.raises(ValueError, match="invalid JSON"):
            RealWebSearchAdapter().search("x")


def test_real_web_search_raises_readable_error_when_no_text_block() -> None:
    # same failure the step-7 bug taught us: thinking/searching can eat the whole budget
    # before any text comes out. a bare StopIteration here tells you nothing
    empty = MagicMock()
    empty.content = []
    empty.stop_reason = "max_tokens"
    with patch("anthropic.Anthropic") as mock_client:
        mock_client.return_value.messages.create.return_value = empty
        with pytest.raises(ValueError, match="no text block"):
            RealWebSearchAdapter().search("x")


# ===== REAL GITHUB =====


def test_real_github_maps_api_response_to_the_interface_shape() -> None:
    with patch("app.integrations.github.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: GITHUB_API_RESPONSE)
        findings = RealGitHubAdapter().check_activity("agent orchestration")

    assert findings == [
        {
            "repo": "example-org/thing",
            "url": "https://github.com/example-org/thing",
            "note": "does a thing",
            "last_activity": "2026-07-01",  # timestamp trimmed to the date
        }
    ]


def test_real_github_survives_a_null_description() -> None:
    # description is nullable on GitHub -- a None here used to be a plausible crash
    payload = {"items": [{**GITHUB_API_RESPONSE["items"][0], "description": None}]}
    with patch("app.integrations.github.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: payload)
        findings = RealGitHubAdapter().check_activity("x")

    assert findings[0]["note"] == "No description provided."


def test_real_github_explains_a_403_as_the_rate_limit() -> None:
    with patch("app.integrations.github.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=403)
        with pytest.raises(ValueError, match="rate limit"):
            RealGitHubAdapter().check_activity("x")


# ===== MOCK ADAPTERS =====


def test_mock_adapters_return_realistic_canned_findings() -> None:
    # not empty stubs -- the demo should read as a working research agent (owner's call)
    web = MockWebSearchAdapter().search("agent orchestration")
    github = MockGitHubAdapter().check_activity("agent orchestration")

    assert len(web) >= 2
    assert len(github) >= 2
    for finding in web:
        assert set(finding) == {"title", "url", "note", "date"}
        assert finding["title"] and finding["url"] and finding["note"] and finding["date"]
    for finding in github:
        assert set(finding) == {"repo", "url", "note", "last_activity"}
        assert finding["repo"] and finding["url"] and finding["note"] and finding["last_activity"]


# ===== FACTORY =====


def test_factory_returns_mocks_in_demo_mode(monkeypatch) -> None:
    monkeypatch.setattr("app.integrations.factory.settings.mode", "demo")

    assert isinstance(get_web_search_adapter(), MockWebSearchAdapter)
    assert isinstance(get_github_adapter(), MockGitHubAdapter)


def test_factory_returns_real_adapters_in_personal_mode(monkeypatch) -> None:
    monkeypatch.setattr("app.integrations.factory.settings.mode", "personal")

    assert isinstance(get_web_search_adapter(), RealWebSearchAdapter)
    assert isinstance(get_github_adapter(), RealGitHubAdapter)


def test_demo_mode_never_touches_the_network(monkeypatch) -> None:
    # the guarantee the whole factory exists for: demo makes no HTTP call and no Claude call.
    # patches blow up if anything reaches for them
    monkeypatch.setattr("app.integrations.factory.settings.mode", "demo")

    with patch("app.integrations.github.httpx.get", side_effect=AssertionError("demo hit the network")):
        with patch("anthropic.Anthropic", side_effect=AssertionError("demo made a Claude call")):
            get_web_search_adapter().search("x")
            get_github_adapter().check_activity("x")
