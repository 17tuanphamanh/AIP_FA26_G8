"""Phase 6 chặng 6C — khởi động lớp 2 của M5 (phase6 bảng 6.4 c1, c2; 6.1 P1, P2, P10; nợ N2, N5). Viết TỪ ĐẶC TẢ trước code.

Chốt áp dụng (PLAN-6C mục 0): Q-6C-1 = B — nguồn chiến lược DUY NHẤT `Settings.strategy` (env `STRATEGY`); `open_runtime` (trước DB)
từ chối `manual` ở MỌI chế độ, còn lại `check_strategy(settings.strategy, eval_mode=settings.eval_mode)`. Ràng buộc: kiểm chỉ đặt trong
`graph/wiring.open_runtime`, c1 dựng runtime qua `open_runtime` cho API (`can_execute=True`) VÀ worker (`can_execute=False`) — N5.
Lệch S1 (PLAN-6C mục 0): `M5Config.calibrator_version` chỉ kiểm độ dài ở Settings; mẫu `VERSION_PATTERN` kiểm ở `open_runtime` qua
`load_calibrator` — vẫn lỗi khởi động TRƯỚC DB.

- c1: `STRATEGY ∈ {llm_only, full_auto}` + `EVAL_MODE=false` → `StrategyNotAllowed` trước DB; `manual` → từ chối ở cả `EVAL_MODE`
  false/true; `hybrid` → chạy; `EVAL_MODE=true` + `llm_only` → chạy. Runtime chạy hết → estimator thật (`LlmRiskEstimator`),
  `NodeDeps.eval_mode` = Settings.
- D-60 (sửa c1 có chủ ý): `rule_only`, `hybrid_guarded` rời `EVAL_ONLY` (chọn được lúc vận hành qua DB) → `STRATEGY=rule_only|
  hybrid_guarded` + `EVAL_MODE=false` KHỞI ĐỘNG ĐƯỢC nhưng env bị bỏ qua (log cảnh báo — DB quyết); `NodeDeps` không còn `strategy`
  (B12 đọc chiến lược đã chụp trên ticket).
- c2: `policy.json` khối `m5` thiếu/khoá lạ → `ValidationError` khi nạp; `calibrator_version` sai mẫu / không có file / file hỏng →
  `RuntimeError` "calibrator" trước DB; `null` → `NodeDeps.calibrator is None`; calibrator fit thật (khuôn cb2/cb3 của 6A) lưu vào
  `<config>/calibrators/` → nạp đúng version (P10: chỉ qua `load_calibrator(version, config_dir / "calibrators")`).

"Trước DB" = spy `wiring.open_postgres_saver` không được gọi (khuôn `test_approvers_config._refused`); `NodeDeps` lấy bằng spy
`wiring.select_nodes` (khuôn `_deps_of`). Policy đưa vào wiring bằng `monkeypatch.setattr(wiring, "get_policy", …)` (khuôn
`test_config_files.py:370`) VÀ ghi vào bản sao `config/` (cùng nội dung) để không phụ thuộc wiring đọc policy theo đường nào.
"""

import json
import re
import shutil
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

import numpy as np
import pytest
import scipy.special
from app.core.clock import FakeClock
from app.risk.calibrator import Calibrator, LabeledSample, fit_platt, save_calibrator
from app.risk.estimator import LlmRiskEstimator, PMethod
from app.risk.strategy import StrategyNotAllowed
from app.settings import (
    M5Config,
    PolicyFile,
    Settings,
    get_policy,
    load_policy,
    parse_policy,
)
from pydantic import SecretStr, ValidationError

REPO = Path(__file__).resolve().parents[3]
POLICY_JSON = REPO / "config" / "policy.json"
NO_DB = "postgresql+psycopg://x@127.0.0.1:1/khong_co"
EVAL_ONLY = ("llm_only", "full_auto")  # phase6 5.3 EVAL_ONLY — D-60: rule_only, hybrid_guarded rời tập này (chạy được lúc vận hành)
RUNTIME_ONLY_FROM_DB = ("rule_only", "hybrid_guarded")  # D-60: env ngoài EVAL_MODE chấp nhận nhưng bỏ qua
MANUAL_MSG = "manual chỉ tính giải tích ở harness M8, không chạy hệ thống"  # PLAN-6C Q-6C-1 (nguyên văn)
NOT_ALLOWED_MSG = "chỉ dùng ở chế độ đánh giá"
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
PROCESSES = pytest.mark.parametrize("can_execute", [True, False], ids=["api", "worker"])  # N5: cả API lẫn worker


