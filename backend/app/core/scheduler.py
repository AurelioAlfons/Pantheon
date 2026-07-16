"""The poller -- watches the tasks table for pending rows and runs them, no request needed.

Replaces the FastAPI BackgroundTasks workaround from step 6/7. A task now runs because a
poll tick found it pending, whether it got there from POST /tasks, from an agent spawning a
child, or from a row someone dropped straight into Supabase by hand.
"""

from apscheduler.schedulers.background import BackgroundScheduler

from app.agents.config import AgentConfig
from app.api.tasks import _run_agent_task
from app.core.database import SessionLocal
from app.core.settings import settings
from app.models import Task


def poll_pending_tasks(agent_configs: dict[str, AgentConfig]) -> None:
    """one tick -- runs every pending row found at the start of the tick, oldest first"""
    # snapshot the pending rows up front. children spawned mid-tick (a Prometheus task
    # spawning Asmoday children) are NOT in this list, so they wait for the next tick --
    # that's the intended two-ticks-per-chain behavior, not a miss
    with SessionLocal() as session:
        pending = session.query(Task).filter(Task.status == "pending").order_by(Task.created_at).all()
        to_run = [(t.id, t.assigned_to, t.payload) for t in pending]

    for task_id, assigned_to, payload in to_run:
        config = agent_configs.get(assigned_to)
        if config is None:
            # a hand-inserted row with an unknown agent name -- skip it, don't crash the whole tick
            continue
        _run_agent_task(task_id, assigned_to, config, payload, agent_configs)


def start_scheduler(agent_configs: dict[str, AgentConfig]) -> BackgroundScheduler:
    """boots the poller on its interval -- returns the handle so main.py can shut it down on exit"""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        poll_pending_tasks,
        "interval",
        seconds=settings.scheduler_poll_interval_seconds,
        args=[agent_configs],
        max_instances=1,  # a slow tick can't overlap the next one and double-process a row
    )
    scheduler.start()
    return scheduler
