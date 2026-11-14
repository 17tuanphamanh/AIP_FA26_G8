"""D-97 (TA 14/11, cách 1) — trang quản trị nhân viên của AD giả lập (`app/console_admin.py`).

Đủ CRUD trừ xoá: xem danh sách, thêm (mật khẩu demo mặc định, quản trị viên không đặt / không xem mật khẩu), sửa, tắt / bật, mở
khoá. Kiểm cả hiệu lực với đường đăng nhập AD mà ServiceDesk AI dùng (`/ad/authenticate`, `/ad/users/{id}`), cổng dev + cờ,
và chặn form gửi từ trang khác (Origin / Referer).
"""

from collections.abc import Iterator

import pytest
from app.main import create_app
from app.security import ServiceTokens
from fastapi.testclient import TestClient
from tests.conftest import NOW
from tests.test_seed import DEMO_PASSWORD

BASE = "/console/nhan-vien"
SAME = {"Origin": "http://testserver"}
NEW = {"username": "minh.nt", "full_name": "Nguyễn Thị Minh", "title": "Kế toán viên", "department": "Finance",
       "role": "employee", "manager_id": "fin_head", "phone": "0900000099", "email": "minh.nt@demo-corp.local"}  # fmt: skip


@pytest.fixture(autouse=True)
def dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MOCK_CONSOLE_ENABLED", "1")


@pytest.fixture
def c(tokens: ServiceTokens) -> Iterator[TestClient]:
    with TestClient(create_app(tokens=tokens, now=lambda: NOW), follow_redirects=False) as client:
        yield client


