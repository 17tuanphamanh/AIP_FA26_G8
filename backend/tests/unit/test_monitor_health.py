"""M9 A4 — `/api/health`: `llm` (Q-M9-7) + `monitor` (Q-M9-B1-6) CHỈ báo, và cache 10 giây (Q-M9-A4-4).

Không gọi LLM thật, không cần Docker: probe tiêm qua `app.state.llm_probe` / `app.state.monitor_probe` (như
`kb_probe` của 3c), đồng hồ tiêm qua `app.state.kb_monotonic` — **không `sleep`** cho phần cache.

Hai bất biến được ghim ở đây:
  1. `llm`, `monitor` KHÔNG BAO GIỜ đổi mã 200/503 — mã chỉ do `checks` (db/qdrant/mock/ml) quyết, như `kb`.
  2. Hai lần gọi trong 10 giây — kể cả đồng thời — mỗi phụ thuộc chỉ kiểm MỘT lần.
"""

import ast
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from app.api.health import HEALTH_CACHE_SECONDS, LlmStatus, MonitorStatus
from app.db.session import Engines
from app.llm.config import Price
from app.main import (
    _default_llm_probe,
    _default_monitor_probe,
    create_app,
    llm_needs_spend,
    llm_status,
    llm_targets,
)
from app.settings import Settings
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.fakes.runtime import no_runtime

LLM_STATUSES: tuple[LlmStatus, ...] = (
    "scripted", "real:configured", "real:missing_pricing", "spend_cap_reached", "unknown",
)  # fmt: skip
MONITOR_STATUSES: tuple[MonitorStatus, ...] = ("ok", "not_configured", "wrong_role", "down")


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg, arg-type]


async def ok() -> None:
    return None


async def broken() -> None:
    raise ConnectionError("không kết nối được")


async def kb_missing() -> str | None:
    return None


class Counter:
    """Đếm số lần phụ thuộc bị kiểm thật (không tính lần đọc cache)."""

    def __init__(self, result: object = None) -> None:
        self.calls = 0
        self._result = result

    async def __call__(self) -> Any:
        self.calls += 1
        return self._result


def _app(
    *,
    checks: dict[str, Any] | None = None,
    kb: Any = kb_missing,
    llm: Any = None,
    monitor: Any = None,
    clock: list[float] | None = None,
    **over: object,
) -> FastAPI:
    """App với 4 phụ thuộc của health tiêm hết; `clock` tiêm đồng hồ monotonic (ô 0 là "bây giờ")."""
    app = create_app(_settings(**over), health_checks=checks or {"db": ok}, runtime=no_runtime,  # type: ignore[arg-type]
                     kb_probe=kb)  # fmt: skip
    if llm is not None:
        app.state.llm_probe = llm
    if monitor is not None:
        app.state.monitor_probe = monitor
    if clock is not None:
        app.state.kb_monotonic = lambda: clock[0]
    return app


# ---- 1. Cache 10 giây + khoá single-flight (Q-M9-A4-4) -------------------------------------------


def test_two_calls_within_10s_check_each_dependency_once() -> None:
    """Đạt khi của #11: 2 lần gọi trong 10 giây → MỖI phụ thuộc kiểm 1 lần. Biên 10 giây là mốc làm mới."""
    db, kb, llm, monitor = Counter(), Counter(None), Counter("scripted"), Counter("ok")
    clock = [1000.0]
    with TestClient(_app(checks={"db": db}, kb=kb, llm=llm, monitor=monitor, clock=clock)) as client:
        assert client.get("/api/health").status_code == 200
        clock[0] = 1000.0 + HEALTH_CACHE_SECONDS - 0.001  # 9,999 s — vẫn trong cửa sổ
        assert client.get("/api/health").status_code == 200
        assert (db.calls, kb.calls, llm.calls, monitor.calls) == (1, 1, 1, 1)
        clock[0] = 1000.0 + HEALTH_CACHE_SECONDS  # đúng 10,0 s — hết hạn (so `<`)
        client.get("/api/health")
        assert (db.calls, kb.calls, llm.calls, monitor.calls) == (2, 2, 2, 2)


