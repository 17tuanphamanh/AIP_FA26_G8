"""Đặt lại mật khẩu AD qua SMS (chặng mock-ad) — phía backend.

- Executor mang `expires_in_minutes`, `sent_to` (số ĐÃ CHE) của mock vào `outputs`; `ExecutionResult` và `result_text` lọc theo mẫu
  chặt (`sent_to` chỉ dạng đã che, phút 1–60) — sai dạng → bỏ khoá, câu dùng bản không số/phút, không lỗi.
- Câu kết quả nói đúng kênh: sms → "qua SMS tới số <đã che>, hiệu lực n phút, chỉ dùng một lần"; không bao giờ chứa mật khẩu.
- AD trả 403 `password_change_required` là TRẠNG THÁI (không phải AD sập): `/api/auth/login` → 403, không đếm lần sai, không phiên.
"""

import secrets
from datetime import timedelta
from typing import Any

import httpx
import pytest
import respx
from app.auth.ports import IdentityUnavailable, PasswordChangeRequired
from app.auth.service import GENERIC_LOGIN_ERROR
from app.core.clock import FakeClock
from app.domain.messages import result_text
from app.domain.ticket_state import ExecutionResult
from app.executor.plan_executor import PlanExecutor
from app.settings import Settings
from app.tools.adapters.ad_read import AdIdentityProvider
from app.tools.models import UserAccountIn
from app.tools.specs import READ_TIMEOUT_S
from app.tools.wiring import build_read_registry
from pydantic import SecretStr
from tests.fakes.auth import DEMO_PASSWORD, FakeAdUser, FakeIdentityProvider
from tests.fakes.executor import MemoryTxLog
from tests.unit._t24 import NOW, TZ, FakeWrites, action
from tests.unit.auth_helpers import AuthEnv, auth_env

CANARY = "Canary-Tmp-9f3Kq7"
SMS_REPLY = {"delivered_via": "sms", "must_change_at_next_login": True, "expires_in_minutes": 15, "sent_to": "0900***001"}
SMS_TEXT = ("Đã đặt lại mật khẩu tài khoản đăng nhập (AD) của bạn. Mật khẩu tạm đã gửi qua SMS tới số 0900***001, hiệu lực "
            "15 phút, chỉ dùng một lần; bạn sẽ được yêu cầu đổi mật khẩu khi đăng nhập. "
            "Bạn đăng nhập thử rồi xác nhận giúp mình nhé.")  # fmt: skip


class SmsWrites(FakeWrites):
    """Như `_t24.FakeWrites` nhưng `reset_password` trả phản hồi tuỳ chọn (mock kênh sms)."""

    def __init__(self, clock: FakeClock, txlog: MemoryTxLog, reply: dict[str, Any]) -> None:
        super().__init__(clock, txlog)
        self.reply = reply

    def handlers(self) -> dict[str, Any]:
        out = super().handlers()

        async def reset_password(a: UserAccountIn, timeout: float) -> object:
            return self._hit("reset_password", a, lambda: {"user_id": a.user_id, "account_type": a.account_type,
                                                            **self.reply})  # fmt: skip

        out["reset_password"] = reset_password
        return out


async def _execute(reply: dict[str, Any]) -> ExecutionResult:
    clock = FakeClock(NOW)
    txlog = MemoryTxLog()
    writes = SmsWrites(clock, txlog, reply)
    return await PlanExecutor(writes.registry(), txlog, clock, tz=TZ).execute("t1", "T1", action("reset_password"))


def _text(outputs: dict[str, str], account_type: str = "ad") -> str:
    act = action("reset_password", params={"account_type": account_type})
    return result_text(act, outputs, act.facts, requester_id="nv001")


# ---- executor → outputs → câu kết quả ----------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sms_reset_outputs_carry_masked_number_and_minutes() -> None:
    res = await _execute(SMS_REPLY)
    assert res.success
    assert res.outputs == {"delivered_via": "sms", "expires_in_minutes": "15", "sent_to": "0900***001"}
    assert _text(res.outputs) == SMS_TEXT


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("sent_to", "minutes"),
    [("0900***001; DROP", 0), ("abc", 61), ("0900000001", 600)],
    ids=["chuoi-la-0-phut", "chu-61-phut", "so-day-du-600-phut"],
)
async def test_bad_number_or_minutes_dropped_not_error(sent_to: str, minutes: int) -> None:
    res = await _execute({**SMS_REPLY, "sent_to": sent_to, "expires_in_minutes": minutes})
    assert res.success and res.outputs == {"delivered_via": "sms"}
    text = _text(res.outputs)
    assert sent_to not in text and "phút" not in text
    assert "qua SMS tới số điện thoại đã đăng ký, chỉ dùng một lần" in text


