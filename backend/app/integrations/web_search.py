"""Web search, real and mocked.

The real one is odd and worth explaining: there's no "just search" endpoint at Anthropic.
web_search is a server-side tool that runs *inside* a messages.create() call, so searching
means making a Claude call. That's why this adapter costs a Claude call of its own, on top
of Hermes's synthesis call.

HermesAgent doesn't know any of that -- it calls adapter.search(query) like it would any
other adapter. Which is the whole point of the pattern.
"""

import json

import anthropic

from app.core.settings import settings
from app.integrations.base import WebFinding

# the current tool version -- _20260209 adds dynamic filtering (Claude filters results with
# code before they hit the context window). needs Sonnet 4.6+ / Opus 4.6+; hermes.md is on
# sonnet-5, so we're fine. the older _20250305 basic variant is for models that can't do this
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search"}

MAX_SEARCHES_PER_RUN = 5  # a research task shouldn't need more, and each one costs

# raw search results give title/url/page_age and nothing else -- no "why does this matter".
# so we don't parse the result blocks directly, we ask Claude to search and hand back our
# own shape. same JSON-only trick prometheus_agent.py uses
SEARCH_SYSTEM_PROMPT = (
    "You are a research assistant. Search the web for the user's query, then report what you found.\n\n"
    "Respond with JSON only, matching this shape: "
    '{"findings": [{"title": string, "url": string, "note": string, "date": string}]}. '
    "'note' is one sentence on why the finding matters to the query. "
    "'date' is when the source is from (YYYY-MM or YYYY-MM-DD); use \"unknown\" if you cannot establish it "
    "-- never guess a date. "
    "Return at most 5 findings, most relevant first. No prose outside the JSON object."
)


class RealWebSearchAdapter:
    """searches for real -- one Claude call with the server-side web_search tool"""

    def search(self, query: str) -> list[WebFinding]:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model="claude-sonnet-5",  # this is the search-and-extract call, not Hermes's own thinking
            max_tokens=8192,  # same reason as the agents: thinking can eat a small budget whole
            system=SEARCH_SYSTEM_PROMPT,
            tools=[{**WEB_SEARCH_TOOL, "max_uses": MAX_SEARCHES_PER_RUN}],
            messages=[{"role": "user", "content": query}],
        )
        # search runs server-side, so the reply has tool blocks in it -- the JSON we want is
        # in the last text block, after Claude's done searching
        text_blocks = [block.text for block in response.content if block.type == "text"]
        if not text_blocks:
            raise ValueError(
                f"web search reply had no text block (stop_reason={response.stop_reason!r}) -- "
                "likely ran out of max_tokens while still searching or thinking"
            )
        raw_text = text_blocks[-1]
        try:
            return json.loads(raw_text).get("findings", [])
        except json.JSONDecodeError as exc:
            raise ValueError(f"web search returned invalid JSON: {raw_text}") from exc


class MockWebSearchAdapter:
    """canned findings for MODE=demo -- no network, no Claude call, no cost.

    Deliberately realistic rather than empty stubs: the public demo should read like a working
    research agent, not a stubbed-out one. Content is generic on purpose so it doesn't go stale.
    """

    def search(self, query: str) -> list[WebFinding]:
        return [
            {
                "title": "Multi-agent orchestration is moving from frameworks to custom pipelines",
                "url": "https://example.com/multi-agent-orchestration-trends",
                "note": f"Teams building '{query}'-style systems increasingly hand-roll orchestration "
                "rather than adopt a framework, citing debuggability.",
                "date": "2026-05",
            },
            {
                "title": "A survey of agent task-queue patterns",
                "url": "https://example.com/agent-task-queue-patterns",
                "note": "Compares message-bus designs against database-backed task queues; "
                "relevant to how agents hand work to each other.",
                "date": "2026-03",
            },
        ]
