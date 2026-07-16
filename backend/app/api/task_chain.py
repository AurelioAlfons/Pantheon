"""Where the task-chain depth cap gets enforced -- the one place a task spawns a child, reused by every future handoff."""

from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models import Task


def spawn_child_task(session: Session, parent: Task, assigned_to: str, payload: dict) -> Task:
    """creates a child task linked to parent via parent_task_id -- refuses past MAX_TASK_CHAIN_DEPTH"""
    child_depth = parent.depth + 1
    if child_depth > settings.max_task_chain_depth:
        raise ValueError(
            f"spawning '{assigned_to}' from task {parent.id} would exceed max_task_chain_depth "
            f"({settings.max_task_chain_depth})"
        )

    child = Task(
        status="pending",
        payload=payload,
        created_by=parent.assigned_to,
        assigned_to=assigned_to,
        parent_task_id=parent.id,
        project_id=parent.project_id,
        depth=child_depth,
    )
    session.add(child)
    session.commit()
    session.refresh(child)
    return child
