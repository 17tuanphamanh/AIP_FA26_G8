"""Tests for the config layer — no real API calls."""

import pytest

from agent.config import DEFAULT_MODEL, Config, read_prompt


def test_missing_api_key_raises_a_clear_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        Config.from_env()


def test_config_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-gia-lap")
    monkeypatch.delenv("MODEL", raising=False)
    config = Config.from_env()
    assert config.api_key == "sk-ant-gia-lap"
    assert config.model == DEFAULT_MODEL


def test_max_steps_is_read_from_environment(monkeypatch):
    """MAX_STEPS was renamed from SO_BUOC_TOI_DA — pin the new name down."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-gia-lap")
    monkeypatch.setenv("MAX_STEPS", "7")
    assert Config.from_env().max_steps == 7


def test_system_prompt_file_exists():
    assert "AIP_FA26_G8" in read_prompt("system.md")
