"""The only place MODE decides anything for integrations.

CLAUDE.md's rule: MODE is resolved once, in a settings module + integration factory, never
checked inside agent or orchestrator logic. If you find yourself writing `if settings.mode`
in an agent, the answer is another factory function here instead.
"""

from app.core.settings import settings
from app.integrations.base import GitHubAdapter, WebSearchAdapter
from app.integrations.github import MockGitHubAdapter, RealGitHubAdapter
from app.integrations.web_search import MockWebSearchAdapter, RealWebSearchAdapter


def get_web_search_adapter() -> WebSearchAdapter:
    """real search in personal mode, canned findings in demo -- the caller can't tell the difference"""
    if settings.mode == "personal":
        return RealWebSearchAdapter()
    return MockWebSearchAdapter()


def get_github_adapter() -> GitHubAdapter:
    """same split -- demo never touches api.github.com, so it can't burn the rate limit"""
    if settings.mode == "personal":
        return RealGitHubAdapter()
    return MockGitHubAdapter()
