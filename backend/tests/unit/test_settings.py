"""Settings: mặc định an toàn, biến LLM để trống hợp lệ (mốc G), bí mật không lộ qua repr."""

import pytest
from app.settings import Settings, env_file_from_env
from pydantic import ValidationError


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg, arg-type]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("LLM_API_KEY", "LOCK_POOL_SIZE", "GRAPH_CONCURRENCY", "EVAL_MODE", "STRATEGY"):
        monkeypatch.delenv(name, raising=False)


def test_safe_defaults() -> None:
    s = _settings()
    assert s.eval_mode is False
    assert s.rediagnose_on_new_slot is False  # D-20 tắt mặc định
    assert s.enable_proactive_diagnosis is True  # B06 mục 7
    assert s.llm_cache_mode == "default"
    assert s.strategy == "hybrid"
    assert s.llm_api_key is None


def test_empty_llm_key_means_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "")
    assert _settings().llm_api_key is None


def test_secret_not_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-bi-mat-khong-duoc-in")
    s = _settings()
    assert "sk-bi-mat-khong-duoc-in" not in repr(s)
    assert s.llm_api_key is not None
    assert s.llm_api_key.get_secret_value() == "sk-bi-mat-khong-duoc-in"


def test_lock_pool_defaults_to_two_times_graph_concurrency_plus_two() -> None:
    assert _settings(graph_concurrency=8).effective_lock_pool_size == 18  # G2 (trước: + 2 → 10); chi tiết test_lock_pool_g2.py
    assert _settings(graph_concurrency=8, lock_pool_size=4).effective_lock_pool_size == 4


def test_flags_read_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EVAL_MODE", "true")
    monkeypatch.setenv("STRATEGY", "rule_only")
    s = _settings()
    assert s.eval_mode is True and s.strategy == "rule_only"


def test_unknown_strategy_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(strategy="yolo")


def test_env_file_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APP_ENV_FILE", raising=False)
    assert env_file_from_env() == ".env"
    monkeypatch.setenv("APP_ENV_FILE", "/srv/khac.env")
    assert env_file_from_env() == "/srv/khac.env"
    monkeypatch.setenv("APP_ENV_FILE", "")
    assert env_file_from_env() is None


def test_env_file_disabled_under_pytest() -> None:
    """conftest.py gốc tắt file env trước khi import app — test không bao giờ đọc .env thật."""
    assert Settings.model_config.get("env_file") is None
