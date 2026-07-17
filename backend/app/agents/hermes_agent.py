"""Hermes's real handler -- the first agent that needs something outside an Anthropic call.

Shape is the same as Prometheus/Asmoday, with one extra step in front: pull both adapters
from the factory, gather raw findings, then hand those to Claude to turn into actual research.
Hermes never learns whether those adapters are real or mocked -- that's the factory's problem.
"""

import json

import anthropic

from app.agents.base_agent import BaseAgent
from app.core.settings import settings
from app.integrations.factory import get_github_adapter, get_web_search_adapter

# appended to hermes.md's own system prompt so the reply is parseable JSON, not prose.
# the date/last_activity fields ride along from the adapters so Prometheus can weigh a
# finding by how fresh it is instead of treating month-old research as current
JSON_ONLY_INSTRUCTION = (
    "\n\nRespond with JSON only, matching this shape: "
    '{"summary": string, '
    '"web_findings": [{"title": string, "url": string, "note": string, "date": string}], '
    '"github_findings": [{"repo": string, "url": string, "note": string, "last_activity": string}], '
    '"recommendations": [string]}. '
    "Carry each finding's date/last_activity through from the research data unchanged -- "
    "never invent or adjust one. Drop findings that don't actually bear on the request. "
    "No prose outside the JSON object."
)


def _build_research_prompt(request: str, web_findings: list[dict], github_findings: list[dict]) -> str:
    """packs the raw adapter output into one user message -- JSON in, so nothing gets lost in prose"""
    return (
        f"Research request:\n{request}\n\n"
        f"Web search results:\n{json.dumps(web_findings, indent=2)}\n\n"
        f"GitHub results:\n{json.dumps(github_findings, indent=2)}\n\n"
        "Turn these raw results into findings that answer the request."
    )


class HermesAgent(BaseAgent):
    """gathers outside context -- adapters first, then one Claude call to make sense of it"""

    def execute(self, payload: dict) -> dict:
        request = payload.get("request", "")

        # mode resolved here and only here, by the factory -- no `if settings.mode` in this file
        web_search = get_web_search_adapter()
        github = get_github_adapter()

        # plain python calls, before any synthesis -- in personal mode search() is secretly its
        # own Claude call, which is why Hermes costs two. demo mode skips it entirely
        web_findings = web_search.search(request)
        github_findings = github.check_activity(request)

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=self.config.model,
            max_tokens=8192,
            system=self.config.system_prompt + JSON_ONLY_INSTRUCTION,
            messages=[{"role": "user", "content": _build_research_prompt(request, web_findings, github_findings)}],
        )
        # same thinking-block dance as the other agents -- content[0] isn't reliably the answer
        try:
            raw_text = next(block.text for block in response.content if block.type == "text")
        except StopIteration:
            raise ValueError(
                f"Hermes's reply had no text block (stop_reason={response.stop_reason!r}) -- "
                "likely ran out of max_tokens while still thinking"
            ) from None
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Hermes returned invalid JSON: {raw_text}") from exc