def _post(c: TestClient, path: str, data: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> object:
    return c.post(path, data=data or {}, headers=SAME if headers is None else headers)


def _login(c: TestClient, agent: dict[str, str], username: str, password: str = DEMO_PASSWORD) -> int:
    return c.post("/ad/authenticate", json={"username": username, "password": password}, headers=agent).status_code


# ---- cổng --------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("env", "flag"), [("prod", "1"), ("dev", "0")])
def test_gate_404_outside_dev_or_flag_off(c: TestClient, monkeypatch: pytest.MonkeyPatch, env: str, flag: str) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("MOCK_CONSOLE_ENABLED", flag)
    assert c.get(BASE).status_code == 404
    assert c.post(f"{BASE}/them", data=NEW, headers=SAME).status_code == 404


def test_post_from_other_origin_rejected(c: TestClient) -> None:
    users = c.app.state.mock.users  # type: ignore[attr-defined]
    before = len(users)
    assert c.post(f"{BASE}/them", data=NEW, headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.post(f"{BASE}/them", data=NEW, headers={}).status_code == 403  # không Origin, không Referer
    assert c.post(f"{BASE}/nv007/tat", headers={"Referer": "http://evil.example/x"}).status_code == 403
    assert len(users) == before and users["nv007"].employment_status == "active"
    ok = c.post(f"{BASE}/nv007/tat", headers={"Referer": "http://testserver/console/nhan-vien/nv007"})
    assert ok.status_code == 303


# ---- xem ----------------------------------------------------------------------------------------------------------------


def test_list_shows_everyone_with_role_status_lock_and_links(c: TestClient) -> None:
    text = c.get(BASE).text
    assert "http-equiv=\"refresh\"" not in text  # trang quản trị không tự làm mới (đang gõ không mất chữ)
    for uid in ("it_mgr01", "nv001", "nv004", "nv007", "svc_backup"):
        assert f'href="/console/nhan-vien/{uid}"' in text
    assert "Trưởng bộ phận IT" in text and "IT Helpdesk L1" in text and "Tài khoản dịch vụ" in text
    assert "Đã tắt" in text  # nv004 bị vô hiệu hoá trong seed
    assert "email" in text  # nv007 đang khoá email
    assert "password_hash" not in text and "$argon2" not in text and DEMO_PASSWORD not in text


def test_index_links_admin_page(c: TestClient) -> None:
    assert f'href="{BASE}"' in c.get("/console").text


# ---- thêm ---------------------------------------------------------------------------------------------------------------


def test_create_employee_default_password_logs_in_via_ad(c: TestClient, agent: dict[str, str]) -> None:
    r = _post(c, f"{BASE}/them", NEW)
    assert r.status_code == 303  # type: ignore[attr-defined]
    assert r.headers["location"] == f"{BASE}/nv008?tb=tao"  # type: ignore[attr-defined]
    u = c.app.state.mock.users["nv008"]  # type: ignore[attr-defined]
    assert (u.username, u.groups, u.employment_status, u.manager_id) == ("minh.nt", ["IT-Users"], "active", "fin_head")
    assert u.password_hash.startswith("$argon2id$") and DEMO_PASSWORD not in u.password_hash
    assert not u.must_change_password
    assert _login(c, agent, "minh.nt") == 200  # đăng nhập được ngay bằng mật khẩu demo
    view = c.get("/ad/users/nv008", headers=agent).json()
    assert (view["username"], view["employment_status"], view["manager_id"]) == ("minh.nt", "active", "fin_head")
    page = c.get(f"{BASE}/nv008?tb=tao").text
    assert "Đã tạo tài khoản" in page and DEMO_PASSWORD not in page
    assert "Tạo nv008 (minh.nt, Nhân viên)" in c.get(BASE).text  # nhật ký thao tác


def test_create_form_has_no_password_field(c: TestClient) -> None:
    text = c.get(f"{BASE}/them").text
    assert "password" not in text.lower() and "mật khẩu</label>" not in text.lower()


def test_create_l1_gets_group(c: TestClient) -> None:
    _post(c, f"{BASE}/them", {**NEW, "role": "l1", "phone": ""})
    assert c.app.state.mock.users["nv008"].groups == ["IT-Users", "IT-L1"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"username": "an.nv"}, "đã có người dùng"),
        ({"username": "A"}, "Tên đăng nhập"),
        ({"username": "Có Dấu"}, "Tên đăng nhập"),
        ({"full_name": ""}, "Họ tên"),
        ({"department": ""}, "Phòng ban"),
        ({"role": "manager"}, "Vai trò"),
        ({"manager_id": "khong-co"}, "Người quản lý"),
        ({"phone": "12345"}, "Số điện thoại"),
        ({"phone": "0900000001"}, "thuộc người khác"),
        ({"email": "khong-hop-le"}, "Email"),
    ],
)  # fmt: skip
def test_create_invalid_400_no_user_added(c: TestClient, over: dict[str, str], message: str) -> None:
    users = c.app.state.mock.users  # type: ignore[attr-defined]
    before = set(users)
    r = _post(c, f"{BASE}/them", {**NEW, **over})
    assert r.status_code == 400  # type: ignore[attr-defined]
    assert message in r.text  # type: ignore[attr-defined]
    assert set(users) == before


# ---- sửa ----------------------------------------------------------------------------------------------------------------


def test_update_info_and_role_keeps_username_and_password(c: TestClient, agent: dict[str, str]) -> None:
    u = c.app.state.mock.users["nv007"]  # type: ignore[attr-defined]
    hash_before = u.password_hash
    form = {"username": "doi.ten", "full_name": "Phan Thu Giang (mới)", "title": "Trưởng nhóm nhân sự", "department": "HR",
            "role": "l2", "manager_id": "hr_head", "phone": "0900000007", "email": ""}  # fmt: skip
    r = _post(c, f"{BASE}/nv007/sua", form)
    assert r.status_code == 303  # type: ignore[attr-defined]
    assert (u.username, u.full_name, u.title, u.email) == ("giang.pt", "Phan Thu Giang (mới)", "Trưởng nhóm nhân sự", None)
    assert u.groups == ["IT-Users", "IT-L2"] and u.password_hash == hash_before
    assert _login(c, agent, "giang.pt") == 200


def test_update_manager_role_cannot_change(c: TestClient) -> None:
    u = c.app.state.mock.users["it_mgr01"]  # type: ignore[attr-defined]
    form = {"full_name": u.full_name, "title": u.title, "department": u.department, "role": "employee", "manager_id": "",
            "phone": u.phone, "email": u.email}  # fmt: skip
    assert _post(c, f"{BASE}/it_mgr01/sua", form).status_code == 303  # type: ignore[attr-defined]
    assert "IT-Manager" in u.groups