# ---- khung dựng runtime ----------------------------------------------------------------------------------------------


def _settings(config_dir: Path | None = None, **over: Any) -> Settings:
    values: dict[str, Any] = {"app_env": "dev", "llm_backend": "scripted", "ml_service_token": SecretStr("t" * 32),
                              "database_url": NO_DB, **over}  # fmt: skip
    if config_dir is not None:
        values["config_dir"] = config_dir
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]  # _env_file: tham số riêng của pydantic-settings


def _raw_policy() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(POLICY_JSON.read_text(encoding="utf-8"))
    return data


def _policy_file(tmp_path: Path, edit: Callable[[dict[str, Any]], None]) -> Path:
    raw = _raw_policy()
    edit(raw)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return path


def _config_copy(tmp_path: Path, m5: dict[str, Any]) -> Path:
    """Bản sao NGUYÊN `config/` của repo (khuôn `test_approvers_config._config_copy`); `policy.json` có khối `m5` = `m5`."""
    dst = tmp_path / "config"
    shutil.copytree(REPO / "config", dst)
    raw = _raw_policy()
    raw["m5"] = m5
    (dst / "policy.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return dst


def _use_policy(monkeypatch: pytest.MonkeyPatch, config_dir: Path) -> PolicyFile:
    """wiring đọc policy qua `wiring.get_policy()` — đè bằng policy nạp từ bản sao (cùng byte với file trong bản sao)."""
    from app.graph import wiring

    policy = load_policy(config_dir / "policy.json")
    monkeypatch.setattr(wiring, "get_policy", lambda: policy)
    return policy


async def _refused(monkeypatch: pytest.MonkeyPatch, settings: Settings, *, can_execute: bool, match: str) -> RuntimeError:
    """Từ chối khởi động TRƯỚC DB (khuôn `test_approvers_config._refused`): spy `open_postgres_saver` không được gọi tới."""
    from app.db.session import create_engines
    from app.graph import wiring
    from langgraph.checkpoint.memory import InMemorySaver

    touched: list[str] = []

    @asynccontextmanager
    async def spy_saver(*_: Any, **__: Any) -> AsyncIterator[InMemorySaver]:
        touched.append("open_postgres_saver")
        yield InMemorySaver()

    monkeypatch.setattr(wiring, "open_postgres_saver", spy_saver)
    engines = create_engines(settings)
    try:
        with pytest.raises(RuntimeError, match=match) as info:
            async with wiring.open_runtime(settings, engines, FakeClock(), can_execute=can_execute):
                pass
        assert not isinstance(info.value, NotImplementedError), "khung chưa hiện thực, không phải từ chối khởi động"
        assert touched == [], "đã mở checkpointer Postgres trước khi từ chối"
    finally:
        await engines.dispose()
    return info.value


async def _deps_of(monkeypatch: pytest.MonkeyPatch, settings: Settings, *, can_execute: bool) -> Any:
    """`open_runtime` tới hết (saver in-memory, không DB) — lấy `NodeDeps` wiring dựng (khuôn `test_approvers_config._deps_of`)."""
    from app.db.session import create_engines
    from app.graph import wiring
    from langgraph.checkpoint.memory import InMemorySaver

    @asynccontextmanager
    async def memory_saver(*_: Any, **__: Any) -> AsyncIterator[InMemorySaver]:
        yield InMemorySaver()

    captured: list[Any] = []
    real_select = wiring.select_nodes

    def spy_select(s: Settings, deps: Any) -> Any:
        captured.append(deps)
        return real_select(s, deps)

    monkeypatch.setattr(wiring, "open_postgres_saver", memory_saver)
    monkeypatch.setattr(wiring, "select_nodes", spy_select)
    engines = create_engines(settings)
    try:
        async with wiring.open_runtime(settings, engines, FakeClock(), can_execute=can_execute):
            pass
    finally:
        await engines.dispose()
    [deps] = captured
    return deps


def _synthetic_calibrator() -> Calibrator:
    """Đoạn sinh chuẩn spec 4.5 (cb2/cb3 của 6A — chép như `test_calibrator.make_samples`), n = 200, `now` có múi giờ."""
    n = 200
    rng = np.random.default_rng(20260925)
    p_true = rng.uniform(0.02, 0.98, n)
    y = rng.uniform(0, 1, n) < p_true
    raw = scipy.special.expit(2 * scipy.special.logit(p_true))
    samples = [LabeledSample(split="calibration", family=f"f{i % 50}", raw_prob=float(r), y=bool(v))
               for i, (r, v) in enumerate(zip(raw, y, strict=True))]  # fmt: skip
    return fit_platt(samples, now=NOW)


# ---- c1: check_strategy lúc khởi động (API và worker) ------------------------------------------------------------------


@pytest.mark.asyncio
@PROCESSES
@pytest.mark.parametrize("strategy", EVAL_ONLY)
async def test_c1_eval_only_strategy_without_eval_mode_refused_before_db(
    monkeypatch: pytest.MonkeyPatch, strategy: str, can_execute: bool
) -> None:
    """c1 (P1, N5, st15): `STRATEGY ∈ EVAL_ONLY` + `EVAL_MODE=false` → `StrategyNotAllowed` (lớp con RuntimeError) TRƯỚC DB, ở cả
    API lẫn worker; thông điệp nêu "chỉ dùng ở chế độ đánh giá"."""
    exc = await _refused(monkeypatch, _settings(strategy=strategy, eval_mode=False), can_execute=can_execute,
                         match=NOT_ALLOWED_MSG)  # fmt: skip
    assert isinstance(exc, StrategyNotAllowed)


@pytest.mark.asyncio
@PROCESSES
@pytest.mark.parametrize("eval_mode", [False, True], ids=["van-hanh", "danh-gia"])
async def test_c1_manual_strategy_refused_in_every_mode_before_db(
    monkeypatch: pytest.MonkeyPatch, eval_mode: bool, can_execute: bool
) -> None:
    """c1 + Q-6C-1 = B: `STRATEGY=manual` → RuntimeError đúng chữ "manual chỉ tính giải tích ở harness M8, không chạy hệ thống",
    TRƯỚC DB, ở MỌI chế độ (kể cả `EVAL_MODE=true`)."""
    await _refused(monkeypatch, _settings(strategy="manual", eval_mode=eval_mode), can_execute=can_execute,
                   match=re.escape(MANUAL_MSG))  # fmt: skip


@pytest.mark.asyncio
@PROCESSES
async def test_c1_hybrid_runs_with_real_estimator(monkeypatch: pytest.MonkeyPatch, can_execute: bool) -> None:
    """c1 (P1, TQ-3, N2): `hybrid` + `EVAL_MODE=false` → khởi động được; `NodeDeps.estimator` là `LlmRiskEstimator` (không còn
    `DisabledEstimator`); `strategy == "hybrid"`, `eval_mode is False`."""
    deps = await _deps_of(monkeypatch, _settings(strategy="hybrid", eval_mode=False), can_execute=can_execute)
    assert isinstance(deps.estimator, LlmRiskEstimator)
    assert not hasattr(deps, "strategy")  # D-60: B12 đọc chiến lược trên ticket, không từ NodeDeps
    assert deps.eval_mode is False


@pytest.mark.asyncio
@PROCESSES
async def test_c1_llm_only_runs_in_eval_mode(monkeypatch: pytest.MonkeyPatch, can_execute: bool) -> None:
    """c1 (st15 "eval_mode=True: cả 5 qua"): `EVAL_MODE=true` + `llm_only` → khởi động được; `NodeDeps.eval_mode is True` (cùng nguồn
    Settings — N2); estimator thật. D-60: chiến lược EVAL chụp lên ticket ở API (`api/strategy.snapshot_for_new_ticket`), không ở
    NodeDeps."""
    deps = await _deps_of(monkeypatch, _settings(strategy="llm_only", eval_mode=True), can_execute=can_execute)
    assert isinstance(deps.estimator, LlmRiskEstimator)
    assert not hasattr(deps, "strategy")
    assert deps.eval_mode is True


@pytest.mark.asyncio
@PROCESSES
@pytest.mark.parametrize("strategy", RUNTIME_ONLY_FROM_DB)
async def test_c1_d60_runtime_strategy_in_env_starts_but_is_ignored(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, strategy: str, can_execute: bool
) -> None:
    """D-60 (sửa c1 có chủ ý): `STRATEGY=rule_only|hybrid_guarded` + `EVAL_MODE=false` → khởi động được (trước D-60: từ chối); env bị
    bỏ qua — log cảnh báo nêu "bị bỏ qua ngoài EVAL_MODE" (chiến lược vận hành do DB quyết)."""
    caplog.set_level("WARNING", logger="app.graph.wiring")
    deps = await _deps_of(monkeypatch, _settings(strategy=strategy, eval_mode=False), can_execute=can_execute)
    assert deps.eval_mode is False
    assert any("bị bỏ qua ngoài EVAL_MODE" in r.getMessage() and strategy in r.getMessage() for r in caplog.records)


# ---- c2: policy.json khối m5 -------------------------------------------------------------------------------------------


def test_c2_repo_policy_has_m5_block() -> None:
    """c2 (P2): `config/policy.json` của repo có `m5 = {p_method: self_report, calibrator_version: null}`."""
    assert _raw_policy()["m5"] == {"p_method": "self_report", "calibrator_version": None}
    assert get_policy().m5 == M5Config(p_method="self_report", calibrator_version=None)


def test_c2_m5_p_method_literal_equals_pmethod() -> None:
    """TQ-4: `M5Config.p_method` chép Literal (settings không import estimator) — tập giá trị phải bằng đúng `PMethod`."""
    annotation = M5Config.model_fields["p_method"].annotation
    assert set(get_args(annotation)) == set(get_args(PMethod.__value__)) == {"self_report", "sampling_k5"}


def test_c2_m5_config_frozen_forbid() -> None:
    """TQ-4: `M5Config` frozen (không sửa được sau khi nạp)."""
    m5 = M5Config(p_method="self_report", calibrator_version=None)
    with pytest.raises(ValidationError):
        m5.p_method = "sampling_k5"  # type: ignore[misc]


def _drop_m5(raw: dict[str, Any]) -> None:
    del raw["m5"]


def _m5_extra_key(raw: dict[str, Any]) -> None:
    raw["m5"]["khoa_la"] = 1


def _m5_no_calibrator_key(raw: dict[str, Any]) -> None:
    del raw["m5"]["calibrator_version"]


def _m5_bad_p_method(raw: dict[str, Any]) -> None:
    raw["m5"]["p_method"] = "sampling_k7"


def _m5_empty_version(raw: dict[str, Any]) -> None:
    raw["m5"]["calibrator_version"] = ""


def _m5_long_version(raw: dict[str, Any]) -> None:
    raw["m5"]["calibrator_version"] = "p" * 65


BAD_M5: dict[str, Callable[[dict[str, Any]], None]] = {
    "thieu-khoi-m5": _drop_m5,
    "khoa-la": _m5_extra_key,
    "thieu-khoa-calibrator_version": _m5_no_calibrator_key,
    "p_method-la": _m5_bad_p_method,
    "version-rong": _m5_empty_version,
    "version-65-ky-tu": _m5_long_version,
}


@pytest.mark.parametrize("edit", list(BAD_M5.values()), ids=list(BAD_M5))
def test_c2_bad_m5_block_rejected_on_load(tmp_path: Path, edit: Callable[[dict[str, Any]], None]) -> None:
    """c2 (P2, TQ-4): thiếu khối `m5` (bắt buộc) / khoá lạ (extra=forbid) / thiếu khoá `calibrator_version` / `p_method` ngoài
    Literal / version ngoài 1–64 ký tự → `ValidationError` khi nạp (`load_policy` và `parse_policy`) → không khởi động."""
    path = _policy_file(tmp_path, edit)
    with pytest.raises(ValidationError):
        load_policy(path)
    with pytest.raises(ValidationError):
        parse_policy(path.read_bytes())


@pytest.mark.asyncio
@PROCESSES
@pytest.mark.parametrize("version", ["platt-2026-xyz", "platt-20261013-0123ABCD", "../../policy", "platt-20261013-0123abcd.json"],
                         ids=["sai-mau", "hex-hoa", "duong-dan", "duoi-json"])  # fmt: skip
async def test_c2_calibrator_version_bad_pattern_refused_before_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: str, can_execute: bool
) -> None:
    """c2 (P2, P10, lệch S1): `calibrator_version` sai mẫu `VERSION_PATTERN` → RuntimeError nêu "calibrator", TRƯỚC DB."""
    config_dir = _config_copy(tmp_path, {"p_method": "self_report", "calibrator_version": version})
    _use_policy(monkeypatch, config_dir)
    await _refused(monkeypatch, _settings(config_dir), can_execute=can_execute, match="calibrator")


