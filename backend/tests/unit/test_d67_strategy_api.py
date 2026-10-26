"""D-67 P1.3, P1.5, P1.6 — chiến lược M5 lúc vận hành qua HTTP thật của app (`desk_env`, graph giả, `MemoryStrategyStore`).

- `GET /api/admin/strategy` (`policy:read`), `PUT` (`policy:edit` + đăng nhập lại ≤ `reauth_minutes`), `GET …/history`: hình dạng phẳng
  (ĐP chốt 26/10), 401/403/422/409/reauth, ranh giới `reason` 9/10/500/501 SAU khi cắt khoảng trắng, `strategy_from`, audit
  `policy_saved {kind: m5_strategy, from, to}`, `reason` qua privacy guard.
- Chụp lên ticket lúc tạo: chiến lược hiện hành của DB, `source` real/sim (X-Sim-Run chỉ dev/test), EVAL_MODE env thắng + `source=eval`,
  giá trị DB lạ → `hybrid` + log cảnh báo. B12 phòng thủ lớp hai (chiến lược ngoài tập cho phép → `hybrid`). Ticket con kế thừa.

Người: quan.tm = it_mgr01 (manager, MFA — đăng ký trong test như `auth_helpers.manager_token`), an.nv = nv001 (employee), ha.lt = l1_01.
"""

import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pyotp
import pytest
from app.api import strategy as strategy_api
from app.auth.mfa import MfaCipher, enroll
from app.db.m5_strategy import StrategyChange
from app.domain.states import S_ASSESSING
from app.graph.nodes import b12_assess
from tests.fakes.auth import DEMO_PASSWORD
from tests.fakes.desk import MASK, SECRET, DeskEnv, desk_env
from tests.unit.test_b12_llm import _no_match, _node, _rule_match

pytestmark = pytest.mark.asyncio

ROUTE, HISTORY = "/api/admin/strategy", "/api/admin/strategy/history"
SELECTABLE = ["rule_only", "hybrid", "hybrid_guarded"]
STATE_KEYS = {"strategy", "selectable", "llm_calibrated", "eval_mode", "changed_by", "changed_at", "reason"}
FORBIDDEN, REAUTH, SAME = {"detail": "forbidden"}, {"detail": "reauth_required"}, {"detail": "same_as_current"}
REASON = "chạy dữ liệu thử"  # 16 ký tự
MANAGER, MANAGER_ID = "quan.tm", "it_mgr01"


def _invalid(*fields: str) -> dict[str, Any]:
    return {"error": "invalid_request", "fields": list(fields)}


async def _manager(env: DeskEnv) -> dict[str, str]:
    """Manager bắt buộc MFA: lần đầu 401 (tạo dòng users), đăng ký MFA qua đúng hàm CLI, đăng nhập kèm OTP (secret giữ trên env)."""
    secret = getattr(env, "_mfa", None)
    if secret is None:
        assert (await env.login(MANAGER)).status_code == 401
        key = env.settings.mfa_enc_key
        assert key is not None
        secret = (await enroll(env.store, env.sink, MfaCipher(key), username=MANAGER, by="ops", reason="test")).secret
        object.__setattr__(env, "_mfa", secret)
    r = await env.client.post("/api/auth/login", json={"username": MANAGER, "password": DEMO_PASSWORD,
                                                       "otp": pyotp.TOTP(secret).at(env.clock.now())})  # fmt: skip
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def _put(env: DeskEnv, headers: dict[str, str] | None, **body: Any) -> Any:
    return await env.client.put(ROUTE, json=body, headers=headers or {})


# ---- GET ----------------------------------------------------------------------------------------------------------------


async def test_get_default_hybrid_flat_shape() -> None:
    """Chưa có dòng nào → `hybrid` + `changed_by/at`, `reason` null; đúng 7 khoá phẳng (không khối `current`)."""
    async with desk_env() as env:
        r = await env.client.get(ROUTE, headers=await _manager(env))
        assert r.status_code == 200
        assert r.json() == {"strategy": "hybrid", "selectable": SELECTABLE, "llm_calibrated": False, "eval_mode": False,
                            "changed_by": None, "changed_at": None, "reason": None}  # fmt: skip


async def test_get_llm_calibrated_follows_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """`llm_calibrated` = `m5.calibrator_version != null` của policy đang chạy."""
    monkeypatch.setattr(strategy_api, "get_policy", lambda: SimpleNamespace(m5=SimpleNamespace(calibrator_version="platt-x")))
    async with desk_env() as env:
        r = await env.client.get(ROUTE, headers=await _manager(env))
        assert r.json()["llm_calibrated"] is True


