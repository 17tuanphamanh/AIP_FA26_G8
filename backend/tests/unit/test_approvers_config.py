"""`config/approvers.yaml` + `APPROVAL_SLA_MINUTES_DEV` (Phase 4 chặng 4b; phase4 mục 5.1 P1, P12; 5.3 b4, b5). Viết TỪ ĐẶC TẢ.

- b4: `approvers.yaml` thiếu intent đang bật / trùng id / khoá lạ / không có file → khởi động thất bại: `open_runtime` (backend + worker)
  ném `RuntimeError` nêu `approvers.yaml` TRƯỚC khi đụng DB (`database_url` trỏ cổng không có DB — khuôn
  `test_config_files.py::test_q3h1_open_runtime_refuses_bad_policy_before_db`). Nhóm/AD KHÔNG kiểm lúc khởi động (P1).
- b5: `APPROVAL_SLA_MINUTES_DEV` (int 1–30) chỉ ở `APP_ENV ∈ {dev, test}`; env khác đặt → từ chối khởi động (trước mọi kiểm khác, trước
  DB). Giá trị hiệu lực tới node qua `NodeDeps.approval_sla_minutes` (dev + 5 → 5; không đặt → `SLA_MINUTES` = 30) — spy
  `wiring.select_nodes` như `test_4a_debts.py::test_4a6_wiring_passes_app_git_sha_to_node_deps`.
"""

import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from app.core.clock import FakeClock
from app.settings import Settings, check_approvers_config, get_policy, load_approvers
from pydantic import SecretStr, ValidationError

REPO = Path(__file__).resolve().parents[3]
NO_DB = "postgresql+psycopg://x@127.0.0.1:1/khong_co"
ROSTER_OK = "{primary: l1_01, backup: l1_02, head: it_mgr01}"


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]  # _env_file: tham số riêng của pydantic-settings


def _runtime_settings(config_dir: Path | None = None, **over: Any) -> Settings:
    values: dict[str, Any] = {"app_env": "dev", "llm_backend": "scripted", "ml_service_token": SecretStr("t" * 32),
                              "database_url": NO_DB, **over}  # fmt: skip
    if config_dir is not None:
        values["config_dir"] = config_dir
    return _settings(**values)


def _config_copy(tmp_path: Path, approvers: str | None) -> Path:
    """Bản sao NGUYÊN thư mục `config/` của repo; `approvers.yaml` thay bằng `approvers` (None = xoá file)."""
    dst = tmp_path / "config"
    shutil.copytree(REPO / "config", dst)
    target = dst / "approvers.yaml"
    if approvers is None:
        target.unlink()
    else:
        target.write_text(approvers, encoding="utf-8")
    return dst


async def _refused(monkeypatch: pytest.MonkeyPatch, settings: Settings, *, can_execute: bool, match: str) -> None:
    """Từ chối khởi động TRƯỚC DB. Engine SQLAlchemy nối lười (URL cổng 1 không làm `open_runtime` hỏng) nên "trước DB" được kiểm
    bằng spy ở `wiring.open_postgres_saver` (chỗ mở checkpointer Postgres): không được gọi tới."""
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
            async with wiring.open_runtime(settings, engines, clock=None, can_execute=can_execute):  # type: ignore[arg-type]
                pass
        assert not isinstance(info.value, NotImplementedError), "khung chưa hiện thực, không phải từ chối khởi động"
        assert touched == [], "đã mở checkpointer Postgres trước khi từ chối"
    finally:
        await engines.dispose()