@pytest.mark.asyncio
@PROCESSES
async def test_c2_calibrator_file_missing_refused_before_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, can_execute: bool
) -> None:
    """c2 (P10): mẫu đúng nhưng `<config>/calibrators/<version>.json` không có → RuntimeError "calibrator", TRƯỚC DB."""
    config_dir = _config_copy(tmp_path, {"p_method": "self_report", "calibrator_version": "platt-20261013-0123abcd"})
    (config_dir / "calibrators").mkdir(exist_ok=True)
    _use_policy(monkeypatch, config_dir)
    await _refused(monkeypatch, _settings(config_dir), can_execute=can_execute, match="calibrator")


@pytest.mark.asyncio
@PROCESSES
@pytest.mark.parametrize("content", ["{không phải json", '{"version": "platt-20261013-0123abcd"}'],
                         ids=["json-hong", "thieu-tham-so"])  # fmt: skip
async def test_c2_calibrator_file_corrupt_refused_before_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str, can_execute: bool
) -> None:
    """c2 (P10 "File lỗi/thiếu → không khởi động"): file calibrator hỏng → RuntimeError "calibrator", TRƯỚC DB."""
    version = "platt-20261013-0123abcd"
    config_dir = _config_copy(tmp_path, {"p_method": "self_report", "calibrator_version": version})
    (config_dir / "calibrators").mkdir(exist_ok=True)
    (config_dir / "calibrators" / f"{version}.json").write_text(content, encoding="utf-8")
    _use_policy(monkeypatch, config_dir)
    await _refused(monkeypatch, _settings(config_dir), can_execute=can_execute, match="calibrator")


