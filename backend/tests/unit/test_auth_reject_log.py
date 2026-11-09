"""Chặng V16 (việc treo gate4 g4-10, 401 chập chờn): mỗi đường 401 của `validate_access` ghi ĐÚNG MỘT dòng
`validate_access 401 reason=<mã cố định>[ revoke=<enum>] cached=<true|false>` — không token, không giá trị claim (sub, sid,
role, tv, jti, iat/exp tuyệt đối), không username/IP. Phản hồi 401 giữ nguyên (status, detail, header); token hợp lệ vẫn
được nhận. `TokenError` "iat ở tương lai"/"hết hạn" kèm số giây lệch — chỉ đổi chuỗi, điều kiện so sánh giữ nguyên.

Canary kiểm trên bản chụp LogRecord GỐC lúc emit ở logger `app` (trước khi bản ghi lan tới handler gốc) — không dựa vào
`RedactSecretsFilter`: dòng log phải sạch ngay từ đầu (P6 mục 7: không log Authorization/cookie).
"""

import asyncio
import logging
import re
import secrets
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from datetime import timedelta

import jwt
import pytest
from app.auth.service import AuthService
from app.auth.tokens import TokenError, TokenSigner
from app.core.clock import FakeClock
from pydantic import SecretStr
from tests.fakes.auth import EPOCH, InMemoryAuthStore
from tests.unit.auth_helpers import AuthEnv, auth_env

SERVICE_LOGGER = "app.auth.service"
LINE = re.compile(
    r"validate_access 401 reason=(?P<reason>\S.*?)"
    r"(?: revoke=(?P<revoke>logout|rotated|reuse_detected|user_disabled|admin|expired))? cached=(?P<cached>true|false)"
)


@dataclass(frozen=True)
class Shot:
    """Chụp LogRecord lúc emit — trước mọi filter của handler gốc (filter đó sửa `record.msg` tại chỗ)."""

    name: str
    levelno: int
    msg: str
    args: str
    text: str


