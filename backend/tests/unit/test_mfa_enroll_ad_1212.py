"""O2 (V17, 12/11): `mfa enroll` trên DB mới — người chưa có dòng `users` được đồng bộ từ AD (`AdUserSync` sẵn có) rồi mới enroll.

AD chỉ tra theo `user_id` (mock `/ad/users/{user_id}`), nên CLI nhận thêm `--user-id`; tên đăng nhập trong AD phải khớp username
gõ vào. Mọi đường lỗi báo rõ và KHÔNG ghi gì (không secret, không sự kiện `mfa_enrolled`).
"""

import base64
import secrets
from datetime import timedelta

import pytest
from app.auth.mfa import AdSource, MfaCipher, MfaError, enroll, main
from app.auth.models import UserSync
from app.auth.user_sync import AdUserSync, LockPolicy
from app.core.clock import FakeClock
from pydantic import SecretStr
from tests.fakes.auth import (
    EPOCH,
    FakeAdUser,
    FakeIdentityProvider,
    InMemoryAuthStore,
    RecordingSink,
)

KEY = b"k" * 32
LOCK = LockPolicy(failure_window=timedelta(minutes=15), max_failures=5, lockout=timedelta(minutes=15))


def _cipher() -> MfaCipher:
    return MfaCipher(SecretStr(base64.b64encode(secrets.token_bytes(32)).decode()))


def _env() -> tuple[InMemoryAuthStore, RecordingSink, FakeIdentityProvider, AdUserSync]:
    sink = RecordingSink(FakeClock(EPOCH))
    store = InMemoryAuthStore(sink)
    idp = FakeIdentityProvider()
    sync = AdUserSync(store=store, sink=sink, username_key=KEY, lock=LOCK)
    return store, sink, idp, sync


def _src(idp: FakeIdentityProvider, sync: AdUserSync, user_id: str) -> AdSource:
    return AdSource(user_id=user_id, identity=idp, sync=sync, now=EPOCH)


@pytest.mark.asyncio
async def test_db_moi_dong_bo_tu_ad_roi_enroll() -> None:
    store, sink, idp, sync = _env()
    assert await store.get_user_by_username("quan.tm") is None  # DB mới: chưa ai đăng nhập
    cipher = _cipher()
    result = await enroll(store, sink, cipher, username="quan.tm", by="ops", reason="demo",
                          from_ad=_src(idp, sync, "it_mgr01"))  # fmt: skip
    user = await store.get_user_by_username("quan.tm")
    assert user is not None and user.user_id == "it_mgr01" and user.role == "manager"
    assert user.mfa_secret_enc is not None and cipher.decrypt("it_mgr01", user.mfa_secret_enc) == result.secret
    [event] = sink.of("mfa_enrolled")
    assert event.user_id == "it_mgr01" and event.detail == {"by": "ops", "reason": "demo"}


@pytest.mark.asyncio
async def test_dong_bo_ca_chuoi_quan_ly() -> None:
    store, sink, idp, sync = _env()
    await enroll(store, sink, _cipher(), username="ha.lt", by="ops", reason="x", from_ad=_src(idp, sync, "l1_01"))
    user = await store.get_user("l1_01")
    assert user is not None and user.manager_id == "it_mgr01"
    assert await store.get_user("it_mgr01") is not None  # FK manager_id: sếp được upsert trước


async def _assert_nothing_written(store: InMemoryAuthStore, sink: RecordingSink) -> None:
    assert sink.of("mfa_enrolled") == []
    for uid in ("it_mgr01", "nv001", "ghost01"):
        row = await store.get_user(uid)
        assert row is None or row.mfa_secret_enc is None


@pytest.mark.asyncio
async def test_khong_co_trong_ad_bao_ro() -> None:
    store, sink, idp, sync = _env()
    with pytest.raises(MfaError, match="không có trong AD"):
        await enroll(store, sink, _cipher(), username="ma.ma", by="ops", reason="x", from_ad=_src(idp, sync, "ghost01"))
    assert await store.get_user("ghost01") is None
    await _assert_nothing_written(store, sink)


