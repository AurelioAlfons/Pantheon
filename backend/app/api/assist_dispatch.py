"""Turns ASSIST's decision into real task rows -- split out of tasks.py the way task_chain.py was.

ASSIST decides (mode + target + whether to pull in research); this does the spawning. Kept separate
so tasks.py's completion hooks stay readable and this logic is testable on its own.

The three shapes ASSIST's decision can take:
- single_agent -> one task to the named agent, then stop.
- full_pipeline/full_auto, no research -> one Prometheus task (gated or not by auto_continue).
- full_pipeline/full_auto, with research -> one Hermes task carrying a marker; when it finishes,
  tasks.py's Hermes-done hook spawns the Prometheus task as its child. Two hops, same machinery.
"""

from sqlalchemy.orm import Session

from app.api.task_chain import spawn_child_task
from app.models import Task

# the marker that tells the Hermes-done hook in tasks.py "this research was for a relay, keep going"
# -- a standalone Mode Three Hermes task never carries it, so it's left alone
RESEARCH_PURPOSE = "assist_prometheus_research"


def dispatch_from_decision(session: Session, assist_task: Task, decision: dict) -> Task | None:
    """spawns the next task(s) from ASSIST's decision -- returns the child spawned, or None if nothing was.

    Modes:
      single_agent  -> one task to decision['target_agent'].
      full_*        -> a Hermes research task if use_hermes_research, else a Prometheus task.
    auto_continue rides in the payload so the downstream hooks know whether to keep going without a
    check-in: True for full_auto, False for full_pipeline (which waits for /approve).
    """
    mode = decision.get("mode")
    brief = decision.get("brief", "")

    if mode == "single_agent":
        # dispatch and stop -- no downstream hooks fire for this one
        return spawn_child_task(session, assist_task, decision["target_agent"], {"request": brief})

    # full_pipeline or full_auto from here -- both head toward Prometheus, research first if asked
    auto_continue = mode == "full_auto"

    if decision.get("use_hermes_research"):
        # Hermes runs first; its completion hook in tasks.py spawns Prometheus with the findings folded in
        return spawn_child_task(
            session,
            assist_task,
            "Hermes",
            {"request": brief, "purpose": RESEARCH_PURPOSE, "auto_continue": auto_continue},
        )

    # straight to Prometheus, no research leg
    return spawn_child_task(
        session, assist_task, "Prometheus", {"request": brief, "auto_continue": auto_continue}
    )


def spawn_prometheus_from_research(session: Session, hermes_task: Task, research_result: dict) -> Task:
    """the Hermes-research bridge: folds Hermes's findings into a Prometheus brief and spawns it.

    Called by tasks.py's Hermes-done hook only when the task carried the RESEARCH_PURPOSE marker.
    Prometheus becomes Hermes's child, so the depth cap keeps counting down the same chain.
    """
    original_brief = (hermes_task.payload or {}).get("request", "")
    summary = research_result.get("summary", "")
    recommendations = research_result.get("recommendations", [])

    enriched_brief = (
        f"{original_brief}\n\n"
        f"Research findings from Hermes:\n{summary}\n\n"
        f"Recommendations:\n" + "\n".join(f"- {rec}" for rec in recommendations)
    )
    # carry auto_continue through from the Hermes task -- a full_auto request stays auto past the research leg
    auto_continue = (hermes_task.payload or {}).get("auto_continue", False)
    return spawn_child_task(
        session, hermes_task, "Prometheus", {"request": enriched_brief, "auto_continue": auto_continue}
    )