@pytest.mark.asyncio
async def test_full_number_dropped_minutes_kept() -> None:
    res = await _execute({**SMS_REPLY, "sent_to": "0900000001"})
    assert res.success and res.outputs == {"delivered_via": "sms", "expires_in_minutes": "15"}
    text = _text(res.outputs)
    assert "0900000001" not in text
    assert "qua SMS tới số điện thoại đã đăng ký, hiệu lực 15 phút, chỉ dùng một lần" in text


@pytest.mark.parametrize(
    ("key", "value", "kept"),
    [
        ("sent_to", "0900***001", True), ("sent_to", "028***123", True), ("sent_to", "0900000001", False),
        ("sent_to", "0900***0012", False), ("sent_to", "+84900***001", False), ("sent_to", "", False),
        ("expires_in_minutes", "1", True), ("expires_in_minutes", "15", True), ("expires_in_minutes", "60", True),
        ("expires_in_minutes", "0", False), ("expires_in_minutes", "61", False), ("expires_in_minutes", "15abc", False),
        ("expires_in_minutes", "015", False), ("expires_in_minutes", 15, False),
    ],
)  # fmt: skip
def test_output_patterns_strict(key: str, value: object, kept: bool) -> None:
    raw: dict[str, object] = {"delivered_via": "sms", key: value}  # giá trị không phải chuỗi cũng phải bị loại
    res = ExecutionResult.model_validate({
        "success": True, "steps_done": ["reset_password"], "failed_step": None, "rollback_status": "none_needed",
        "rollback_details": [], "action_plan_hash_matched": None, "handoff_note": None, "outputs": raw,
    })  # fmt: skip
    assert (key in res.outputs) is kept


@pytest.mark.parametrize(
    "outputs",
    [
        {"delivered_via": "sms", "sent_to": CANARY, "expires_in_minutes": "15"},
        {"delivered_via": "sms", "sent_to": "0900***001", "expires_in_minutes": CANARY},
        {"delivered_via": "sms", "temp_password": CANARY, "password": CANARY},
        {"delivered_via": CANARY},
    ],
    ids=["sent_to", "minutes", "khoa-la", "delivered_via"],
)
def test_result_text_never_contains_password(outputs: dict[str, str]) -> None:
    """`result_text` tự lọc lại (lớp thứ hai) — kể cả khi gọi thẳng với dict chưa qua `ExecutionResult`."""
    assert CANARY not in _text(outputs)


def test_sms_sentence_never_says_email_and_email_channel_is_attributed() -> None:
    sms = _text({"delivered_via": "sms", "sent_to": "0900***001", "expires_in_minutes": "15"})
    assert "email" not in sms.lower()
    email = _text({"delivered_via": "email"}, "email")
    assert email == ("Đã đặt lại mật khẩu tài khoản email của bạn. Hệ thống tài khoản xác nhận mật khẩu tạm được gửi qua "
                     "email; bạn cần đổi mật khẩu ở lần đăng nhập tới. Bạn đăng nhập thử rồi xác nhận giúp mình nhé.")  # fmt: skip
    assert "SMS" not in email


# ---- AdIdentityProvider: 403 từ AD --------------------------------------------------------------------------------------------

MOCK = "http://mock.test"


@pytest.fixture
def idp() -> AdIdentityProvider:
    settings = Settings(_env_file=None, mock_url=MOCK, svc_agent_token=SecretStr(secrets.token_urlsafe(32)))  # type: ignore[call-arg]
    registry, http = build_read_registry(settings, FakeClock())
    return AdIdentityProvider(http, registry, timeout=READ_TIMEOUT_S, unavailable=IdentityUnavailable,
                              password_change=PasswordChangeRequired)  # fmt: skip


