"""I1 — `GET /api/admin/llm-status` (Trạng thái LLM, chỉ đọc, Trưởng BP IT) không cần DB, không cần stack.

- 401 không token; 403 cho L1, L2, nhân viên (+ `permission_denied`); 405 cho method khác; marker `("llm_status:read", None, False)`.
- Thiếu DSN monitor → 503 `monitor_unavailable`.
- Khoá API (chuỗi giả) KHÔNG BAO GIỜ xuất hiện trong body: không nguyên văn, không mã băm, không tiền tố/đuôi, không độ dài.
- Chi tiêu / tỉ lệ / ngưỡng cảnh báo đúng trên dữ liệu tự dựng; ngưỡng `warn` và `warn_percent` theo `warn_ratio` của cấu hình.
- Trung bình theo ticket, cửa sổ 24 giờ, model theo backend, KB (ready / missing / unknown), chỉ-SELECT.

SQL thật kiểm ở `tests/integration/test_llm_status_api_pg.py`; ở đây `read_snapshot` và `llm_usage` là bản giả.
"""

import base64
import hashlib
import json
import re
import shutil
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.api import llm_status as api
from app.main import create_app
from app.monitor.queries import llm_usage as usage_mod
from app.monitor.queries.llm_usage import LlmUsage
from tests.fakes.auth import EPOCH
from tests.unit.auth_helpers import AuthEnv, auth_env, auth_settings
from tests.unit.test_auth_route_scan import route_auth

URL = "/api/admin/llm-status"
REPO_CONFIG = Path(__file__).resolve().parents[3] / "config"
FAKE_KEY = "sk-FAKE-9f3a1c77d2e84b60a5c1-ZZtop"
TOP_KEYS = {"as_of", "backend", "models", "api_key_configured", "spend", "usage", "kb"}
SPEND_KEYS = {"total_usd", "cap_usd", "percent", "warn_percent", "status"}
USAGE_KEYS = {"calls_total", "calls_24h", "tickets_with_calls", "avg_cost_per_ticket_usd"}
KB_KEYS = {"alias", "collection", "status"}


class Source:
    """Thay `read_snapshot` + `llm_usage`: trả số tự dựng, nhớ `since` đã nhận."""

    def __init__(self) -> None:
        self.usage = LlmUsage(spent_usd=0.0, calls_total=0, calls_since=0, tickets=0)
        self.since: list[datetime] = []

    @asynccontextmanager
    async def snapshot(self, _engines: Any) -> AsyncIterator[None]:
        yield None

    async def llm_usage(self, _conn: Any, since: datetime) -> LlmUsage:
        self.since.append(since)
        return self.usage


@pytest.fixture
def src(monkeypatch: pytest.MonkeyPatch) -> Source:
    s = Source()
    monkeypatch.setattr(api, "read_snapshot", s.snapshot)
    monkeypatch.setattr(api, "llm_usage", s.llm_usage)
    return s


@pytest.fixture(autouse=True)
def _no_monitor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONITOR_DATABASE_URL", raising=False)


