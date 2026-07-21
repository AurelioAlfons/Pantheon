"""Khepri's real handler -- the reviewer. Takes another agent's output, returns a structured verdict.

Simplest of the agents so far: no adapters (unlike Hermes), no multi-job branching into different
output shapes (unlike Aizen). One job, one Claude call, one verdict shape -- always. content_type
only reframes the prompt, it never changes what comes back.
"""

import json

import anthropic

from app.agents.base_agent import BaseAgent
from app.core.settings import settings

# content_type just swaps the framing sentence so Khepri knows what it's looking at -- the
# review criteria and the output shape are the same either way, so this is a lookup, not a branch
CONTENT_TYPE_FRAMING = {
    "code": "You are reviewing code written by Asmoday.",
    "prd": "You are reviewing a PRD written by Prometheus.",
    "draft": "You are reviewing a draft written by Aizen.",
}

# appended to khepri.md's system prompt so the reply is parseable JSON, not prose -- same trick
# every agent uses. recommendation is the one field not in khepri.md's literal wording: it's here
# so ASSIST (later) can branch on the verdict without re-reading the whole issues list
JSON_ONLY_INSTRUCTION = (
    "\n\nRespond with JSON only, matching this shape: "
    '{"summary": string, '
    '"issues": [{"severity": "critical"|"major"|"minor", "description": string}], '
    '"open_questions": [string], '
    '"recommendation": "proceed"|"revise"}. '
    "No prose outside the JSON object."
)


class KhepriAgent(BaseAgent):
    """reviews an agent's output and hands back a verdict -- an unknown content_type fails loudly, no Claude call"""

    def execute(self, payload: dict) -> dict:
        content_type = payload.get("content_type")
        content = payload.get("content", "")

        framing = CONTENT_TYPE_FRAMING.get(content_type)
        if framing is None:
            # bad discriminator is a caller bug, same as Aizen's unknown task_type -- catch it
            # before the API call so it costs zero tokens. BaseAgent.run() lands the task failed
            raise ValueError(
                f"Khepri got an unknown content_type: {content_type!r} -- expected 'code', 'prd', or 'draft'"
            )

        user_content = f"{framing}\n\n{content}"

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=self.config.model,
            max_tokens=8192,  # thinking can eat a small budget whole before any text -- same reason as the others
            system=self.config.system_prompt + JSON_ONLY_INSTRUCTION,
            messages=[{"role": "user", "content": user_content}],
        )
        # thinking block can precede the text block, so content[0] isn't reliably the answer.
        # no text block at all means thinking ate the whole budget -- raise something debuggable
        try:
            raw_text = next(block.text for block in response.content if block.type == "text")
        except StopIteration:
            raise ValueError(
                f"Khepri's reply had no text block (stop_reason={response.stop_reason!r}) -- "
                "likely ran out of max_tokens while still thinking"
            ) from None
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Khepri returned invalid JSON: {raw_text}") from exc
