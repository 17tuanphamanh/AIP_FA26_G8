"""Q1 (soát 12/11, agent 13 F1 — sửa (a)): `POST /api/auth/refresh` đồng bộ người dùng từ AD như lúc đăng nhập (`AdUserSync`).

- AD: nghỉ việc / khoá, không còn trong AD, nhóm không ra role → thu hồi mọi phiên của người đó, 401 (như đăng xuất). Không ghi
  `refresh_reuse_detected` (không phải dùng lại token).
- Role đổi trong AD → `AdUserSync` tăng `token_version` + thu hồi phiên (như đăng nhập) → 401, đăng nhập lại để nhận role mới.
- AD không trả lời → 503 `identity_unavailable`: KHÔNG cấp token mới (fail-closed), nhưng KHÔNG thu hồi phiên — AD trở lại thì
  refresh tiếp được (frontend coi 503 là lỗi tạm, không đăng xuất).
- Kiểm bảng `users` cục bộ trước như cũ (TC31).
"""

from dataclasses import replace
from datetime import timedelta

from tests.fakes.auth import InMemoryAuthStore
from tests.unit.auth_helpers import AuthEnv, auth_env

AN = "nv001"  # an.nv


def _ad(env: AuthEnv, user_id: str = AN, **changes: object) -> None:
    env.idp.set(replace(env.idp.users[user_id], **changes))  # type: ignore[arg-type]


def _mem(env: AuthEnv) -> InMemoryAuthStore:
    assert isinstance(env.store, InMemoryAuthStore)
    return env.store


def _all_revoked(env: AuthEnv, user_id: str = AN) -> bool:
    sessions = [s for s in _mem(env).sessions.values() if s.user_id == user_id]
    return bool(sessions) and all(s.revoked_at is not None for s in sessions)


def test_refresh_hop_le_van_200() -> None:
    with auth_env() as env:
        env.login("an.nv")
        env.clock.advance(timedelta(minutes=20))
        r = env.refresh()
        assert r.status_code == 200, r.text
        assert env.sink.of("token_refreshed")


def test_nghi_viec_sau_dang_nhap_refresh_401_thu_hoi_phien() -> None:
    with auth_env() as env:
        env.login("an.nv")
        _ad(env, employment_status="terminated")
        env.clock.advance(timedelta(minutes=20))  # access token 15 phút đã hết
        r = env.refresh()
        assert r.status_code == 401, r.text
        assert _all_revoked(env)
        assert env.sink.of("refresh_reuse_detected") == []
        assert _mem(env).users[AN].employment_status == "terminated"  # đã đồng bộ về
        assert env.refresh().status_code == 401  # cookie cũ không hồi lại được


def test_khong_con_trong_ad_refresh_401() -> None:
    with auth_env() as env:
        env.login("an.nv")
        del env.idp.users[AN]
        r = env.refresh()
        assert r.status_code == 401, r.text
        assert _all_revoked(env)


def test_nhom_ad_khong_ra_role_refresh_401() -> None:
    with auth_env() as env:
        env.login("an.nv")
        _ad(env, groups=["Guests"])
        r = env.refresh()
        assert r.status_code == 401, r.text
        assert _all_revoked(env)


def test_role_doi_trong_ad_refresh_401_khong_bao_dung_lai() -> None:
    with auth_env() as env:
        env.login("ha.lt")
        _ad(env, "l1_01", groups=["IT-Users", "IT-L2"])
        r = env.refresh()
        assert r.status_code == 401, r.text
        assert _all_revoked(env, "l1_01")
        assert env.sink.of("refresh_reuse_detected") == []
        assert _mem(env).users["l1_01"].role == "l2"
        assert env.login("ha.lt").status_code == 200  # đăng nhập lại → role mới


def test_ad_khong_tra_loi_503_giu_phien() -> None:
    with auth_env() as env:
        env.login("an.nv")
        env.idp.down = True
        r = env.refresh()
        assert r.status_code == 503, r.text
        assert r.json()["detail"] == "identity_unavailable"
        assert not _all_revoked(env)
        env.idp.down = False
        assert env.refresh().status_code == 200  # AD trở lại → refresh tiếp được, cùng cookie


def test_bang_users_cuc_bo_da_khoa_van_401_khong_hoi_ad() -> None:
    """TC31 giữ nguyên: dòng `users` cục bộ không còn active → 401 trước khi hỏi AD (AD tắt cũng không thành 503)."""
    with auth_env() as env:
        env.login("an.nv")
        store = _mem(env)
        store.users[AN] = replace(store.users[AN], employment_status="terminated")
        env.idp.down = True
        assert env.refresh().status_code == 401
