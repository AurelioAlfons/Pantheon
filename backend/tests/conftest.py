"""Shared test fixtures.

The agents table is real, shared, and permanent -- boot re-seeds it, and the dashboard reads it.
Any test that runs a task writes a status to it, so without cleanup pytest leaves fake done/failed
statuses on real agents forever (boot only re-seeds role/model, never status, on purpose).

Same lesson as the step 7 orphaned-rows incident: tests must not leave real state behind.
"""

import pytest

from app.core.database import SessionLocal
from app.models import Agent


@pytest.fixture(scope="session", autouse=True)
def restore_agent_statuses():
    """snapshots every agent's status before the suite and puts it back after -- pytest must not dirty real supabase.

    Session-scoped on purpose: three test files write agent statuses, and a per-test fixture would
    fight the ones that deliberately check status across a poll tick.
    """
    with SessionLocal() as session:
        before = {agent.name: agent.status for agent in session.query(Agent).all()}

    yield

    with SessionLocal() as session:
        for agent in session.query(Agent).all():
            # rows the suite created itself (a fresh DB) weren't in the snapshot -- idle is their honest state
            agent.status = before.get(agent.name, "idle")
        session.commit()
