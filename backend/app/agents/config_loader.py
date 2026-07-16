"""Loads every agents/*.md file at boot -- turns the six markdown configs into a name-keyed dict of AgentConfig."""

from pathlib import Path

from app.agents.config import AgentConfig, parse_agent_config


def load_all_agent_configs(config_dir: Path) -> dict[str, AgentConfig]:
    """glob every *.md in config_dir (skips README.md), keys the result by agent name"""
    configs: dict[str, AgentConfig] = {}

    for path in sorted(Path(config_dir).glob("*.md")):
        # README.md documents the folder, it isn't an agent config
        if path.stem.lower() == "readme":
            continue
        config = parse_agent_config(path)
        configs[config.name] = config

    return configs
