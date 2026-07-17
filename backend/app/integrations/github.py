"""GitHub repo activity, real and mocked.

Real one is a plain unauthenticated REST call -- no token, no new setting, no new dependency
(httpx was already here for the test client). The trade is rate limits: GitHub's search API
allows 10 requests/minute unauthenticated, which is fine for occasional research and would
fall over under any real volume. If Hermes ever runs on a schedule, this needs a token.
"""

import httpx

from app.integrations.base import GitHubFinding

GITHUB_SEARCH_URL = "https://api.github.com/search/repositories"
MAX_RESULTS = 5
REQUEST_TIMEOUT_SECONDS = 10  # a hung GitHub call shouldn't wedge the whole poll tick


class RealGitHubAdapter:
    """searches public repos, sorted by most recently pushed -- activity is what Hermes cares about"""

    def check_activity(self, query: str) -> list[GitHubFinding]:
        response = httpx.get(
            GITHUB_SEARCH_URL,
            params={"q": query, "sort": "updated", "order": "desc", "per_page": MAX_RESULTS},
            headers={"Accept": "application/vnd.github+json"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        # 403 here is usually the rate limit, not auth -- say so, a bare "403" sends you
        # hunting for a token that was never supposed to exist
        if response.status_code == 403:
            raise ValueError(
                "GitHub refused the search (403) -- almost certainly the unauthenticated "
                "rate limit (10 searches/min), not a credential problem"
            )
        response.raise_for_status()

        return [
            {
                "repo": item["full_name"],
                "url": item["html_url"],
                # description is nullable on GitHub, so don't assume a string comes back
                "note": item.get("description") or "No description provided.",
                "last_activity": (item.get("pushed_at") or "unknown")[:10],  # ISO timestamp -> just the date
            }
            for item in response.json().get("items", [])
        ]


class MockGitHubAdapter:
    """canned repo hits for MODE=demo -- no network call, so the demo can't burn the rate limit"""

    def check_activity(self, query: str) -> list[GitHubFinding]:
        return [
            {
                "repo": "example-org/agent-orchestrator",
                "url": "https://github.com/example-org/agent-orchestrator",
                "note": f"A custom orchestration layer for LLM agents -- close to '{query}' in shape, "
                "worth reading before building.",
                "last_activity": "2026-06-28",
            },
            {
                "repo": "example-org/task-queue-postgres",
                "url": "https://github.com/example-org/task-queue-postgres",
                "note": "Postgres-backed task queue with no broker; same architecture bet this project makes.",
                "last_activity": "2026-04-11",
            },
        ]