def test_cached_body_is_identical() -> None:
    """Lần thứ hai trả đúng body đã lưu (không dựng lại một phần)."""
    clock = [50.0]
    with TestClient(_app(llm=Counter("scripted"), monitor=Counter("ok"), clock=clock)) as client:
        first = client.get("/api/health").json()
        clock[0] += 5.0
        assert client.get("/api/health").json() == first


@pytest.mark.asyncio
async def test_concurrent_calls_single_flight() -> None:
    """Hai request ĐỒNG THỜI lúc cache nguội: khoá giữ suốt lượt tính → mỗi phụ thuộc vẫn 1 lần.
    Không có khoá thì cả hai cùng thấy cache rỗng và cùng đi kiểm (2 lần)."""
    gate = asyncio.Event()

    class Slow(Counter):
        async def __call__(self) -> Any:
            self.calls += 1
            await gate.wait()  # giữ lượt tính mở cho tới khi cả hai request đã vào
            return self._result

    db, llm, monitor = Slow(), Counter("scripted"), Counter("ok")
    app = _app(checks={"db": db}, llm=llm, monitor=monitor, clock=[7.0])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        first = asyncio.create_task(client.get("/api/health"))
        second = asyncio.create_task(client.get("/api/health"))
        await asyncio.sleep(0)  # nhường vòng lặp: request 1 vào khối khoá, request 2 đứng chờ khoá
        gate.set()
        r1, r2 = await asyncio.gather(first, second)
    assert (r1.status_code, r2.status_code) == (200, 200)
    assert r1.json() == r2.json()
    assert (db.calls, llm.calls, monitor.calls) == (1, 1, 1)


def test_503_is_cached_too() -> None:
    """Cache GỒM CẢ mã: phụ thuộc hồi phục trong 10 giây vẫn thấy 503 (chấp nhận trễ ≤ 10 s, Q-M9-A4-4)."""
    state = {"fail": True}

    async def flaky() -> None:
        if state["fail"]:
            raise ConnectionError("chưa lên")

    clock = [0.0]
    with TestClient(_app(checks={"db": flaky}, llm=Counter("scripted"), monitor=Counter("ok"),
                         clock=clock)) as client:  # fmt: skip
        assert client.get("/api/health").status_code == 503
        state["fail"] = False
        clock[0] += 9.0
        assert client.get("/api/health").status_code == 503  # cache
        clock[0] += 1.0
        assert client.get("/api/health").status_code == 200


# ---- 2. `llm` và `monitor` không đổi mã HTTP -----------------------------------------------------


@pytest.mark.parametrize("status", LLM_STATUSES)
@pytest.mark.parametrize(("check", "code"), [(ok, 200), (broken, 503)])
def test_llm_never_changes_status_code(status: LlmStatus, check: Any, code: int) -> None:
    with TestClient(_app(checks={"db": check}, llm=Counter(status), monitor=Counter("ok"))) as client:
        r = client.get("/api/health")
    assert r.status_code == code  # mã chỉ do `checks` quyết — `llm` chỉ báo (như `kb`)
    assert r.json()["llm"] == status
    assert "llm" not in r.json()["checks"] and "llm" not in r.json()["failed"]


@pytest.mark.parametrize("status", MONITOR_STATUSES)
@pytest.mark.parametrize(("check", "code"), [(ok, 200), (broken, 503)])
def test_monitor_never_changes_status_code(status: MonitorStatus, check: Any, code: int) -> None:
    with TestClient(_app(checks={"db": check}, llm=Counter("scripted"), monitor=Counter(status))) as client:
        r = client.get("/api/health")
    assert r.status_code == code
    assert r.json()["monitor"] == status
    assert "monitor" not in r.json()["checks"] and "monitor" not in r.json()["failed"]


