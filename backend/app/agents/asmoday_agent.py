"""Asmoday's real handler -- takes an assigned piece of Prometheus's plan and writes the code for it."""

import anthropic

from app.agents.base_agent import BaseAgent
from app.core.settings import settings


class AsmodayAgent(BaseAgent):
    """turns an assigned task into real code, using asmoday.md's own system prompt -- plain text output, no schema"""

    def execute(self, payload: dict) -> dict:
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        response = client.messages.create(
            model=self.config.model,
            # 8192, not 4096 -- writing real code needs more room, and thinking alone can eat
            # the whole budget on a meaty task before any text comes out (see the ValueError below)
            max_tokens=8192,
            system=self.config.system_prompt,
            messages=[{"role": "user", "content": payload.get("request", "")}],
        )
        # same thinking-block-safe extraction as Prometheus -- adaptive thinking can put a
        # ThinkingBlock before the TextBlock. If thinking ate the whole max_tokens budget,
        # there's no text block at all -- raise something debuggable, not a bare StopIteration
        try:
            raw_text = next(block.text for block in response.content if block.type == "text")
        except StopIteration:
            raise ValueError(
                f"Asmoday's reply had no text block (stop_reason={response.stop_reason!r}) -- "
                "likely ran out of max_tokens while still thinking"
            ) from None
        return {"code": raw_text}