@pytest.mark.parametrize("path", [ROUTE, HISTORY])
async def test_read_401_and_403(path: str) -> None:
    async with desk_env() as env:
        assert (await env.client.get(path)).status_code == 401
        for user in ("an.nv", "ha.lt", "long.nh"):
            before = env.denied()
            r = await env.client.get(path, headers=await env.token(user))
            assert (r.status_code, r.json()) == (403, FORBIDDEN), user
            assert env.denied() == before + 1


# ---- PUT ----------------------------------------------------------------------------------------------------------------


async def test_put_ok_writes_row_audit_and_returns_state() -> None:
    async with desk_env() as env:
        mgr = await _manager(env)
        r = await _put(env, mgr, strategy="rule_only", reason=f"  {REASON}  ")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) == STATE_KEYS
        assert (body["strategy"], body["changed_by"], body["reason"]) == ("rule_only", MANAGER_ID, REASON)
        assert datetime.fromisoformat(body["changed_at"]) == env.clock.now()
        [row] = env.strategy.rows
        assert (row.strategy, row.strategy_from, row.changed_by, row.reason) == ("rule_only", "hybrid", MANAGER_ID, REASON)
        assert env.strategy.events == [{"event_type": "policy_saved", "user_id": MANAGER_ID,
                                        "detail": {"kind": "m5_strategy", "from": "hybrid", "to": "rule_only"}}]  # fmt: skip
        assert (await env.client.get(ROUTE, headers=mgr)).json() == body


@pytest.mark.parametrize(("length", "status"), [(9, 422), (10, 200), (500, 200), (501, 422)])
async def test_put_reason_length_after_strip(length: int, status: int) -> None:
    """`reason` 10–500 ký tự SAU khi cắt khoảng trắng (khoảng trắng hai đầu không tính)."""
    async with desk_env() as env:
        r = await _put(env, await _manager(env), strategy="hybrid_guarded", reason="   " + "a" * length + " \n ")
        assert r.status_code == status, r.text
        if status == 422:
            assert r.json() == _invalid("reason")
            assert env.strategy.rows == []
        else:
            assert env.strategy.rows[0].reason == "a" * length


@pytest.mark.parametrize("value", ["llm_only", "full_auto", "manual", "", "HYBRID", None])
async def test_put_strategy_outside_selectable_422(value: Any) -> None:
    async with desk_env() as env:
        r = await _put(env, await _manager(env), strategy=value, reason=REASON)
        assert (r.status_code, r.json()) == (422, _invalid("strategy"))
        assert env.strategy.rows == []


async def test_put_missing_fields_and_extra_key_422() -> None:
    async with desk_env() as env:
        mgr = await _manager(env)
        assert (await _put(env, mgr)).json() == _invalid("strategy", "reason")
        r = await _put(env, mgr, strategy="rule_only", reason=REASON, note="x")
        assert (r.status_code, r.json()) == (422, _invalid("<extra>"))


async def test_put_same_as_current_409() -> None:
    """Chưa có dòng → hiện hành `hybrid` → PUT `hybrid` = 409; sau PUT rule_only → PUT rule_only = 409. Không ghi dòng thừa."""
    async with desk_env() as env:
        mgr = await _manager(env)
        assert ((r := await _put(env, mgr, strategy="hybrid", reason=REASON)).status_code, r.json()) == (409, SAME)
        assert (await _put(env, mgr, strategy="rule_only", reason=REASON)).status_code == 200
        assert ((r := await _put(env, mgr, strategy="rule_only", reason=REASON)).status_code, r.json()) == (409, SAME)
        assert [c.strategy for c in env.strategy.rows] == ["rule_only"]


async def test_put_401_403_reauth() -> None:
    async with desk_env() as env:
        assert (await _put(env, None, strategy="rule_only", reason=REASON)).status_code == 401
        for user in ("an.nv", "ha.lt"):
            r = await _put(env, await env.token(user), strategy="rule_only", reason=REASON)
            assert (r.status_code, r.json()) == (403, FORBIDDEN)
        mgr = await _manager(env)
        env.clock.advance(timedelta(minutes=env.settings.reauth_minutes + 1))  # access token 15 phút còn hạn
        r = await _put(env, mgr, strategy="rule_only", reason=REASON)
        assert (r.status_code, r.json()) == (403, REAUTH)
        assert env.sink.of("permission_denied")[-1].detail == {"perm": "policy:edit", "reason": "reauth_required"}
        assert (await _put(env, await _manager(env), strategy="rule_only", reason=REASON)).status_code == 200
        assert len(env.strategy.rows) == 1


async def test_put_reason_goes_through_privacy_guard() -> None:
    """Bảng chỉ ghi thêm: `reason` có bí mật → lưu bản ĐÃ CHE + `privacy_secret_redacted {count}`."""
    async with desk_env() as env:
        r = await _put(env, await _manager(env), strategy="rule_only", reason=f"đổi để thử, mã {SECRET}")
        assert r.status_code == 200
        assert SECRET not in r.text and MASK in env.strategy.rows[0].reason
        [ev] = env.sink.of("privacy_secret_redacted")
        assert (ev.user_id, ev.route, ev.detail) == (MANAGER_ID, ROUTE, {"count": 1})