def test_probe_error_does_not_break_health() -> None:
    """Probe ném → `llm="unknown"`, `monitor="down"`, mã vẫn 200, log chỉ TÊN LỚP lỗi (không DSN, không URL)."""

    async def raising() -> Any:
        raise RuntimeError("probe hỏng")

    with TestClient(_app(llm=raising, monitor=raising)) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert (r.json()["llm"], r.json()["monitor"]) == ("unknown", "down")


def test_probe_timeout_reported_not_fatal() -> None:
    """Probe treo → hết `health_timeout` → `down`/`unknown`, không treo cả route."""

    async def hang() -> Any:
        await asyncio.sleep(1)

    with TestClient(_app(llm=hang, monitor=hang, health_timeout=0.05)) as client:
        r = client.get("/api/health")
    assert r.status_code == 200
    assert (r.json()["llm"], r.json()["monitor"]) == ("unknown", "down")


def test_body_has_no_secret_or_number() -> None:
    """Q-M9-A4-9: body không chứa số tiền, DSN hay tên model — `llm`/`monitor` là chuỗi nhãn."""
    with TestClient(_app(llm=Counter("spend_cap_reached"), monitor=Counter("wrong_role"))) as client:
        body = client.get("/api/health").json()
    assert isinstance(body["llm"], str) and isinstance(body["monitor"], str)
    assert body["llm"] in LLM_STATUSES and body["monitor"] in MONITOR_STATUSES


# ---- 3. `llm_status` thuần — phủ cả 4 giá trị (Q-M9-A4-2, Q-M9-A4-3) -----------------------------

FREE = Price.model_validate({"in": 0, "out": 0})
PAID = Price.model_validate({"in": 1.0, "out": 2.0})
PRICING = {"scripted": FREE, "m-fast": PAID, "m-strong": PAID, "m-free": FREE}


@pytest.mark.parametrize(
    ("case", "backend", "models", "spent", "expected"),
    [
        ("backend chưa đặt (chỉ ở test)", None, ("m-fast",), 0.0, "unknown"),
        ("scripted", "scripted", ("scripted",), None, "scripted"),
        # scripted giá 0 → trần chi không áp, dù tổng chi đã vượt (Q-3d-4)
        ("scripted vượt trần", "scripted", ("scripted",), 99.0, "scripted"),
        ("model chính thiếu dòng giá", "real", ("m-fast", "la-lung"), 0.0, "real:missing_pricing"),
        ("fallback thiếu dòng giá", "real", ("m-fast", "fb-khong-gia"), 0.0, "real:missing_pricing"),
        ("env model chưa đặt", "real", (None, "m-strong"), 0.0, "real:missing_pricing"),
        ("đủ giá, còn ngân sách", "real", ("m-fast", "m-strong"), 37.99, "real:configured"),
        ("đọc tổng chi lỗi", "real", ("m-fast",), None, "unknown"),
        ("đúng trần (so >=)", "real", ("m-fast",), 38.0, "spend_cap_reached"),
        ("sát dưới trần", "real", ("m-fast",), 38.0 - 1e-9, "real:configured"),
        ("vượt trần", "real", ("m-fast",), 100.0, "spend_cap_reached"),
        # mọi đích giá 0 → trần không áp, kể cả khi SUM đã vượt
        ("đích miễn phí vượt trần", "real", ("m-free",), 99.0, "real:configured"),
    ],
)
def test_llm_status_table(
    case: str, backend: str | None, models: tuple[str | None, ...], spent: float | None, expected: LlmStatus
) -> None:
    assert llm_status(backend, models, PRICING, spent, 38.0) == expected, case


def test_llm_status_covers_all_four_values() -> None:
    """Q-M9-A4-2: giữ đủ 4 giá trị của Q-M9-7 trong kiểu VÀ trong bảng test (`real:missing_pricing` không xuất
    hiện ở process thật vì `check_llm` đã chặn khởi động — vẫn phải phủ)."""
    got = {
        llm_status("scripted", ("scripted",), PRICING, None, 38.0),
        llm_status("real", ("m-fast",), PRICING, 0.0, 38.0),
        llm_status("real", ("khong-co-gia",), PRICING, 0.0, 38.0),
        llm_status("real", ("m-fast",), PRICING, 38.0, 38.0),
    }
    assert got == {"scripted", "real:configured", "real:missing_pricing", "spend_cap_reached"}


