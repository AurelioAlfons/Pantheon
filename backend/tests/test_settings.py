"""Covers validate_startup()'s fail-fast rules for demo vs personal mode."""

from pathlib import Path

import pytest

from app.core.settings import Settings, validate_startup


def _settings_with_valid_agents_dir(tmp_path: Path, **overrides) -> Settings:
    # every case needs a real .md file somewhere -- tmp_path keeps this independent
    # of whatever's actually sitting in the real agents/ folder
    (tmp_path / "dummy.md").write_text("---\nname: Dummy\n---\n")
    return Settings(agent_config_dir=tmp_path, **overrides)


def test_demo_mode_no_credentials_passes(tmp_path: Path) -> None:
    config = _settings_with_valid_agents_dir(tmp_path, mode="demo")
    validate_startup(config)  # no news is good news here


def test_demo_mode_with_gmail_credential_raises(tmp_path: Path) -> None:
    config = _settings_with_valid_agents_dir(
        tmp_path, mode="demo", gmail_client_id="leaked-id"
    )
    with pytest.raises(RuntimeError, match="GMAIL_CLIENT_ID"):
        validate_startup(config)


def test_personal_mode_missing_credentials_raises(tmp_path: Path) -> None:
    config = _settings_with_valid_agents_dir(tmp_path, mode="personal")
    with pytest.raises(RuntimeError) as exc_info:
        validate_startup(config)
    # a boot failure should name every missing field, not just the first one it trips over
    for field in (
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN",
        "ADMIN_PASSWORD_HASH",
        "SESSION_SECRET",
    ):
        assert field in str(exc_info.value)


def test_personal_mode_with_all_credentials_passes(tmp_path: Path) -> None:
    config = _settings_with_valid_agents_dir(
        tmp_path,
        mode="personal",
        gmail_client_id="id",
        gmail_client_secret="secret",
        gmail_refresh_token="token",
        admin_password_hash="hash",
        session_secret="session-secret",
    )
    validate_startup(config)  # fully staffed, should just go


def test_missing_agent_config_dir_raises(tmp_path: Path) -> None:
    never_created = tmp_path / "does-not-exist"
    config = Settings(mode="demo", agent_config_dir=never_created)
    with pytest.raises(RuntimeError, match="agent_config_dir"):
        validate_startup(config)


def test_empty_agent_config_dir_raises(tmp_path: Path) -> None:
    # dir exists but has no .md files in it -- same failure as not existing at all
    config = Settings(mode="demo", agent_config_dir=tmp_path)
    with pytest.raises(RuntimeError, match="agent_config_dir"):
        validate_startup(config)
