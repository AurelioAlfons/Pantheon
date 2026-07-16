"""BaseAgent -- generic state machine every agent runs on. Subclasses override execute() for real work."""

from app.agents.config import AgentConfig
from app.agents.state import AgentState, transition


class BaseAgent:
    """drives idle -> running -> done/failed around a subclass's execute() -- a blown-up agent must not crash whatever's driving it"""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.state: AgentState = "idle"
        self.result: dict | None = None
        self.error: str | None = None

    def run(self, payload: dict | None = None) -> dict | None:
        """runs execute(), always lands in done or failed -- exceptions get caught, never escape this call"""
        payload = payload or {}
        self.state = transition(self.state, "running")

        try:
            self.result = self.execute(payload)
        except Exception as exc:
            self.error = str(exc)
            self.state = transition(self.state, "failed")
            return None

        self.state = transition(self.state, "done")
        return self.result

    def execute(self, payload: dict) -> dict:
        """no generic behavior here -- only DummyAgent (this step) has anything real to do"""
        raise NotImplementedError(f"{self.config.name} has no execute() implementation yet")
