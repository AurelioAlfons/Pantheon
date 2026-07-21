"""ASSIST's real handler -- the overseer. Resolves which mode a request implies and where it goes.

Different shape of decision from the other agents, but the same mechanics: one Claude call,
structured JSON out, no DB access of its own. It decides; assist_dispatch.py turns that decision
into real task rows. ASSIST never spawns anything itself -- same "execute() is pure" rule as everyone.
"""

import json

import anthropic

from app.agents.base_agent import BaseAgent
from app.core.settings import settings

# ASSIST can cold-dispatch a single request to these three only. Aizen and Khepri are deliberately
# excluded: both need relay-internal context (a task_type/content_type discriminator plus existing
# content to act on) that a fresh owner request can't supply. enforced here, not just prompted --
# a prompt gets followed most of the time, not all of the time
SINGLE_AGENT_TARGETS = {"Prometheus", "Hermes", "Asmoday"}

# appended to ASSIST.md's system prompt so the reply is parseable JSON. spells out the schema and
# the mode rules -- ASSIST.md already describes the three modes in prose, this pins the output shape
JSON_ONLY_INSTRUCTION = (
    "\n\nRespond with JSON only, matching this shape: "
    '{"mode": "full_pipeline"|"full_auto"|"single_agent", '
    '"target_agent": "Prometheus"|"Hermes"|"Asmoday"|null, '
    '"use_hermes_research": true|false, '
    '"brief": string, '
    '"reasoning": string}. '
    "mode is read from how the request is phrased: full_auto only when the owner says to run it "
    "end-to-end without check-ins; single_agent only when they ask for one agent's output with "
    "nothing downstream; full_pipeline otherwise (the default). "
    "target_agent is required for single_agent (one of Prometheus, Hermes, Asmoday -- never Aizen "
    "or Khepri, which only act inside a relay) and null for the other two modes. "
    "use_hermes_research is true only when outside research would materially improve the brief. "
    "brief is the owner's request bundled for the next agent. No prose outside the JSON object."
)


class AssistAgent(BaseAgent):
    """resolves a request into a dispatch decision -- a bad target from the LLM fails loud, no silent fix"""

    def execute(self, payload: dict) -> dict:
        request = payload.get("request", "")
        # agent_status is assembled by tasks.py from the live agents table and handed in -- ASSIST
        # reasons over it (who's busy) but never reads the DB itself
        agent_status = payload.get("agent_status", {})

        user_content = (
            f"Owner request:\n{request}\n\n"
            f"Current agent availability:\n{json.dumps(agent_status, indent=2)}\n\n"
            "Resolve the mode and where this should go."
        )

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=self.config.model,
            max_tokens=8192,  # thinking can eat a small budget whole before any text -- same as the others
            system=self.config.system_prompt + JSON_ONLY_INSTRUCTION,
            messages=[{"role": "user", "content": user_content}],
        )
        # thinking block can precede the text block; no text block at all means thinking ate the budget
        try:
            raw_text = next(block.text for block in response.content if block.type == "text")
        except StopIteration:
            raise ValueError(
                f"ASSIST's reply had no text block (stop_reason={response.stop_reason!r}) -- "
                "likely ran out of max_tokens while still thinking"
            ) from None
        try:
            decision = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"ASSIST returned invalid JSON: {raw_text}") from exc

        self._guard_single_agent_target(decision)
        return decision

    def _guard_single_agent_target(self, decision: dict) -> None:
        """rejects a single_agent decision aimed at an agent ASSIST can't cold-dispatch to"""
        if decision.get("mode") != "single_agent":
            return
        target = decision.get("target_agent")
        if target not in SINGLE_AGENT_TARGETS:
            raise ValueError(
                f"ASSIST picked an invalid single_agent target: {target!r} -- "
                f"expected one of {sorted(SINGLE_AGENT_TARGETS)}"
            )
