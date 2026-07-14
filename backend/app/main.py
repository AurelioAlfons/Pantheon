"""FastAPI entrypoint for the Pantheon backend."""

import os

from dotenv import find_dotenv, load_dotenv
from fastapi import FastAPI

# .env lives at the repo root (one level above backend/), shared by all services.
load_dotenv(find_dotenv())

app = FastAPI(title="Pantheon")


@app.get("/health")
def health() -> dict:
    """Liveness check used by the repo-skeleton test and future deploy checks."""
    return {"status": "ok", "mode": os.getenv("MODE", "demo")}
