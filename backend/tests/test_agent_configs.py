"""Validates every agents/*.md file has the frontmatter step 4's config loader will need."""

from pathlib import Path

import pytest
import yaml

# agents/ lives at repo root, two levels up from backend/tests/
AGENTS_DIR = Path(__file__).resolve().parent.parent.parent / "agents"
# tools is checked separately below -- [] is a valid value for it, not "empty"
NON_EMPTY_FIELDS = ["name", "role", "model", "schedule"]


def _agent_files() -> list[Path]:
    # sorted so pytest -v output order is stable across machines
    # README.md documents the folder, it isn't an agent config -- skip it
    return sorted(p for p in AGENTS_DIR.glob("*.md") if p.stem.lower() != "readme")


def _parse_frontmatter(path: Path) -> dict:
    # frontmatter sits between the first two "---" lines, body is everything after
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    assert len(parts) >= 3, f"{path.name}: missing '---' frontmatter delimiters"
    return yaml.safe_load(parts[1])


@pytest.mark.parametrize("path", _agent_files(), ids=lambda p: p.name)
def test_frontmatter_has_required_fields(path: Path) -> None:
    frontmatter = _parse_frontmatter(path)

    for field in NON_EMPTY_FIELDS:
        # spell out which file + field failed, generic assert gives nothing to go on
        assert field in frontmatter, f"{path.name}: missing '{field}' in frontmatter"
        assert frontmatter[field] not in (None, ""), f"{path.name}: '{field}' is empty"

    # tools must be present and a list, but [] (no tools) is a valid value for it
    assert "tools" in frontmatter, f"{path.name}: missing 'tools' in frontmatter"
    assert isinstance(frontmatter["tools"], list), (
        f"{path.name}: 'tools' must be a list (got {type(frontmatter['tools']).__name__})"
    )


def test_all_six_agents_present() -> None:
    # catches a silently-missing file that the parametrize glob would just skip over
    found = {p.stem for p in _agent_files()}
    expected = {"assist", "prometheus", "asmoday", "hermes", "aizen", "khepri"}
    assert found == expected, f"expected {expected}, found {found}"
