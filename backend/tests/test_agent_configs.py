"""Validates every agents/*.md file parses cleanly through the real config parser step 5 built."""

from pathlib import Path

import pytest

from app.agents.config import parse_agent_config

# agents/ lives at repo root, two levels up from backend/tests/
AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"


def _agent_files() -> list[Path]:
    # sorted so pytest -v output order is stable across machines
    # README.md documents the folder, it isn't an agent config -- skip it
    return sorted(p for p in AGENTS_DIR.glob("*.md") if p.stem.lower() != "readme")


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_frontmatter_has_required_fields(path: Path) -> None:
    # parse_agent_config already raises ValueError naming the file + field on anything missing/malformed
    config = parse_agent_config(path)

    assert config.name
    assert config.role
    assert config.model
    assert config.schedule
    assert isinstance(config.tools, list)


def test_all_six_agents_present() -> None:
    # catches a silently-missing file that the parametrize glob would just skip over
    found = {p.stem for p in _agent_files()}
    expected = {"assist", "prometheus", "asmoday", "hermes", "aizen", "khepri"}
    assert found == expected, f"expected {expected}, found {found}"