# ---- history ------------------------------------------------------------------------------------------------------------


async def test_history_newest_first_strategy_from_and_truncated() -> None:
    async with desk_env() as env:
        mgr = await _manager(env)
        for s in ("rule_only", "hybrid_guarded", "hybrid"):
            assert (await _put(env, mgr, strategy=s, reason=f"{REASON} {s}")).status_code == 200
            env.clock.advance(timedelta(minutes=1))
        r = await env.client.get(HISTORY, headers=mgr)
        assert r.status_code == 200
        body = r.json()
        assert body["truncated"] is False
        assert [(i["strategy_from"], i["strategy_to"]) for i in body["items"]] == [
            ("hybrid_guarded", "hybrid"), ("rule_only", "hybrid_guarded"), ("hybrid", "rule_only")]
        assert set(body["items"][0]) == {"changed_at", "changed_by", "strategy_from", "strategy_to", "reason"}
        assert body["items"][2]["reason"] == f"{REASON} rule_only"
        r2 = (await env.client.get(HISTORY, params={"limit": 2}, headers=mgr)).json()
        assert (len(r2["items"]), r2["truncated"]) == (2, True)


@pytest.mark.parametrize("limit", ["0", "201", "-1", "x"])
async def test_history_limit_out_of_range_422(limit: str) -> None:
    async with desk_env() as env:
        r = await env.client.get(HISTORY, params={"limit": limit}, headers=await _manager(env))
        assert (r.status_code, r.json()) == (422, _invalid("query.limit"))


async def test_history_limit_200_ok() -> None:
    async with desk_env() as env:
        assert (await env.client.get(HISTORY, params={"limit": 200}, headers=await _manager(env))).status_code == 200


# ---- chụp chiến lược lúc tạo ticket -------------------------------------------------------------------------------------