def _config(tmp_path: Path, warn_ratio: float | None = None) -> Path:
    """Bản chép CẢ thư mục `config/` (create_app đọc cả privacy_patterns…) vào thư mục tạm; đổi `spend.warn_ratio` của bản
    chép `llm.yaml` nếu cho. Không đụng config thật."""
    dest = tmp_path / "config"
    shutil.copytree(REPO_CONFIG, dest, dirs_exist_ok=True)
    if warn_ratio is not None:
        raw = yaml.safe_load((dest / "llm.yaml").read_text(encoding="utf-8"))
        raw["spend"]["warn_ratio"] = warn_ratio
        (dest / "llm.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return dest


def _cap(cfg_dir: Path) -> float:
    return float(yaml.safe_load((cfg_dir / "llm.yaml").read_text(encoding="utf-8"))["spend"]["cap_usd"])


@pytest.fixture
def cfg_dir(tmp_path: Path) -> Path:
    return _config(tmp_path)


@pytest.fixture
def env(cfg_dir: Path) -> Iterator[AuthEnv]:
    with auth_env(llm_backend="scripted", config_dir=cfg_dir) as e:
        e.app.state.kb_probe = _kb("kb_v12")
        yield e


def _kb(collection: str | None, boom: bool = False) -> Any:
    async def probe() -> str | None:
        if boom:
            raise OSError("qdrant down")
        return collection

    return probe


def _headers(env: AuthEnv) -> dict[str, str]:
    """`manager_token()` đăng ký MFA nên chỉ gọi được một lần mỗi env — nhớ token trên chính env."""
    if not hasattr(env, "_mgr_token"):
        env._mgr_token = env.manager_token()  # type: ignore[attr-defined]
    return env.bearer(env._mgr_token)  # type: ignore[attr-defined,no-any-return]


def _get(env: AuthEnv) -> tuple[int, Any]:
    r = env.client.get(URL, headers=_headers(env))
    return r.status_code, r.json()


def _ok(env: AuthEnv) -> dict[str, Any]:
    code, body = _get(env)
    assert code == 200, body
    return body  # type: ignore[no-any-return]


# ---- 401 / 403 / 405 / 503 -------------------------------------------------------------------------------------------


def test_no_token_401(env: AuthEnv) -> None:
    r = env.client.get(URL)
    assert (r.status_code, r.json()) == (401, {"detail": "unauthorized"})


@pytest.mark.parametrize("username", ["ha.lt", "long.nh", "an.nv"])
def test_other_roles_403(env: AuthEnv, src: Source, username: str) -> None:
    """L1, L2, nhân viên → 403 + đúng một `permission_denied`; không đọc DB."""
    before = len(env.sink.of("permission_denied"))
    r = env.client.get(URL, headers=env.bearer(env.token(username)))
    assert (r.status_code, r.json()) == (403, {"detail": "forbidden"})
    events = env.sink.of("permission_denied")[before:]
    assert [(e.route, e.detail.get("perm")) for e in events] == [(URL, "llm_status:read")]
    assert src.since == []


def test_route_marker_and_read_only_methods() -> None:
    app = create_app(auth_settings(), health_checks={})
    found = {c.path: (c.methods, c.requirements) for c in route_auth(app)}
    assert found[URL] == (frozenset({"GET"}), (("llm_status:read", None, False),))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_other_methods_405(env: AuthEnv, method: str) -> None:
    r = env.client.request(method, URL, headers=_headers(env))
    assert r.status_code == 405


def test_missing_monitor_dsn_503(env: AuthEnv) -> None:
    assert _get(env) == (503, {"detail": "monitor_unavailable"})


# ---- hình dạng + số liệu ---------------------------------------------------------------------------------------------


def test_exact_keys_and_scripted_defaults(env: AuthEnv, src: Source) -> None:
    src.usage = LlmUsage(spent_usd=9.5, calls_total=420, calls_since=37, tickets=19)
    body = _ok(env)
    assert set(body) == TOP_KEYS
    assert set(body["spend"]) == SPEND_KEYS
    assert set(body["usage"]) == USAGE_KEYS
    assert set(body["kb"]) == KB_KEYS
    assert body["backend"] == "scripted"
    assert body["models"] == {"fast": "scripted", "strong": "scripted"}
    assert body["api_key_configured"] is False
    assert body["as_of"] == EPOCH.isoformat().replace("+00:00", "Z")
    assert body["kb"] == {"alias": "kb_current", "collection": "kb_v12", "status": "ready"}


def test_spend_and_usage_numbers(env: AuthEnv, src: Source, cfg_dir: Path) -> None:
    cap = _cap(cfg_dir)
    src.usage = LlmUsage(spent_usd=cap / 4, calls_total=420, calls_since=37, tickets=20)
    body = _ok(env)
    assert body["spend"] == {
        "total_usd": cap / 4, "cap_usd": cap, "percent": 25.0, "warn_percent": 80.0, "status": "ok",
    }  # fmt: skip
    assert body["usage"] == {
        "calls_total": 420, "calls_24h": 37, "tickets_with_calls": 20, "avg_cost_per_ticket_usd": cap / 4 / 20,
    }  # fmt: skip


def test_avg_cost_null_without_tickets(env: AuthEnv, src: Source) -> None:
    src.usage = LlmUsage(spent_usd=0.0, calls_total=0, calls_since=0, tickets=0)
    body = _ok(env)
    assert body["usage"]["avg_cost_per_ticket_usd"] is None
    assert body["spend"]["percent"] == 0.0
    assert body["spend"]["status"] == "ok"


def test_calls_window_is_24h_before_now(env: AuthEnv, src: Source) -> None:
    _ok(env)
    assert src.since == [EPOCH - timedelta(hours=24)]


def test_spend_status_boundaries(env: AuthEnv, src: Source, cfg_dir: Path) -> None:
    """Mốc theo `cap × warn_ratio` và `cap` (so `>=`, như `llm/spend.py`)."""
    cap = _cap(cfg_dir)
    warn_at = cap * 0.8
    cases = [
        (0.0, "ok"), (warn_at - 0.01, "ok"), (warn_at, "warn"), (cap - 0.01, "warn"), (cap, "over"), (cap * 2, "over"),
    ]  # fmt: skip
    for spent, status in cases:
        src.usage = LlmUsage(spent_usd=spent, calls_total=1, calls_since=1, tickets=1)
        spend = _ok(env)["spend"]
        assert (spend["status"], spend["total_usd"]) == (status, spent), spent
        assert spend["percent"] == pytest.approx(spent / cap * 100)
    assert _ok(env)["spend"]["percent"] == pytest.approx(200.0)  # vượt trần: không cắt ở 100


@pytest.mark.parametrize("warn_ratio", [0.5, 0.9])
def test_warn_ratio_comes_from_config(tmp_path: Path, src: Source, warn_ratio: float) -> None:
    """Đổi `spend.warn_ratio` trong cấu hình → `warn_percent` và ngưỡng `warn` đổi theo (không cứng 80)."""
    cfg = _config(tmp_path, warn_ratio)
    cap = _cap(cfg)
    with auth_env(llm_backend="scripted", config_dir=cfg) as e:
        e.app.state.kb_probe = _kb("kb_v12")
        for spent, status in [(cap * warn_ratio - 0.01, "ok"), (cap * warn_ratio, "warn"), (cap, "over")]:
            src.usage = LlmUsage(spent_usd=spent, calls_total=1, calls_since=1, tickets=1)
            spend = _ok(e)["spend"]
            assert spend["warn_percent"] == pytest.approx(warn_ratio * 100), spent
            assert spend["status"] == status, (warn_ratio, spent)
    # cùng một số chi: 70% trần → 0,5 là `warn`, 0,9 là `ok` — chứng minh ngưỡng không cứng 80%
    src.usage = LlmUsage(spent_usd=cap * 0.7, calls_total=1, calls_since=1, tickets=1)
    with auth_env(llm_backend="scripted", config_dir=cfg) as e:
        e.app.state.kb_probe = _kb("kb_v12")
        assert _ok(e)["spend"]["status"] == ("warn" if warn_ratio == 0.5 else "ok")


# ---- backend / model / khoá ------------------------------------------------------------------------------------------


def test_real_backend_models_from_env(cfg_dir: Path, src: Source) -> None:
    with auth_env(llm_backend="real", config_dir=cfg_dir, fast_model="deepseek-flash", strong_model=None) as e:
        e.app.state.kb_probe = _kb("kb_v12")
        body = _ok(e)
    assert body["backend"] == "real"
    assert body["models"] == {"fast": "deepseek-flash", "strong": None}
    assert body["api_key_configured"] is False


@pytest.mark.parametrize(("backend", "key", "expected"), [
    ("scripted", None, False), ("scripted", "", False), ("scripted", FAKE_KEY, True),
    ("real", None, False), ("real", "", False), ("real", FAKE_KEY, True),
])  # fmt: skip
def test_api_key_configured_is_boolean_only(cfg_dir: Path, src: Source, backend: str, key: str | None, expected: bool) -> None:
    with auth_env(llm_backend=backend, config_dir=cfg_dir, llm_api_key=key, fast_model="a", strong_model="b") as e:
        e.app.state.kb_probe = _kb("kb_v12")
        body = _ok(e)
    assert body["api_key_configured"] is expected


def _variants(secret: str) -> set[str]:
    raw = secret.encode()
    out = {secret, secret.lower(), secret.upper(), secret[::-1], base64.b64encode(raw).decode(),
           base64.urlsafe_b64encode(raw).decode().rstrip("="), raw.hex()}  # fmt: skip
    for algo in ("md5", "sha1", "sha256", "sha512"):
        digest = hashlib.new(algo, raw).hexdigest()
        out |= {digest, digest[:8], digest[:12]}
    out |= {secret[:6], secret[:8], secret[-6:], secret[-4:], secret[3:12]}
    return {v for v in out if len(v) >= 4}


@pytest.mark.parametrize("backend", ["scripted", "real"])
def test_secret_never_in_body(cfg_dir: Path, src: Source, backend: str) -> None:
    src.usage = LlmUsage(spent_usd=1.25, calls_total=9, calls_since=3, tickets=2)
    with auth_env(llm_backend=backend, config_dir=cfg_dir, llm_api_key=FAKE_KEY, fast_model="a", strong_model="b",
                  llm_base_url="https://llm.example.invalid") as e:  # fmt: skip
        e.app.state.kb_probe = _kb("kb_v12")
        r = e.client.get(URL, headers=_headers(e))
        assert r.status_code == 200
        assert r.json()["api_key_configured"] is True
        text = r.text
        # mọi giá trị chuỗi/số được làm phẳng cũng không chứa biến thể nào của khoá
        flat = json.dumps(r.json(), ensure_ascii=False)
        for variant in _variants(FAKE_KEY):
            assert variant not in text and variant not in flat, variant
        assert "llm.example.invalid" not in text  # base_url cũng không lộ
        assert [k for k in r.json() if "key" in k] == ["api_key_configured"]
        assert "len" not in text and "length" not in text  # không có trường độ dài khoá


def test_response_model_forbids_unknown_fields() -> None:
    """Thêm trường (vd. `api_key_hint`) mà không đổi model → lỗi to, không lọt im lặng."""
    assert api.LlmStatus.model_config["extra"] == "forbid"
    assert set(api.LlmStatus.model_fields) == TOP_KEYS
    with pytest.raises(ValueError):
        api.Models.model_validate({"fast": "a", "strong": "b", "api_key": FAKE_KEY})


# ---- KB ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("probe", "expected"), [
    (_kb("kb_v12"), {"alias": "kb_current", "collection": "kb_v12", "status": "ready"}),
    (_kb(None), {"alias": "kb_current", "collection": None, "status": "missing"}),
    (_kb(None, boom=True), {"alias": "kb_current", "collection": None, "status": "unknown"}),
])  # fmt: skip
def test_kb_states(env: AuthEnv, src: Source, probe: Any, expected: dict[str, Any]) -> None:
    env.app.state.kb_probe = probe
    body = _ok(env)
    assert body["kb"] == expected


# ---- chỉ SELECT ---------------------------------------------------------------------------------------------------------


def test_usage_query_is_select_only() -> None:
    source = Path(usage_mod.__file__).read_text(encoding="utf-8")
    sql = " ".join(re.findall(r'"((?:SELECT|FROM|JOIN|WHERE)[^"]*)"', source)).upper()
    assert sql.startswith("SELECT") and "FROM LLM_CALLS" in sql
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT)\b", sql)


@pytest.mark.asyncio
async def test_usage_query_rejects_naive_since() -> None:
    conn: Any = None
    with pytest.raises(ValueError):
        await usage_mod.llm_usage(conn, datetime(2030, 1, 1))  # noqa: DTZ001 — cố ý naive


def test_config_copy_helper_does_not_touch_repo_config(tmp_path: Path) -> None:
    before = (REPO_CONFIG / "llm.yaml").read_bytes()
    _config(tmp_path, 0.5)
    assert (REPO_CONFIG / "llm.yaml").read_bytes() == before