async def _deps_of(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> Any:
    """`open_runtime` tới hết (saver in-memory, không DB) — lấy `NodeDeps` mà wiring dựng."""
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
        async with wiring.open_runtime(settings, engines, FakeClock(), can_execute=False):
            pass
    finally:
        await engines.dispose()
    [deps] = captured
    return deps


# ---- b4 / P1: nạp + kiểm approvers.yaml -------------------------------------------------------------------------------


def test_p1_repo_approvers_yaml_vpn_roster() -> None:
    """P1: `vpn: {primary: l1_01, backup: l1_02, head: it_mgr01}`; repo đạt `check_approvers_config` với ENABLED_INTENTS mặc định."""
    approvers = load_approvers(REPO / "config" / "approvers.yaml")
    vpn = approvers.of("vpn")
    assert vpn is not None
    assert (vpn.primary, vpn.backup, vpn.head) == ("l1_01", "l1_02", "it_mgr01")
    settings = _settings()
    assert settings.enabled_intents == ["vpn", "account", "software", "access"]  # T24 P1 (trước T24: ["vpn"])
    check_approvers_config(settings, approvers)  # không ném


def test_b4_enabled_intent_without_roster_refuses(tmp_path: Path) -> None:
    """b4: intent trong ENABLED_INTENTS thiếu roster → RuntimeError nêu `approvers.yaml`. Đổi ở T20a (P10, Q-T20a-1 c): `account`
    nay có roster → dùng intent KHÔNG có roster (`printer`), giữ ý."""
    approvers = load_approvers(REPO / "config" / "approvers.yaml")
    assert approvers.of("printer") is None
    with pytest.raises(RuntimeError, match="approvers.yaml") as info:
        check_approvers_config(_settings(enabled_intents=["vpn", "printer"]), approvers)
    assert not isinstance(info.value, NotImplementedError)
    path = tmp_path / "approvers.yaml"
    path.write_text(f"account: {ROSTER_OK}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="approvers.yaml") as info:
        check_approvers_config(_settings(), load_approvers(path))  # bật vpn, file chỉ có account
    assert not isinstance(info.value, NotImplementedError)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("vpn: {primary: l1_01, backup: l1_01, head: it_mgr01}\n", id="trung-id"),
        pytest.param("vpn: {primary: l1_01, backup: l1_02, head: it_mgr01, note: x}\n", id="khoa-la"),
        pytest.param("vpn: {primary: L1_01, backup: l1_02, head: it_mgr01}\n", id="id-sai-mau"),
        pytest.param("vpn: {primary: l1_01, backup: l1_02}\n", id="thieu-head"),
    ],
)
def test_b4_load_approvers_rejects_bad_schema(tmp_path: Path, body: str) -> None:
    path = tmp_path / "approvers.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValidationError):
        load_approvers(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("can_execute", [False, True], ids=["worker", "backend"])
@pytest.mark.parametrize(
    "approvers",
    [
        pytest.param(f"account: {ROSTER_OK}\n", id="thieu-intent-vpn"),
        pytest.param("vpn: {primary: l1_01, backup: l1_02, head: l1_01}\n", id="trung-id"),
        pytest.param("vpn: {primary: l1_01, backup: l1_02, head: it_mgr01, extra: l2_01}\n", id="khoa-la"),
        pytest.param(None, id="khong-co-file"),
        pytest.param("vpn: [l1_01\n", id="yaml-hong"),
    ],
)
async def test_b4_open_runtime_refuses_bad_approvers_before_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, approvers: str | None, can_execute: bool
) -> None:
    """b4 "Khởi động thất bại" (P1): `open_runtime` nạp `config_dir/approvers.yaml` + `check_approvers_config` TRƯỚC DB; lỗi
    file/YAML/schema bọc thành RuntimeError nêu `approvers.yaml` (không phải lỗi kết nối DB)."""
    settings = _runtime_settings(_config_copy(tmp_path, approvers))
    await _refused(monkeypatch, settings, can_execute=can_execute, match="approvers.yaml")


