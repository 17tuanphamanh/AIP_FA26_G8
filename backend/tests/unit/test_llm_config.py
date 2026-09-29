"""LLM gateway — cấu hình và kiểm lúc khởi động (PLAN-3d S1: d2, d3, d15, Q-3d-3, Q-3d-7, Q-3d-13).

Không test nào gọi LLM thật hay đọc `.env`: Settings dựng với `_env_file=None`, conftest gốc đặt `LLM_BACKEND=scripted`.
"""

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.db.session import create_engines
from app.graph.wiring import open_runtime
from app.guard.privacy import NotRedactingGuard
from app.llm.config import (
    SCRIPTED_MODEL,
    LlmConfig,
    check_timing,
    load_llm_config,
    resolve,
    worst_case_s,
)
from app.llm.wiring import check_llm
from app.main import create_app
from app.settings import Settings
from pydantic import SecretStr, ValidationError

REPO = Path(__file__).resolve().parents[3]
LLM_YAML = REPO / "config" / "llm.yaml"
STALE = Settings(_env_file=None).worker_stale_turn_seconds  # type: ignore[call-arg]


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


def _raw() -> dict[str, Any]:
    data = yaml.safe_load(LLM_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _cfg(mutate: Any = None) -> LlmConfig:
    data = copy.deepcopy(_raw())
    if mutate is not None:
        mutate(data)
    return LlmConfig.model_validate(data)


def _priced(data: dict[str, Any], *models: str) -> None:
    for m in models:
        data["pricing"][m] = {"in": 0.25, "out": 1.0}


REAL = {"fast_model": "m-fast", "strong_model": "m-strong", "llm_base_url": "http://llm.test/v1",
        "llm_api_key": SecretStr("k-khong-that")}  # fmt: skip


# ---- d2, d3: LLM_BACKEND bắt buộc; scripted chỉ dev/test — create_app và open_runtime ------------------


@pytest.mark.parametrize("env", [None, "staging", "prod"])
def test_d2_scripted_outside_dev_test_refuses_create_app(env: str | None) -> None:
    settings = _settings(app_env=env, llm_backend="scripted")
    with pytest.raises(RuntimeError, match=r"LLM_BACKEND=scripted.*APP_ENV"):
        create_app(settings, health_checks={}, guard=NotRedactingGuard())  # runtime thật (mặc định)


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [None, "staging", "prod"])
async def test_d2_scripted_outside_dev_test_refuses_worker_before_db(env: str | None) -> None:
    settings = _settings(app_env=env, llm_backend="scripted")
    engines = create_engines(settings)  # URL mặc định không có Postgres: chạm DB là lỗi kết nối, không RuntimeError
    with pytest.raises(RuntimeError, match=r"LLM_BACKEND=scripted"):
        async with open_runtime(settings, engines, clock=None, can_execute=False):  # type: ignore[arg-type]
            pass
    await engines.dispose()


