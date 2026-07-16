"""Proves BaseAgent's state machine actually works -- echoes payload back, or fails on command."""

from app.agents.base_agent import BaseAgent
from app.agents.config import AgentConfig


class DummyAgent(BaseAgent):
    """testing/proof-of-mechanism only -- fail=True forces the failure path without mocking anything"""

    def __init__(self, config: AgentConfig, fail: bool = False):
        super().__init__(config)
        self.fail = fail

    def execute(self, payload: dict) -> dict:
        if self.fail:
            raise RuntimeError("dummy failure for testing")
        return {"echo": payload}