@pytest.mark.asyncio
@PROCESSES
async def test_c2_calibrator_null_gives_none(monkeypatch: pytest.MonkeyPatch, can_execute: bool) -> None:
    """c2 (P10, D-38): `calibrator_version: null` (policy repo) → `NodeDeps.calibrator is None` (chưa hiệu chỉnh → không AUTO)."""
    assert get_policy().m5.calibrator_version is None
    deps = await _deps_of(monkeypatch, _settings(), can_execute=can_execute)
    assert deps.calibrator is None
    assert isinstance(deps.estimator, LlmRiskEstimator)  # runtime chạy hết → estimator thật (TQ-3)


@pytest.mark.asyncio
@PROCESSES
async def test_c2_real_calibrator_loaded_from_config_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, can_execute: bool
) -> None:
    """c2 (P10, TQ-13): calibrator fit thật (dữ liệu tổng hợp cb2/cb3), `save_calibrator` vào `<bản sao config>/calibrators/`,
    `m5.calibrator_version` = version đó → `NodeDeps.calibrator.params.version == version`, biến đổi như bản đã lưu."""
    config_dir = _config_copy(tmp_path, {"p_method": "self_report", "calibrator_version": None})
    (config_dir / "calibrators").mkdir(exist_ok=True)
    cal = _synthetic_calibrator()
    saved = save_calibrator(cal, config_dir / "calibrators")
    assert saved.parent == config_dir / "calibrators"
    version = cal.params.version
    raw = json.loads((config_dir / "policy.json").read_text(encoding="utf-8"))
    raw["m5"] = {"p_method": "self_report", "calibrator_version": version}
    (config_dir / "policy.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    _use_policy(monkeypatch, config_dir)
    deps = await _deps_of(monkeypatch, _settings(config_dir), can_execute=can_execute)
    assert deps.calibrator is not None
    assert deps.calibrator.params.version == version
    assert deps.calibrator.params == cal.params
    assert deps.calibrator.transform(0.3) == cal.transform(0.3)