class _Snapshot(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.shots: list[Shot] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.shots.append(Shot(record.name, record.levelno, str(record.msg), repr(record.args), record.getMessage()))


@pytest.fixture
def snap(caplog: pytest.LogCaptureFixture) -> Iterator[_Snapshot]:
    caplog.set_level(logging.DEBUG, logger="app")  # đủ cả dòng DEBUG — canary soát mọi mức
    handler = _Snapshot()
    app_logger = logging.getLogger("app")
    app_logger.addHandler(handler)
    try:
        yield handler
    finally:
        app_logger.removeHandler(handler)


def _rejects(snap: _Snapshot) -> list[Shot]:
    return [s for s in snap.shots if s.name == SERVICE_LOGGER and s.text.startswith("validate_access 401")]


def _sid(token: str) -> str:
    return str(jwt.decode(token, options={"verify_signature": False})["sid"])


def _auth(env: AuthEnv) -> AuthService:
    auth = env.app.state.auth
    assert isinstance(auth, AuthService)
    return auth


def _store(env: AuthEnv) -> InMemoryAuthStore:
    assert isinstance(env.store, InMemoryAuthStore)
    return env.store


def _key(env: AuthEnv) -> SecretStr:
    key = env.settings.jwt_signing_key
    assert key is not None
    return key


@dataclass(frozen=True)
class Case:
    """Kết quả dựng một ca: token trình lên `/api/auth/me` + giá trị canary (không được lọt vào log)."""

    token: str
    canaries: tuple[str, ...]


def _base(env: AuthEnv) -> tuple[str, str]:
    token = env.token("an.nv")
    return token, _sid(token)


def _canaries(token: str, sid: str, *extra: str) -> tuple[str, ...]:
    return (token, sid, "nv001", "an.nv", *extra)


# ---- dựng từng ca (mỗi hàm trả token + canary; KHÔNG gọi /me trước, trừ ca cần cache) -----------------------------------------


def _bad_signature(env: AuthEnv) -> Case:
    token, sid = _base(env)
    other = TokenSigner(SecretStr(secrets.token_urlsafe(32)), timedelta(minutes=15), env.clock)
    forged = other.issue(user_id="nv001", role="employee", session_id=sid, token_version=0)
    return Case(forged, _canaries(token, sid, forged))


def _not_jwt(env: AuthEnv) -> Case:
    token, sid = _base(env)
    return Case("khong-phai-jwt-canary", _canaries(token, sid, "khong-phai-jwt-canary"))


def _iat_future(env: AuthEnv) -> Case:
    token, sid = _base(env)
    ahead = TokenSigner(_key(env), timedelta(minutes=15), FakeClock(env.clock.now() + timedelta(seconds=2)))
    future = ahead.issue(user_id="nv001", role="employee", session_id=sid, token_version=0)
    return Case(future, _canaries(token, sid, future))


def _expired(env: AuthEnv) -> Case:
    token, sid = _base(env)
    env.clock.advance(timedelta(minutes=15, seconds=12.3))
    return Case(token, _canaries(token, sid))


def _session_missing(env: AuthEnv) -> Case:
    token, sid = _base(env)
    ghost = _auth(env).signer.issue(user_id="nv001", role="employee", session_id="phien-ma-canary", token_version=0)
    return Case(ghost, _canaries(token, sid, ghost, "phien-ma-canary"))


def _user_missing(env: AuthEnv) -> Case:
    token, sid = _base(env)
    ghost = _auth(env).signer.issue(user_id="user-ma-canary", role="employee", session_id=sid, token_version=0)
    return Case(ghost, _canaries(token, sid, ghost, "user-ma-canary"))


def _revoked_logout(env: AuthEnv) -> Case:
    token, sid = _base(env)
    assert env.client.post("/api/auth/logout", headers=env.bearer(token)).status_code == 204  # logout bỏ phiên khỏi cache
    return Case(token, _canaries(token, sid))


def _revoked_admin(env: AuthEnv) -> Case:
    token, sid = _base(env)
    asyncio.run(_store(env).revoke_user_sessions("nv001", "admin", env.clock.now()))
    return Case(token, _canaries(token, sid))


def _session_expired(env: AuthEnv) -> Case:
    token, sid = _base(env)
    store = _store(env)
    store.sessions[sid] = replace(store.sessions[sid], expires_at=env.clock.now())  # phiên hết hạn, access token còn hạn
    return Case(token, _canaries(token, sid))


def _sub_mismatch(env: AuthEnv) -> Case:
    token, sid = _base(env)
    env.token("ha.lt")  # tạo dòng users l1_01
    other = _auth(env).signer.issue(user_id="l1_01", role="employee", session_id=sid, token_version=0)
    return Case(other, _canaries(token, sid, other, "l1_01", "ha.lt"))


def _tv_mismatch_db(env: AuthEnv) -> Case:
    token, sid = _base(env)
    asyncio.run(_store(env).bump_token_version("nv001"))
    env.clock.advance(timedelta(seconds=30))
    return Case(token, _canaries(token, sid))


def _tv_mismatch_cached(env: AuthEnv) -> Case:
    token, sid = _base(env)
    assert env.client.get("/api/auth/me", headers=env.bearer(token)).status_code == 200  # nạp cache theo sid
    newer = _auth(env).signer.issue(user_id="nv001", role="employee", session_id=sid, token_version=1)
    return Case(newer, _canaries(token, sid, newer))


def _role_mismatch(env: AuthEnv) -> Case:
    token, sid = _base(env)
    store = _store(env)
    store.users["nv001"] = replace(store.users["nv001"], role="l2")
    env.clock.advance(timedelta(seconds=30))
    return Case(token, _canaries(token, sid))


def _user_inactive(env: AuthEnv) -> Case:
    token, sid = _base(env)
    store = _store(env)
    store.users["nv001"] = replace(store.users["nv001"], employment_status="terminated")
    env.clock.advance(timedelta(seconds=30))
    return Case(token, _canaries(token, sid))


W, I, D = logging.WARNING, logging.INFO, logging.DEBUG
# (ca, mã lý do đầy đủ, revoke, mức, cached)
CASES: list[tuple[Callable[[AuthEnv], Case], str, str | None, int, str]] = [
    (_bad_signature, "token_invalid:InvalidSignatureError", None, W, "false"),
    (_not_jwt, "token_invalid:DecodeError", None, W, "false"),
    (_iat_future, "token_invalid:iat ở tương lai (+2.000s)", None, W, "false"),
    (_expired, "token_invalid:hết hạn (-12.300s)", None, I, "false"),  # duyệt V16: INFO — giả thuyết "giờ nhảy tới"
    (_session_missing, "session_missing", None, W, "false"),
    (_user_missing, "user_missing", None, W, "false"),
    (_revoked_logout, "session_revoked", "logout", D, "false"),
    (_revoked_admin, "session_revoked", "admin", I, "false"),
    (_session_expired, "session_expired", None, I, "false"),
    (_sub_mismatch, "sub_mismatch", None, W, "false"),
    (_tv_mismatch_db, "tv_mismatch", None, W, "false"),
    (_tv_mismatch_cached, "tv_mismatch", None, W, "true"),
    (_role_mismatch, "role_mismatch", None, W, "false"),
    (_user_inactive, "user_inactive", None, I, "false"),
]


@pytest.mark.parametrize(
    ("build", "reason", "revoke", "level", "cached"), CASES, ids=[c[0].__name__.lstrip("_") for c in CASES]
)
def test_v16_each_reject_path_logs_exactly_one_reason_line(
    snap: _Snapshot, build: Callable[[AuthEnv], Case], reason: str, revoke: str | None, level: int, cached: str
) -> None:
    with auth_env() as env:
        case = build(env)
        snap.shots.clear()
        r = env.client.get("/api/auth/me", headers=env.bearer(case.token))

    # 401 giữ nguyên: status, thân, header
    assert (r.status_code, r.json(), r.headers.get("www-authenticate")) == (401, {"detail": "unauthorized"}, "Bearer")

    [line] = _rejects(snap)  # đúng MỘT dòng
    m = LINE.fullmatch(line.text)
    assert m, line.text  # fullmatch: ngoài mã + revoke + cached không có gì khác
    assert (m["reason"], m["revoke"], m["cached"], line.levelno) == (reason, revoke, cached, level)

    for shot in snap.shots:  # canary: mọi dòng của `app.*` trong lời gọi, trên bản ghi gốc (msg, args, đã format)
        for value in case.canaries:
            assert value not in shot.msg and value not in shot.args and value not in shot.text, (value, shot)


def test_v16_valid_token_still_accepted_without_reject_line(snap: _Snapshot) -> None:
    with auth_env() as env:
        token = env.token("an.nv")
        snap.shots.clear()
        first = env.client.get("/api/auth/me", headers=env.bearer(token))  # đọc DB
        second = env.client.get("/api/auth/me", headers=env.bearer(token))  # từ cache
    assert first.status_code == second.status_code == 200
    assert first.json()["user_id"] == "nv001"
    assert _rejects(snap) == []


# ---- tokens.py: chỉ chuỗi thông điệp đổi (kèm số giây lệch), điều kiện giữ nguyên -------------------------------------------------

KEY = SecretStr(secrets.token_urlsafe(32))


def _signer(clock: FakeClock) -> TokenSigner:
    return TokenSigner(KEY, timedelta(minutes=15), clock)


def test_v16_iat_future_message_carries_skew_seconds() -> None:
    token = _signer(FakeClock(EPOCH + timedelta(seconds=1))).issue(
        user_id="nv001", role="employee", session_id="s1", token_version=0
    )
    with pytest.raises(TokenError) as e:
        _signer(FakeClock(EPOCH + timedelta(seconds=0.266))).verify(token)
    assert str(e.value) == "iat ở tương lai (+0.734s)"


def test_v16_expired_message_carries_seconds_past_exp() -> None:
    clock = FakeClock(EPOCH)
    signer = _signer(clock)
    token = signer.issue(user_id="nv001", role="employee", session_id="s1", token_version=0)
    clock.advance(timedelta(minutes=15, seconds=12.3))
    with pytest.raises(TokenError) as e:
        signer.verify(token)
    assert str(e.value) == "hết hạn (-12.300s)"


def test_v16_time_conditions_unchanged_at_boundaries() -> None:
    """iat == now → nhận (không thêm lệch giờ cho phép); exp == now → từ chối; exp - 1 µs → nhận."""
    clock = FakeClock(EPOCH)
    signer = _signer(clock)
    token = signer.issue(user_id="nv001", role="employee", session_id="s1", token_version=0)
    assert signer.verify(token).sid == "s1"  # iat == now
    clock.advance(timedelta(minutes=15) - timedelta(microseconds=1))
    assert signer.verify(token).sid == "s1"
    clock.advance(timedelta(microseconds=1))
    with pytest.raises(TokenError, match=r"^hết hạn \("):
        signer.verify(token)
    early = _signer(FakeClock(EPOCH - timedelta(microseconds=1)))
    with pytest.raises(TokenError, match=r"^iat ở tương lai \(\+"):
        early.verify(token)  # iat lớn hơn now 1 µs → từ chối, như cũ


@pytest.mark.parametrize(("iat", "exp", "message"), [
    (10**400, 10**400 + 900, "iat ở tương lai (lệch ngoài miền float)"),
    (0, -(10**400), "hết hạn (lệch ngoài miền float)"),
], ids=["iat-qua-lon", "exp-am-qua-lon"])  # fmt: skip
def test_v16_skew_overflow_still_token_error(iat: int, exp: int, message: str) -> None:
    """Soát V16 NGHI-1: số nguyên khổng lồ (token ký đúng) — tính số giây lệch không được biến 401 thành 500."""
    claims = {"sub": "nv001", "role": "employee", "sid": "s1", "tv": 0, "iat": iat, "exp": exp, "jti": "j"}
    token = jwt.encode(claims, KEY.get_secret_value().encode("utf-8"), algorithm="HS256")
    with pytest.raises(TokenError) as e:
        _signer(FakeClock(EPOCH)).verify(token)
    assert str(e.value) == message