@pytest.mark.asyncio
async def test_b4_open_runtime_accepts_repo_approvers_copy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Đối chứng b4: bản sao nguyên vẹn `config/` → `open_runtime` chạy hết (saver in-memory) — tức ca hỏng ở trên đỏ ĐÚNG vì
    `approvers.yaml`. Nhóm AD không kiểm lúc khởi động (P1): roster trỏ người không có trong AD vẫn khởi động được."""
    # T24 (Q-T24-8 = A): giữ ý — roster vpn hợp lệ (kể cả người không có trong AD) → khởi động; ca 4 intent mặc định = w2
    # (`test_enable_intents_t24.py`). Mặc định giờ là 4 intent → truyền tường minh `enabled_intents=["vpn"]`.
    await _deps_of(monkeypatch, _runtime_settings(_config_copy(tmp_path, f"vpn: {ROSTER_OK}\n"), enabled_intents=["vpn"]))
    ghost = _config_copy(tmp_path / "ghost", "vpn: {primary: khong_co_1, backup: khong_co_2, head: khong_co_3}\n")
    await _deps_of(monkeypatch, _runtime_settings(ghost, enabled_intents=["vpn"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("can_execute", [False, True], ids=["worker", "backend"])
async def test_t24_default_four_intents_vpn_only_roster_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, can_execute: bool
) -> None:
    """T24 (Q-T24-8, chiều ngược — fail-closed): settings MẶC ĐỊNH (4 intent) + `approvers.yaml` chỉ có vpn → `open_runtime` từ chối
    TRƯỚC DB, thông điệp nêu đủ 3 intent thiếu roster."""
    monkeypatch.delenv("ENABLED_INTENTS", raising=False)
    settings = _runtime_settings(_config_copy(tmp_path, f"vpn: {ROSTER_OK}\n"))
    assert settings.enabled_intents == ["vpn", "account", "software", "access"]
    await _refused(monkeypatch, settings, can_execute=can_execute,
                   match=r"approvers\.yaml thiếu người duyệt cho intent đang bật \['access', 'account', 'software'\]")


# ---- b5 / P12: APPROVAL_SLA_MINUTES_DEV -------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [0, 31, -1])
def test_p12_sla_dev_out_of_range_rejected(bad: int) -> None:
    with pytest.raises(ValidationError):
        _settings(app_env="dev", approval_sla_minutes_dev=bad)


@pytest.mark.parametrize("ok", [1, 2, 30])
def test_p12_sla_dev_in_range_accepted(ok: int) -> None:
    assert _settings(app_env="dev", approval_sla_minutes_dev=ok).approval_sla_minutes_dev == ok


def test_p12_sla_dev_default_unset_and_empty_env_is_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose truyền `${APPROVAL_SLA_MINUTES_DEV:-}` (rỗng khi không đặt) → phải coi là KHÔNG đặt, không phải lỗi 1–30."""
    assert _settings().approval_sla_minutes_dev is None
    monkeypatch.setenv("APPROVAL_SLA_MINUTES_DEV", "")
    assert _settings(app_env="dev").approval_sla_minutes_dev is None
    monkeypatch.setenv("APPROVAL_SLA_MINUTES_DEV", "2")
    assert _settings(app_env="dev").approval_sla_minutes_dev == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("can_execute", [False, True], ids=["worker", "backend"])
@pytest.mark.parametrize("env", [None, "staging", "prod"])
async def test_b5_sla_dev_outside_dev_test_refuses_before_db(
    monkeypatch: pytest.MonkeyPatch, env: str | None, can_execute: bool
) -> None:
    """b5: `APPROVAL_SLA_MINUTES_DEV` đặt ở APP_ENV ∉ {dev, test} → `open_runtime` từ chối (RuntimeError nêu tên biến), TRƯỚC mọi
    kiểm khác (ở đây: trước kiểm `LLM_BACKEND=scripted` ngoài dev/test) và trước DB (khuôn
    `test_app_env.py::test_worker_runtime_refuses_fake_approver`)."""
    settings = _settings(app_env=env, approval_sla_minutes_dev=5, database_url=NO_DB)
    await _refused(monkeypatch, settings, can_execute=can_execute, match="APPROVAL_SLA_MINUTES_DEV")


@pytest.mark.asyncio
@pytest.mark.parametrize("env", ["dev", "test"])
async def test_p12_sla_dev_reaches_node_deps(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    deps = await _deps_of(monkeypatch, _runtime_settings(app_env=env, approval_sla_minutes_dev=5))
    assert deps.approval_sla_minutes == 5


@pytest.mark.asyncio
async def test_p12_sla_unset_uses_policy_sla_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    deps = await _deps_of(monkeypatch, _runtime_settings())
    assert get_policy().constants.SLA_MINUTES == 30
    assert deps.approval_sla_minutes == 30