@pytest.mark.parametrize(
    ("backend", "models", "expected"),
    [
        ("scripted", ("scripted",), False),  # không đụng DB khi scripted
        ("real", ("m-fast",), True),
        ("real", ("khong-co-gia",), False),  # thiếu giá → báo missing_pricing, khỏi đọc
        ("real", ("m-free",), False),  # mọi đích miễn phí → trần không áp
        (None, ("m-fast",), False),
    ],
)
def test_llm_needs_spend(backend: str | None, models: tuple[str | None, ...], expected: bool) -> None:
    assert llm_needs_spend(backend, models, PRICING) is expected


# ---- 4. Probe thật: không gọi provider, không rơi về engines.main --------------------------------


class FakeStore:
    """Đếm số lần đọc tổng chi; `fail=True` → ném như DB lỗi."""

    created = 0
    calls = 0
    fail = False

    def __init__(self, engine: object) -> None:
        type(self).created += 1
        self.engine = engine

    async def spend_total(self) -> float:
        type(self).calls += 1
        if type(self).fail:
            raise ConnectionError("DB chết")
        return 0.0


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> type[FakeStore]:
    FakeStore.created = FakeStore.calls = 0
    FakeStore.fail = False
    monkeypatch.setattr("app.main.SqlLlmStore", FakeStore)
    return FakeStore


def _fake_app(main: object = None, monitor: object = None) -> Any:
    engines = Engines(main=main, lock=None, monitor=monitor)  # type: ignore[arg-type]
    return SimpleNamespace(state=SimpleNamespace(engines=engines))


class NeverEngine:
    """Engine không được phép dùng: chạm vào là đỏ (bất biến 4.1 — M9 không rơi về app_rw)."""

    def connect(self) -> Any:
        raise AssertionError("M9 không được dùng engine này")


@pytest.mark.asyncio
async def test_llm_probe_scripted_does_not_read_spend(store: type[FakeStore]) -> None:
    """`LLM_BACKEND=scripted` (mọi test, conftest gốc): không một lời gọi DB nào."""
    probe = _default_llm_probe(_settings(llm_backend="scripted"), _fake_app(main=NeverEngine()))
    assert await probe() == "scripted"
    assert (store.created, store.calls) == (0, 0)


@pytest.mark.asyncio
async def test_llm_probe_reads_spend_only_when_needed(store: type[FakeStore]) -> None:
    """`real` + model có dòng giá trả phí → đọc SUM(llm_calls.cost_usd) đúng 1 lần mỗi lượt."""
    settings = _settings(llm_backend="real", fast_model="scripted", strong_model="scripted")
    probe = _default_llm_probe(settings, _fake_app(main=object()))
    assert await probe() == "real:configured"  # `scripted` giá 0 → không cần đọc
    assert store.calls == 0
    settings = _settings(llm_backend="real", fast_model="khong-co-gia", strong_model="scripted")
    assert await _default_llm_probe(settings, _fake_app(main=object()))() == "real:missing_pricing"
    assert store.calls == 0  # thiếu giá → không đụng DB


@pytest.mark.asyncio
async def test_llm_probe_spend_error_is_unknown(
    store: type[FakeStore], caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    """Đọc tổng chi lỗi → `unknown` (không báo `real:configured` khi không biết đã chi bao nhiêu), log TÊN LỚP."""
    store.fail = True
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "llm.yaml").write_text(_PAID_YAML, encoding="utf-8")
    settings = _settings(llm_backend="real", fast_model="m-paid", strong_model="m-paid", config_dir=cfg)
    probe = _default_llm_probe(settings, _fake_app(main=object()))
    with caplog.at_level("WARNING", logger="app.main"):
        assert await probe() == "unknown"
    assert store.calls == 1
    messages = [r.getMessage() for r in caplog.records if r.name == "app.main"]
    assert messages == ["không đọc được tổng chi LLM cho /api/health: ConnectionError"]


