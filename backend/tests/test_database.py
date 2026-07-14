"""Insert/read against the real Supabase db, wrapped in a transaction that always gets rolled back."""

import pytest
from sqlalchemy.orm import Session

from app.core.database import engine
from app.models import Agent, Event, Task


@pytest.fixture
def db_session():
    # one connection, one transaction, for the whole test -- every insert below is a real
    # round trip to supabase, but nothing survives past the rollback, so no test db needed
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


def test_insert_and_read_agent(db_session: Session) -> None:
    agent = Agent(name="TestAgent", role="tester", model="claude-sonnet-5")
    db_session.add(agent)
    db_session.flush()  # pushes the insert without committing, so we can read it straight back

    fetched = db_session.get(Agent, agent.id)
    assert fetched.name == "TestAgent"
    assert fetched.role == "tester"
    assert fetched.model == "claude-sonnet-5"
    assert fetched.status == "idle"  # column default, never set it explicitly above


def test_insert_and_read_task(db_session: Session) -> None:
    task = Task(created_by="owner", assigned_to="Prometheus", payload={"brief": "build X"})
    db_session.add(task)
    db_session.flush()

    fetched = db_session.get(Task, task.id)
    assert fetched.created_by == "owner"
    assert fetched.assigned_to == "Prometheus"
    assert fetched.payload == {"brief": "build X"}
    assert fetched.parent_task_id is None
    assert fetched.depth == 0


def test_child_task_resolves_parent_fk(db_session: Session) -> None:
    parent = Task(created_by="owner", assigned_to="Prometheus")
    db_session.add(parent)
    db_session.flush()

    child = Task(created_by="Prometheus", assigned_to="Asmoday", parent_task_id=parent.id, depth=1)
    db_session.add(child)
    db_session.flush()

    fetched = db_session.get(Task, child.id)
    assert fetched.parent_task_id == parent.id
    assert fetched.depth == 1
    # walk the fk back up for real, not just compare the raw id -- proves the relationship holds
    resolved_parent = db_session.get(Task, fetched.parent_task_id)
    assert resolved_parent is not None
    assert resolved_parent.id == parent.id


def test_insert_and_read_event(db_session: Session) -> None:
    task = Task(created_by="owner", assigned_to="Hermes")
    db_session.add(task)
    db_session.flush()

    event = Event(task_id=task.id, agent_name="Hermes", event_type="started", message="kicking off research")
    db_session.add(event)
    db_session.flush()

    fetched = db_session.get(Event, event.id)
    assert fetched.task_id == task.id
    assert fetched.agent_name == "Hermes"
    assert fetched.event_type == "started"
    assert fetched.message == "kicking off research"
