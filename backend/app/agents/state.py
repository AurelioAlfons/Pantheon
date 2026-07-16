"""idle -> running -> done/failed -- the one state machine every agent runs on."""

from typing import Literal

AgentState = Literal["idle", "running", "done", "failed"]

# no failed -> idle yet -- retry lands in step 8 once the scheduler exists to drive it
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"running"},
    "running": {"done", "failed"},
    "done": set(),
    "failed": set(),
}


def transition(current: AgentState, target: AgentState) -> AgentState:
    """returns target if the hop is legal, raises ValueError on an illegal jump (e.g. done -> running)"""
    if target not in ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid transition: {current} -> {target}")
    return target
