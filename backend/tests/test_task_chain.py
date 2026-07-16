"""spawn_child_task -- the one place the task-chain depth cap gets enforced."""

import uuid

import pytest

from app.api.task_chain import spawn_child_task
from app.core.database import SessionLocal
from app.core.settings import settings
from app.models import Task


@pytest.fixture
def db_session():
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def cleanup_task_ids():
    # spawn_child_task commits for real, so real cleanup after -- no rollback fixture here
    ids: list[uuid.UUID] = []
    yield ids
    with SessionLocal() as session:
        # two passes, children then parents -- a single flush batches same-table deletes
        # together and doesn't respect self-referential FK order on its own
        tasks = [t for t in (session.get(Task, task_id) for task_id in ids) if t is not None]
        for t in [t for t in tasks if t.parent_task_id is not None]:
            session.delete(t)
        session.commit()
        for t in [t for t in tasks if t.parent_task_id is None]:
            session.delete(t)
        session.commit()


def test_spawn_child_task_creates_linked_child(db_session, cleanup_task_ids: list[uuid.UUID]) -> None:
    parent = Task(status="done", created_by="owner", assigned_to="Prometheus")
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)
    cleanup_task_ids.append(parent.id)

    child = spawn_child_task(db_session, parent, "Asmoday", {"request": "build X"})
    cleanup_task_ids.append(child.id)

    assert child.parent_task_id == parent.id
    assert child.depth == parent.depth + 1
    assert child.assigned_to == "Asmoday"
    assert child.created_by == "Prometheus"
    assert child.status == "pending"


def test_spawn_child_task_raises_past_depth_cap(db_session, cleanup_task_ids: list[uuid.UUID]) -> None:
    # constructed directly -- a real Prometheus -> Asmoday hop only ever reaches depth 1
    # against a default cap of 10, this path can't be reached through the real API yet
    parent = Task(status="done", created_by="owner", assigned_to="Prometheus", depth=settings.max_task_chain_depth)
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)
    cleanup_task_ids.append(parent.id)

    with pytest.raises(ValueError, match="max_task_chain_depth"):
        spawn_child_task(db_session, parent, "Asmoday", {"request": "build X"})