@pytest.mark.asyncio
async def test_llm_probe_spend_cap_reached(store: type[FakeStore], tmp_path: Path) -> None:
    """Tổng chi ≥ trần của `config/llm.yaml` → `spend_cap_reached`, mã HTTP không đổi (test ở mục 2)."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "llm.yaml").write_text(_PAID_YAML, encoding="utf-8")

    class Over(FakeStore):
        async def spend_total(self) -> float:
            type(self).calls += 1
            return 38.0

    monkey = pytest.MonkeyPatch()
    monkey.setattr("app.main.SqlLlmStore", Over)
    try:
        settings = _settings(llm_backend="real", fast_model="m-paid", strong_model="m-paid", config_dir=cfg)
        assert await _default_llm_probe(settings, _fake_app(main=object()))() == "spend_cap_reached"
    finally:
        monkey.undo()


def test_llm_probe_never_builds_provider() -> None:
    """Q-M9-7 ghim tĩnh: probe KHÔNG dựng gateway/provider và không gọi LLM. Tên bị cấm trong thân hàm."""
    tree = ast.parse(inspect.getsource(_default_llm_probe))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert names & {"open_llm", "LLMClient", "OpenAICompatProvider", "Provider", "resolve", "complete"} == set()
    assert "load_llm_config" in names  # chỉ đọc cấu hình


@pytest.mark.asyncio
async def test_llm_targets_lists_roles_and_fallback() -> None:
    """Đích = 2 vai trò + mọi fallback; env chưa đặt → None (để ra `real:missing_pricing`, không bỏ sót)."""
    from app.llm.config import load_llm_config

    cfg = load_llm_config(_settings().config_dir / "llm.yaml")
    assert llm_targets(cfg, _settings(fast_model="a", strong_model="b")) == ("a", "b")
    assert llm_targets(cfg, _settings(fast_model="a")) == ("a", None)


_PAID_YAML = """
providers:
  cloud_a: {kind: openai_compat, base_url_setting: llm_base_url, api_key_setting: llm_api_key}
roles:
  fast:   {provider: cloud_a, model_setting: fast_model,   timeout_s: 8,  max_retries: 3, deadline_s: 45,
           max_tokens: 400, temperature: 0, budget_in: 2000}
  strong: {provider: cloud_a, model_setting: strong_model, timeout_s: 20, max_retries: 1, deadline_s: 50,
           max_tokens: 900, temperature: 0, budget_in: 6000}
fallback: {fast: [], strong: []}
spend: {cap_usd: 38, warn_ratio: 0.8, refresh_s: 60}
limits: {max_concurrency: 8, retry_on: [429], backoff_base_s: 1, jitter_max_s: 0.25}
cache: {ttl_hours_runtime: 24}
pricing:
  m-paid: {in: 1.0, out: 2.0}