@pytest.mark.asyncio
async def test_user_id_thuoc_nguoi_khac_bi_tu_choi() -> None:
    store, sink, idp, sync = _env()
    with pytest.raises(MfaError, match="không thuộc tài khoản quan.tm"):
        await enroll(store, sink, _cipher(), username="quan.tm", by="ops", reason="x",
                     from_ad=_src(idp, sync, "nv001"))  # fmt: skip
    assert await store.get_user("nv001") is None  # không đồng bộ người khác
    await _assert_nothing_written(store, sink)


@pytest.mark.asyncio
async def test_ad_sap_bao_ro_khong_ghi() -> None:
    store, sink, idp, sync = _env()
    idp.down = True
    with pytest.raises(MfaError, match="AD không trả lời"):
        await enroll(store, sink, _cipher(), username="quan.tm", by="ops", reason="x",
                     from_ad=_src(idp, sync, "it_mgr01"))  # fmt: skip
    await _assert_nothing_written(store, sink)


@pytest.mark.asyncio
async def test_nhom_ad_khong_ra_role_bao_ro() -> None:
    store, sink, idp, sync = _env()
    idp.set(FakeAdUser("ext01", "khach.x", ["Guests"]))
    with pytest.raises(MfaError, match="role"):
        await enroll(store, sink, _cipher(), username="khach.x", by="ops", reason="x", from_ad=_src(idp, sync, "ext01"))
    assert await store.get_user("ext01") is None


@pytest.mark.asyncio
async def test_tai_khoan_da_nghi_khong_enroll() -> None:
    store, sink, idp, sync = _env()
    with pytest.raises(MfaError, match="không còn hoạt động"):
        await enroll(store, sink, _cipher(), username="em.lv", by="ops", reason="x", from_ad=_src(idp, sync, "nv006"))
    assert sink.of("mfa_enrolled") == []


@pytest.mark.asyncio
async def test_thieu_user_id_goi_y_cach_dong_bo() -> None:
    store, sink, _, _ = _env()
    with pytest.raises(MfaError, match="--user-id"):
        await enroll(store, sink, _cipher(), username="quan.tm", by="ops", reason="x")
    assert sink.events == []


@pytest.mark.asyncio
async def test_da_co_dong_nhung_user_id_lech_bi_tu_choi() -> None:
    store, sink, idp, sync = _env()
    await store.upsert_user(UserSync("it_mgr01", "quan.tm", "Q", "manager", "it", None, "active", None, False, EPOCH))
    with pytest.raises(MfaError, match="không khớp"):
        await enroll(store, sink, _cipher(), username="quan.tm", by="ops", reason="x", from_ad=_src(idp, sync, "nv001"))
    user = await store.get_user("it_mgr01")
    assert user is not None and user.mfa_secret_enc is None


@pytest.mark.asyncio
async def test_da_co_dong_khop_user_id_khong_goi_ad() -> None:
    store, sink, idp, sync = _env()
    await store.upsert_user(UserSync("it_mgr01", "quan.tm", "Q", "manager", "it", None, "active", None, False, EPOCH))
    idp.down = True  # đã có dòng → không cần AD
    await enroll(store, sink, _cipher(), username="quan.tm", by="ops", reason="x", from_ad=_src(idp, sync, "it_mgr01"))
    assert len(sink.of("mfa_enrolled")) == 1


def test_cli_user_id_thieu_token_ad_bao_ro(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MFA_ENC_KEY", base64.b64encode(secrets.token_bytes(32)).decode())
    monkeypatch.delenv("SVC_AGENT_TOKEN", raising=False)
    assert main(["enroll", "quan.tm", "--user-id", "it_mgr01", "--by", "ops", "--reason", "x"]) == 2
    assert "SVC_AGENT_TOKEN" in capsys.readouterr().err