@pytest.mark.parametrize("env", ["dev", "test", "prod"])
def test_d3_missing_backend_refuses_create_app(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BACKEND")
    settings = _settings(app_env=env)
    assert settings.llm_backend is None
    with pytest.raises(RuntimeError, match=r"LLM_BACKEND chưa cấu hình — giá trị hợp lệ: scripted \| real"):
        create_app(settings, health_checks={}, guard=NotRedactingGuard())


@pytest.mark.asyncio
async def test_d3_missing_backend_refuses_worker_before_db(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_BACKEND")
    settings = _settings(app_env="dev")
    engines = create_engines(settings)
    with pytest.raises(RuntimeError, match="LLM_BACKEND chưa cấu hình"):
        async with open_runtime(settings, engines, clock=None, can_execute=False):  # type: ignore[arg-type]
            pass
    await engines.dispose()


def test_invalid_backend_value_names_variable_and_valid_values() -> None:
    with pytest.raises(ValidationError, match=r"LLM_BACKEND='fake' không hợp lệ — giá trị hợp lệ: scripted \| real"):
        _settings(llm_backend="fake")


@pytest.mark.parametrize("env", ["dev", "test"])
def test_scripted_in_dev_test_starts(env: str) -> None:
    setup = check_llm(_settings(app_env=env, llm_backend="scripted"))
    assert setup.runtime.backend == "scripted"
    for role in ("fast", "strong"):
        (only,) = setup.runtime.chains[role]  # scripted: một đích, không fallback (Q-3d-4)
        assert (only.provider, only.model) == ("scripted", SCRIPTED_MODEL)
        assert only.price is not None and not only.price.paid


# ---- d15: config/llm.yaml của repo; real bị từ chối tới mốc G; thông báo nêu tên model ------------------


def test_d15_repo_config_loads_and_has_no_interpolation() -> None:
    cfg = load_llm_config(LLM_YAML)
    assert set(cfg.roles) == {"fast", "strong"}
    assert cfg.fallback["strong"] == ()
    def strings(node: Any) -> list[str]:
        if isinstance(node, dict):
            return [s for k, v in node.items() for s in (str(k), *strings(v))]
        if isinstance(node, list):
            return [s for v in node for s in strings(v)]
        return [str(node)]

    found = strings(_raw())
    assert len(found) > 20 and not [s for s in found if "${" in s]  # Q-3d-3: không nội suy ở khoá/giá trị nào
    assert set(cfg.pricing) == {SCRIPTED_MODEL}  # 3d: chưa có giá model thật → real từ chối khởi động


def test_d15_real_with_repo_config_refuses_missing_model_env() -> None:
    with pytest.raises(RuntimeError, match=r"FAST_MODEL chưa cấu hình"):
        check_llm(_settings(app_env="prod", llm_backend="real"))


def test_d15_real_model_not_in_pricing_names_the_model() -> None:
    settings = _settings(app_env="prod", llm_backend="real", **REAL)
    with pytest.raises(RuntimeError) as e:
        check_llm(settings)
    msg = str(e.value)
    assert "FAST_MODEL='m-fast'" in msg and "STRONG_MODEL='m-strong'" in msg and "pricing" in msg


def test_d15_real_one_model_priced_names_only_the_missing_one() -> None:
    cfg = _cfg(lambda d: _priced(d, "m-fast"))
    with pytest.raises(RuntimeError) as e:
        resolve(cfg, _settings(**REAL), "real")
    assert "STRONG_MODEL='m-strong'" in str(e.value) and "m-fast" not in str(e.value)


def test_d15_fallback_model_without_price_is_refused_at_startup() -> None:
    def mutate(d: dict[str, Any]) -> None:
        _priced(d, "m-fast", "m-strong")
        d["fallback"]["fast"] = [{"provider": "cloud_a", "model": "m-local"}]

    with pytest.raises(RuntimeError, match=r"fallback\.fast='m-local'"):
        resolve(_cfg(mutate), _settings(**REAL), "real")


@pytest.mark.parametrize(("drop", "name"), [("llm_api_key", "LLM_API_KEY"), ("llm_base_url", "LLM_BASE_URL")])
def test_d15_real_needs_key_and_url(drop: str, name: str) -> None:
    cfg = _cfg(lambda d: _priced(d, "m-fast", "m-strong"))
    over = {k: v for k, v in REAL.items() if k != drop}
    with pytest.raises(RuntimeError, match=name):
        resolve(cfg, _settings(**over), "real")


def test_d15_real_fully_configured_resolves_without_leaking_key() -> None:
    cfg = _cfg(lambda d: _priced(d, "m-fast", "m-strong"))
    runtime = resolve(cfg, _settings(**REAL), "real")
    assert [t.model for t in runtime.chains["fast"]] == ["m-fast"]
    assert [t.model for t in runtime.chains["strong"]] == ["m-strong"]
    assert all(t.price is not None and t.price.paid for c in runtime.chains.values() for t in c)
    settings = _settings(**REAL)
    for text in (repr(runtime), repr(settings), str(settings), repr(cfg)):
        assert "k-khong-that" not in text


def test_d15_strong_fallback_rejected() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["fallback"]["strong"] = [{"provider": "cloud_a", "model": "x"}]

    with pytest.raises(ValidationError, match=r"fallback\.strong phải rỗng"):
        _cfg(mutate)


def test_d15_pricing_key_must_be_literal() -> None:
    with pytest.raises(ValidationError, match="tên model cố định"):
        _cfg(lambda d: d["pricing"].update({"${FAST_MODEL}": {"in": 0.25, "out": 1}}))


def test_d15_setting_names_must_exist_and_key_must_be_secret() -> None:
    def bad_model(d: dict[str, Any]) -> None:
        d["roles"]["fast"]["model_setting"] = "khong_co"

    with pytest.raises(RuntimeError, match="khong_co"):
        resolve(_cfg(bad_model), _settings(), "scripted")

    def plain_key(d: dict[str, Any]) -> None:
        d["providers"]["cloud_a"]["api_key_setting"] = "llm_base_url"  # str, không phải SecretStr

    with pytest.raises(RuntimeError, match="SecretStr"):
        resolve(_cfg(plain_key), _settings(), "scripted")


# ---- Q-3d-7: công thức Q-3a-16 cho cả fast và strong -----------------------------------------------------


@pytest.mark.parametrize("role", ["fast", "strong"])
def test_q3d7_repo_timing_below_half_stale(role: str) -> None:
    cfg = load_llm_config(LLM_YAML)
    r = cfg.roles[role]  # type: ignore[index]
    worst = worst_case_s(r, cfg.limits)
    backoff = sum(cfg.limits.backoff_base_s * 2**k for k in range(r.max_retries))
    by_hand = (r.max_retries + 1) * r.timeout_s + backoff + r.max_retries * cfg.limits.jitter_max_s
    assert worst == pytest.approx(by_hand)
    assert worst < STALE / 2  # số lần thử × timeout + backoff < ngưỡng stale worker / 2
    assert worst <= r.deadline_s < STALE / 2
    check_timing(cfg, STALE)  # không ném


def test_q3d7_repo_timing_values() -> None:
    cfg = load_llm_config(LLM_YAML)
    assert worst_case_s(cfg.roles["fast"], cfg.limits) == pytest.approx(39.75)
    assert worst_case_s(cfg.roles["strong"], cfg.limits) == pytest.approx(41.25)


@pytest.mark.parametrize(("role", "field", "value", "pattern"), [
    ("strong", "max_retries", 3, r"roles\.strong: \(max_retries\+1\)·timeout_s \+ backoff = 87\.75s"),  # P2 §9 gốc
    ("fast", "timeout_s", 14, r"roles\.fast: \(max_retries\+1\)"),
    ("fast", "deadline_s", 60, r"roles\.fast: deadline_s = 60s ≥ WORKER_STALE_TURN_SECONDS/2"),
    ("strong", "deadline_s", 30, r"roles\.strong: deadline_s = 30s < thời gian retry tối đa 41\.25s"),
])  # fmt: skip
def test_q3d7_timing_violations_refuse_start(role: str, field: str, value: float, pattern: str) -> None:
    cfg = _cfg(lambda d: d["roles"][role].update({field: value}))
    with pytest.raises(RuntimeError, match=pattern):
        check_timing(cfg, STALE)


def test_q3d7_timing_checked_against_configured_stale() -> None:
    # stale 80 → trần 40 s: fast deadline_s 45 vượt (rag_deadline_s, turn_budget_s hạ theo để Settings còn hợp lệ,
    # Q-3c-4, phase3 9.0)
    settings = _settings(app_env="dev", llm_backend="scripted", worker_stale_turn_seconds=80, rag_deadline_s=30,
                         turn_budget_s=70)  # fmt: skip
    with pytest.raises(RuntimeError, match=r"roles\.fast: deadline_s = 45s ≥ WORKER_STALE_TURN_SECONDS/2 = 40s"):
        check_llm(settings)


# ---- Q-3d-13: compose, .env.example ---------------------------------------------------------------------


def test_compose_requires_llm_backend_without_default() -> None:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    value = compose["x-backend-env"]["LLM_BACKEND"]
    assert re.fullmatch(r"\$\{LLM_BACKEND:\?[^}]+\}", value)
    assert "scripted" in value and "real" in value  # thông báo của compose nêu giá trị hợp lệ
    for name in ("backend", "worker"):
        assert compose["services"][name]["environment"]["LLM_BACKEND"] == value
    assert "LLM_BACKEND" not in compose["services"]["mock"]["environment"]


def test_env_example_has_scripted_backend_and_blank_key() -> None:
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "LLM_BACKEND=scripted" in lines
    assert "LLM_API_KEY=" in lines  # tên, không giá trị
    assert not any(re.match(r"^(FAST_MODEL|STRONG_MODEL|LLM_BASE_URL)=\S", line) for line in lines)
