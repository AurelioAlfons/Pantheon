"""SQLAlchemy engine + session factory -- one source of truth for the DB connection, same pattern as settings.py."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import settings

# one engine for the whole app -- SQLAlchemy pools connections under the hood, no need to recreate it per request
engine = create_engine(settings.database_url)

# each caller gets its own session off this factory, commits/closes are on them
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