"""

# Như _PAID_YAML nhưng vai trò `fast` có MỘT fallback mà model của nó KHÔNG có dòng giá.
_FALLBACK_NO_PRICE_YAML = _PAID_YAML.replace(
    "fallback: {fast: [], strong: []}", "fallback: {fast: [{provider: cloud_a, model: fb-khong-gia}], strong: []}"
)


@pytest.mark.asyncio
async def test_llm_probe_fallback_missing_price(store: type[FakeStore], tmp_path: Path) -> None:
    """Đột biến H8: `config/llm.yaml` thật có fallback RỖNG và bảng `llm_status` truyền `models` trực tiếp → quên đưa
    model fallback vào `llm_targets` thì không test nào bắt. Ở đây probe đọc `llm.yaml` có fallback thiếu giá: model
    chính đủ giá, nhưng đích fallback không có dòng `pricing` → `real:missing_pricing` (gateway thật sẽ từ chối khởi
    động, 3-Q26), không được báo `real:configured`, và không đọc tổng chi."""
    assert _FALLBACK_NO_PRICE_YAML != _PAID_YAML  # chuỗi thay thế phải khớp
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "llm.yaml").write_text(_FALLBACK_NO_PRICE_YAML, encoding="utf-8")
    settings = _settings(llm_backend="real", fast_model="m-paid", strong_model="m-paid", config_dir=cfg_dir)
    from app.llm.config import load_llm_config

    assert llm_targets(load_llm_config(cfg_dir / "llm.yaml"), settings) == ("m-paid", "fb-khong-gia", "m-paid")
    assert await _default_llm_probe(settings, _fake_app(main=object()))() == "real:missing_pricing"
    assert store.calls == 0


# ---- 5. Probe monitor: đúng role, không rơi về engines.main (kiểm thử 01/10 mục 7) ---------------


class FakeConn:
    def __init__(self, user: object) -> None:
        self._user = user

    async def execute(self, _: object) -> Any:
        return SimpleNamespace(scalar=lambda: self._user)


class FakeMonitorEngine:
    """Engine giả trả `current_user` định trước; `fail=True` → connect lỗi như DB chết."""

    def __init__(self, user: object = "app_monitor", fail: bool = False) -> None:
        self._user, self._fail = user, fail
        self.connects = 0

    def connect(self) -> Any:
        engine = self

        class Ctx:
            async def __aenter__(self) -> FakeConn:
                engine.connects += 1
                if engine._fail:
                    raise ConnectionError("không nối được")
                return FakeConn(engine._user)

            async def __aexit__(self, *_: object) -> None:
                return None

        return Ctx()


@pytest.mark.asyncio
async def test_monitor_probe_ok() -> None:
    engine = FakeMonitorEngine("app_monitor")
    probe = _default_monitor_probe(_fake_app(main=NeverEngine(), monitor=engine))
    assert await probe() == "ok"
    assert engine.connects == 1


@pytest.mark.asyncio
async def test_monitor_probe_not_configured_does_not_touch_main() -> None:
    """Thiếu DSN → `not_configured`; KHÔNG rơi về `engines.main` (bất biến 4.1 — `NeverEngine` chạm là đỏ)."""
    probe = _default_monitor_probe(_fake_app(main=NeverEngine(), monitor=None))
    assert await probe() == "not_configured"


@pytest.mark.asyncio
async def test_monitor_probe_wrong_role_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    """DSN đặt nhầm sang `app_rw` → `wrong_role` + ĐÚNG 1 dòng ERROR; log không chứa DSN."""
    engine = FakeMonitorEngine("app_rw")
    probe = _default_monitor_probe(_fake_app(main=NeverEngine(), monitor=engine))
    with caplog.at_level("ERROR", logger="app.main"):
        assert await probe() == "wrong_role"
    errors = [r.getMessage() for r in caplog.records if r.name == "app.main" and r.levelname == "ERROR"]
    assert errors == ["monitor DSN sai role: app_rw — M9 phải chạy bằng app_monitor"]
    assert "postgresql" not in errors[0] and "@" not in errors[0]


@pytest.mark.asyncio
async def test_monitor_probe_connect_error_propagates_to_down() -> None:
    """Lỗi kết nối KHÔNG bị probe nuốt — biên health (`_probe`) đổi thành `down` và log tên lớp."""
    engine = FakeMonitorEngine(fail=True)
    probe = _default_monitor_probe(_fake_app(main=NeverEngine(), monitor=engine))
    with pytest.raises(ConnectionError):
        await probe()


def test_default_probes_are_wired() -> None:
    """`create_app` gắn sẵn 2 probe (không đổi chữ ký `create_app` — test gán đè `app.state`)."""
    app = create_app(_settings(), health_checks={}, runtime=no_runtime)
    assert callable(app.state.llm_probe) and callable(app.state.monitor_probe)