@pytest.mark.asyncio
@respx.mock
async def test_403_password_change_required_is_a_state_not_outage(idp: AdIdentityProvider) -> None:
    route = respx.post(f"{MOCK}/ad/authenticate").mock(
        return_value=httpx.Response(403, json={"detail": "password_change_required"})
    )
    with pytest.raises(PasswordChangeRequired) as exc:
        await idp.authenticate("an.nv", CANARY)
    assert not isinstance(exc.value, IdentityUnavailable) and CANARY not in str(exc.value)
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_403_account_locked_is_wrong_login_other_403_is_outage(idp: AdIdentityProvider) -> None:
    respx.post(f"{MOCK}/ad/authenticate").mock(side_effect=[
        httpx.Response(403, json={"detail": "account_locked"}),
        httpx.Response(403, json={"detail": "khac"}),
        httpx.Response(403, text="<html>"),
    ])  # fmt: skip
    assert await idp.authenticate("mai.tt", DEMO_PASSWORD) is None
    for _ in range(2):
        with pytest.raises(IdentityUnavailable):
            await idp.authenticate("mai.tt", DEMO_PASSWORD)


# ---- /api/auth/login gặp mật khẩu tạm --------------------------------------------------------------------------------------


class ChangeRequiredIdp(FakeIdentityProvider):
    """AD giả: username trong `must_change` + mật khẩu đúng → `PasswordChangeRequired` (như mock sau reset SMS)."""

    def __init__(self) -> None:
        super().__init__()
        self.must_change: set[str] = set()

    async def authenticate(self, username: str, password: str) -> FakeAdUser | None:
        if username in self.must_change and password == self.password:
            self.authenticate_calls += 1
            raise PasswordChangeRequired("AD: cần đổi mật khẩu")
        return await super().authenticate(username, password)


def _env() -> Any:
    return auth_env(idp=ChangeRequiredIdp())


def _idp(env: AuthEnv) -> ChangeRequiredIdp:
    assert isinstance(env.idp, ChangeRequiredIdp)
    return env.idp


def test_login_403_no_session_no_failure_count() -> None:
    with _env() as env:
        assert env.login("an.nv").status_code == 200  # có dòng users
        before = len(env.store.sessions)
        _idp(env).must_change.add("an.nv")
        for _ in range(7):  # > ngưỡng khoá 5: nếu đếm là lần sai thì đã bị khoá
            r = env.login("an.nv", DEMO_PASSWORD)
            assert (r.status_code, r.json()) == (403, {"detail": "password_change_required"})
            assert r.headers.get("set-cookie") is None and "access_token" not in r.text
        assert len(env.store.sessions) == before
        types = [e.event_type for e in env.sink.events]
        assert types.count("login_success") == 1 and "login_failed" not in types and "account_locked" not in types
        denied = env.sink.of("permission_denied")
        assert len(denied) == 7 and {e.detail["reason"] for e in denied} == {"password_change_required"}
        assert {e.route for e in denied} == {"/api/auth/login"}
        assert all(DEMO_PASSWORD not in str(e) for e in env.sink.events)
        _idp(env).must_change.discard("an.nv")  # đã đổi mật khẩu ở cổng AD
        assert env.login("an.nv").status_code == 200


def test_wrong_password_still_generic_401_and_lock_still_applies() -> None:
    with _env() as env:
        _idp(env).must_change.add("an.nv")
        r = env.login("an.nv", "sai")
        assert (r.status_code, r.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
        for _ in range(4):
            env.login("an.nv", "sai")
        calls = _idp(env).authenticate_calls
        locked = env.login("an.nv", DEMO_PASSWORD)  # đủ 5 lần sai → khoá chặn TRƯỚC khi hỏi AD
        assert (locked.status_code, locked.json()) == (401, {"detail": GENERIC_LOGIN_ERROR})
        assert _idp(env).authenticate_calls == calls
        env.clock.advance(timedelta(minutes=10, seconds=1))
        assert env.login("an.nv", DEMO_PASSWORD).status_code == 403


def test_ip_range_limit_still_applies_before_ad() -> None:
    with auth_env(idp=ChangeRequiredIdp(), client_ip="198.51.100.20") as env:
        _idp(env).must_change.add("an.nv")
        for i in range(20):
            env.login(f"ghost{i}", "sai")
        assert env.login("an.nv", DEMO_PASSWORD).status_code == 429
