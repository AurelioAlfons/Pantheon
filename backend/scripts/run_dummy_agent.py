"""Runnable demo half of DummyAgent -- not wired into the API/queue yet, that's step 6.

Usage:
    python scripts/run_dummy_agent.py          -- happy path, prints done + the echoed payload
    python scripts/run_dummy_agent.py --fail   -- forces the failure path, prints failed + the error
"""

import sys
from pathlib import Path

# lets this run from any cwd -- puts backend/ on the path so "import app...." resolves
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.config import AgentConfig
from app.agents.dummy_agent import DummyAgent


def main() -> None:
    fail = "--fail" in sys.argv
    config = AgentConfig(
        name="Dummy",
        role="proof of mechanism",
        model="claude-sonnet-5",
        tools=[],
        schedule="on-demand",
        system_prompt="",
    )
    agent = DummyAgent(config, fail=fail)
    result = agent.run({"hello": "world"})

    print(f"state: {agent.state}")
    if agent.state == "failed":
        print(f"error: {agent.error}")
    else:
        print(f"result: {result}")


if __name__ == "__main__":
    main()
