"""Prometheus's real handler -- the first agent that actually calls Claude instead of just moving through states."""

import json

import anthropic

from app.agents.base_agent import BaseAgent
from app.core.settings import settings

# appended to prometheus.md's own system prompt so the reply is parseable JSON, not prose
JSON_ONLY_INSTRUCTION = (
    "\n\nRespond with JSON only, matching this shape: "
    '{"scope": string, "requirements": [string], "constraints": [string], '
    '"task_breakdown": [{"title": string, "description": string}], "open_questions": [string]}. '
    "No prose outside the JSON object."
)


class PrometheusAgent(BaseAgent):
    """turns a brief into a real structured PRD -- a malformed reply raises, run() catches it and lands the task failed"""

    def execute(self, payload: dict) -> dict:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=self.config.model,
            max_tokens=4096,  # hardcoded for now, revisit if a real per-agent tuning need shows up
            system=self.config.system_prompt + JSON_ONLY_INSTRUCTION,
            messages=[{"role": "user", "content": payload.get("request", "")}],
        )
        # thinking is on by default for this model, so a ThinkingBlock can precede the
        # TextBlock -- content[0] isn't reliably the answer, find the text block itself
        raw_text = next(block.text for block in response.content if block.type == "text")
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Prometheus returned invalid JSON: {raw_text}") from exc