async def test_ticket_snapshots_current_strategy_at_creation() -> None:
    """Ticket tạo TRƯỚC khi đổi giữ `hybrid`; ticket tạo SAU nhận `rule_only` — chụp lúc tạo, không đọc lại."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        before = await env.create(an)
        assert (await _put(env, await _manager(env), strategy="rule_only", reason=REASON)).status_code == 200
        after = await env.create(an)
        assert (env.h.tickets.strategies[before], env.h.tickets.sources[before]) == ("hybrid", "real")
        assert (env.h.tickets.strategies[after], env.h.tickets.sources[after]) == ("rule_only", "real")
        assert await env.h.tickets.strategy_of(before) == "hybrid"


@pytest.mark.parametrize(("app_env", "source"), [("dev", "sim"), ("test", "sim"), ("staging", "real"), (None, "real")])
async def test_sim_header_only_in_dev_test(app_env: str | None, source: str) -> None:
    """`source='sim'` CHỈ khi có `X-Sim-Run` VÀ APP_ENV ∈ {dev, test}; ngoài dev/test header bị bỏ qua. Không header → real."""
    async with desk_env(app_env=app_env) as env:
        an = await env.token("an.nv")
        r = await env.client.post("/api/tickets", json={"text": "VPN không vào được"}, headers={**an, "X-Sim-Run": "1"})
        assert r.status_code == 202
        plain = await env.create(an)
        assert env.h.tickets.sources[r.json()["ticket_id"]] == source
        assert env.h.tickets.sources[plain] == "real"


async def test_eval_mode_env_wins_db_ignored() -> None:
    """EVAL_MODE: chiến lược = env (`STRATEGY`), DB bị bỏ qua (DB đang `rule_only`), `source='eval'` kể cả có X-Sim-Run."""
    async with desk_env(app_env="dev", eval_mode=True, strategy="llm_only") as env:
        env.strategy.rows.append(StrategyChange(1, "rule_only", "hybrid", MANAGER_ID, REASON, datetime(2026, 10, 1, tzinfo=UTC)))
        env.strategy.fail = None
        an = await env.token("an.nv")
        r = await env.client.post("/api/tickets", json={"text": "VPN không vào được"}, headers={**an, "X-Sim-Run": "1"})
        tid = r.json()["ticket_id"]
        assert (env.h.tickets.strategies[tid], env.h.tickets.sources[tid]) == ("llm_only", "eval")
        get = (await env.client.get(ROUTE, headers=await _manager(env))).json()
        assert (get["strategy"], get["eval_mode"]) == ("rule_only", True)  # GET báo giá trị DB + cờ eval_mode


async def test_eval_mode_does_not_read_db() -> None:
    """EVAL_MODE không chạm DB: store giả ném lỗi ở `current` mà tạo ticket vẫn 202."""
    async with desk_env(app_env="dev", eval_mode=True, strategy="hybrid_guarded") as env:
        env.strategy.fail = RuntimeError("không được đọc DB khi EVAL_MODE")
        tid = await env.create(await env.token("an.nv"))
        assert env.h.tickets.strategies[tid] == "hybrid_guarded"


async def test_unknown_db_value_falls_back_to_hybrid_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    """DB có giá trị ngoài RUNTIME_SELECTABLE (không được xảy ra) → KHÔNG chạy chiến lược đó: ticket `hybrid` + log cảnh báo."""
    caplog.set_level(logging.WARNING, logger="app.api.strategy")
    async with desk_env() as env:
        env.strategy.rows.append(StrategyChange(1, "llm_only", "hybrid", MANAGER_ID, REASON, datetime(2026, 10, 1, tzinfo=UTC)))
        tid = await env.create(await env.token("an.nv"))
        assert env.h.tickets.strategies[tid] == "hybrid"
        assert any("ngoài RUNTIME_SELECTABLE" in rec.getMessage() for rec in caplog.records)
        assert (await env.client.get(ROUTE, headers=await _manager(env))).json()["strategy"] == "hybrid"


# ---- B12 phòng thủ lớp hai + ticket con -----------------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "eval_mode"), [("llm_only", False), ("full_auto", False), ("manual", True), ("yolo", False)])
async def test_b12_defends_unknown_ticket_strategy(value: str, eval_mode: bool, caplog: pytest.LogCaptureFixture) -> None:
    """Ticket mang chiến lược ngoài tập cho phép của chế độ (vận hành: RUNTIME_SELECTABLE; EVAL: STRATEGIES) → B12 chạy `hybrid` +
    log cảnh báo — không chạy `llm_only`/`full_auto`/giá trị lạ, không E9."""
    caplog.set_level(logging.WARNING, logger=b12_assess.__name__)
    _, h, gw = await _node(_rule_match(), strategy=value, eval_mode=eval_mode)  # type: ignore[arg-type]
    [row] = h.audit.of("t1", "risk_decided")
    # luật R20 allow khớp: hybrid → quyết bằng luật, 0 lời gọi b14 (llm_only sẽ là `llm`, full_auto sẽ không có `decided_by`)
    assert (row["detail"]["strategy"], row["decided_by"], row["matched_rule_id"]) == ("hybrid", "rule", "R20")
    assert [c for c in gw.llm.calls if c.prompt_id.startswith("b14")] == []
    assert any("ngoài tập cho phép" in rec.getMessage() for rec in caplog.records)


async def test_b12_eval_mode_runs_ticket_eval_strategy() -> None:
    """EVAL_MODE: ticket `rule_only` (giá trị EVAL hợp lệ) chạy đúng `rule_only` — không bị kéo về `hybrid`."""
    out, h, _ = await _node(_no_match(), strategy="rule_only", eval_mode=True)
    [row] = h.audit.of("t1", "risk_decided")
    assert (row["detail"]["strategy"], out["status"]) == ("rule_only", S_ASSESSING)


async def test_child_ticket_inherits_parent_strategy_and_source() -> None:
    """Ticket con kế thừa `strategy`, `source` của cha (bản giả cùng ngữ nghĩa `INSERT … SELECT` của SQL — PG: test riêng)."""
    async with desk_env(app_env="dev") as env:
        assert (await _put(env, await _manager(env), strategy="hybrid_guarded", reason=REASON)).status_code == 200
        an = await env.token("an.nv")
        r = await env.client.post("/api/tickets", json={"text": "VPN không vào được"}, headers={**an, "X-Sim-Run": "1"})
        parent = r.json()["ticket_id"]
        await env.h.tickets.create_child(f"{parent}-1", parent_id=parent, redacted_request="ý 1", created_at=env.clock.now(),
                                         intents=2, intent_type="vpn")  # fmt: skip
        assert (env.h.tickets.strategies[f"{parent}-1"], env.h.tickets.sources[f"{parent}-1"]) == ("hybrid_guarded", "sim")


async def test_strategy_db_error_on_create_is_503_no_ticket() -> None:
    """Điểm lệch 4 (BE chốt): đọc chiến lược hiện hành lỗi lúc tạo ticket → 503 `strategy_unavailable` (khuôn `checkpoint_unavailable`),
    KHÔNG đoán `hybrid`, KHÔNG tạo ticket/lượt."""
    async with desk_env() as env:
        an = await env.token("an.nv")
        env.strategy.fail = RuntimeError("DB mất kết nối")
        before = set(env.h.tickets.rows)
        r = await env.client.post("/api/tickets", json={"text": "VPN không vào được"}, headers=an)
        assert (r.status_code, r.json()) == (503, {"detail": "strategy_unavailable"})
        assert set(env.h.tickets.rows) == before