def test_update_invalid_400_unchanged(c: TestClient) -> None:
    u = c.app.state.mock.users["nv001"]  # type: ignore[attr-defined]
    before = (u.full_name, u.phone)
    form = {"full_name": "X", "title": "t", "department": "d", "role": "employee", "manager_id": "", "phone": "0900000002"}
    r = _post(c, f"{BASE}/nv001/sua", form)
    assert r.status_code == 400  # type: ignore[attr-defined]
    assert (u.full_name, u.phone) == before


def test_unknown_user_404(c: TestClient) -> None:
    assert c.get(f"{BASE}/khong-co").status_code == 404
    assert _post(c, f"{BASE}/khong-co/tat").status_code == 404  # type: ignore[attr-defined]


# ---- tắt / bật ----------------------------------------------------------------------------------------------------------


def test_disable_then_enable_visible_in_ad(c: TestClient, agent: dict[str, str]) -> None:
    """Tắt: AD trả `employment_status = disabled` (ServiceDesk AI từ chối đăng nhập ở bước 5 — xem backend auth/service).
    Bật lại: `active`. Không có nút xoá."""
    assert _post(c, f"{BASE}/nv001/tat").status_code == 303  # type: ignore[attr-defined]
    view = c.get("/ad/users/nv001", headers=agent).json()
    assert view["employment_status"] == "disabled"
    page = c.get(f"{BASE}/nv001").text
    assert "Bật lại tài khoản" in page and "Tắt tài khoản" not in page and "Xoá" not in page
    assert _post(c, f"{BASE}/nv001/tat").status_code == 409  # type: ignore[attr-defined]
    assert _post(c, f"{BASE}/nv001/bat").status_code == 303  # type: ignore[attr-defined]
    assert c.get("/ad/users/nv001", headers=agent).json()["employment_status"] == "active"
    assert _post(c, f"{BASE}/nv001/bat").status_code == 409  # type: ignore[attr-defined]


def test_terminated_cannot_be_enabled(c: TestClient) -> None:
    assert _post(c, f"{BASE}/nv006/bat").status_code == 409  # type: ignore[attr-defined]
    assert "Đã nghỉ việc" in c.get(f"{BASE}/nv006").text


# ---- mở khoá ------------------------------------------------------------------------------------------------------------


def test_unlock_locked_account(c: TestClient) -> None:
    u = c.app.state.mock.users["nv007"]  # type: ignore[attr-defined]
    assert u.accounts["email"].locked
    assert "Mở khoá" in c.get(f"{BASE}/nv007").text
    assert _post(c, f"{BASE}/nv007/mo-khoa", {"account_type": "email"}).status_code == 303  # type: ignore[attr-defined]
    assert not u.accounts["email"].locked and u.accounts["email"].lock_reason is None
    assert _post(c, f"{BASE}/nv007/mo-khoa", {"account_type": "email"}).status_code == 409  # type: ignore[attr-defined]
    assert _post(c, f"{BASE}/nv007/mo-khoa", {"account_type": "khong-co"}).status_code == 409  # type: ignore[attr-defined]


def test_seed_reset_drops_admin_changes(c: TestClient) -> None:
    _post(c, f"{BASE}/them", NEW)
    assert "nv008" in c.app.state.mock.users  # type: ignore[attr-defined]
    assert c.post("/_admin/reset").status_code == 200
    assert "nv008" not in c.app.state.mock.users  # type: ignore[attr-defined]
    assert "(chưa có)" in c.get(BASE).text


def test_list_has_search_box_and_add_button(c: TestClient) -> None:
    text = c.get(BASE).text
    assert 'data-loc="bang-nv"' in text and 'id="bang-nv"' in text  # ô tìm nhanh lọc ngay trên trang
    assert f'href="{BASE}/them"' in text
    assert 'class=on' in text and 'data-lam-moi="0"' in text  # tab đang mở, trang quản trị không tự làm mới


def test_detail_shows_lock_reason_in_vietnamese_and_confirm_on_disable(c: TestClient) -> None:
    text = c.get(f"{BASE}/nv007").text
    assert "nhập sai mật khẩu nhiều lần" in text
    assert 'data-hoi="Tắt tài khoản của Phan Thu Giang?' in text  # hỏi lại trước khi tắt
