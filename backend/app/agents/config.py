"""One place that understands agents/*.md's shape -- frontmatter fields plus the body as the system prompt."""

from dataclasses import dataclass
from pathlib import Path

import yaml

# tools is checked separately below -- [] is a valid value for it, not "empty"
REQUIRED_NON_EMPTY_FIELDS = ["name", "role", "model", "schedule"]


@dataclass
class AgentConfig:
    """one agent's config -- frontmatter fields plus the markdown body as its system prompt"""

    name: str
    role: str
    model: str
    tools: list[str]
    schedule: str
    system_prompt: str


def parse_agent_config(path: Path) -> AgentConfig:
    """splits one agents/*.md file into frontmatter + body, validates it, returns an AgentConfig"""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise ValueError(f"{path.name}: missing '---' frontmatter delimiters")

    frontmatter = yaml.safe_load(parts[1]) or {}
    body = parts[2].strip()

    for field_name in REQUIRED_NON_EMPTY_FIELDS:
        # spell out which file + field failed, a generic KeyError gives nothing to go on
        if not frontmatter.get(field_name):
            raise ValueError(f"{path.name}: missing '{field_name}' in frontmatter")

    tools = frontmatter.get("tools")
    if not isinstance(tools, list):
        raise ValueError(f"{path.name}: 'tools' must be a list (got {type(tools).__name__})")

    return AgentConfig(
        name=frontmatter["name"],
        role=frontmatter["role"],
        model=frontmatter["model"],
        tools=tools,
        schedule=frontmatter["schedule"],
        system_prompt=body,
    )
