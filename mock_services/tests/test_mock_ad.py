"""Chặng mock-ad: đặt lại mật khẩu AD chạy trọn như ngoài đời + AD có email.

- e2e: reset SMS → mật khẩu cũ 401, mật khẩu tạm 403 `password_change_required` → đổi → mật khẩu mới 200; quá hạn → từ chối.
- Khoá AD chặn `/ad/authenticate` (403 `account_locked`); reset/unlock tài khoản disabled/terminated → 409 `account_disabled`;
  unlock khi không khoá → 409 `not_locked`.
- Email: seed.json chỉ @demo-corp.local; `seed.local.json` nạp đè lúc khởi động và `/_admin/reset`; dòng sai bị bỏ + cảnh báo
  với địa chỉ ĐÃ CHE.
- Cổng `/portal` (APP_ENV dev/test): HTML, không JS ngoài.
- Email báo chủ tài khoản chỉ vào hộp thư đi — không mở kết nối mạng nào.
"""

import json
import logging
import socket
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from app import ad
from app.main import create_app
from app.security import ServiceTokens
from app.seed_model import SeedData
from app.state import SEED_LOCAL_ENV, SEED_PATH, load_seed
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.conftest import NOW
from tests.test_reset_sms import CANARY, NEW_PASSWORD, MutableClock
from tests.test_seed import DEMO_PASSWORD

REAL = "chu.tai.khoan+anv@gmail.com"  # địa chỉ giả có dạng thật — chỉ để thử nạp đè và che log


@pytest.fixture
def clock() -> MutableClock:
    return MutableClock(NOW)


@pytest.fixture
def c(tokens: ServiceTokens, clock: MutableClock) -> Iterator[TestClient]:
    with TestClient(create_app(tokens=tokens, now=clock)) as client:
        yield client


@pytest.fixture
def temp(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(ad, "new_temp_password", lambda: CANARY)
    return CANARY


def _login(c: TestClient, agent: dict[str, str], username: str, password: str) -> Any:
    return c.post("/ad/authenticate", headers=agent, json={"username": username, "password": password})


def _post(c: TestClient, executor: dict[str, str], path: str, **body: Any) -> Any:
    return c.post(path, headers=executor, json=body)


# ---- e2e reset SMS ---------------------------------------------------------------------------------------------------------


def test_e2e_sms_reset_old_temp_change_new(
    c: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str
) -> None:
    assert _login(c, agent, "an.nv", DEMO_PASSWORD).status_code == 200
    reset = _post(c, executor, "/ad/users/nv001/reset-password", account_type="ad", channel="sms")
    assert reset.status_code == 200 and reset.json()["sent_to"] == "0900***001"
    assert _login(c, agent, "an.nv", DEMO_PASSWORD).status_code == 401
    required = _login(c, agent, "an.nv", temp)
    assert (required.status_code, required.json()) == (403, {"detail": "password_change_required"})
    changed = _post(c, executor, "/ad/change-password", username="an.nv", temp_password=temp, new_password=NEW_PASSWORD)
    assert changed.status_code == 200
    ok = _login(c, agent, "an.nv", NEW_PASSWORD)
    assert ok.status_code == 200 and ok.json()["user_id"] == "nv001"
    assert _login(c, agent, "an.nv", temp).status_code == 401


def test_e2e_temp_password_past_ttl_rejected(
    c: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str, clock: MutableClock
) -> None:
    _post(c, executor, "/ad/users/nv001/reset-password", channel="sms")
    clock.t = NOW + ad.TEMP_PASSWORD_TTL + timedelta(seconds=1)
    assert _login(c, agent, "an.nv", temp).status_code == 401
    late = _post(c, executor, "/ad/change-password", username="an.nv", temp_password=temp, new_password=NEW_PASSWORD)
    assert late.status_code == 401
    assert _login(c, agent, "an.nv", NEW_PASSWORD).status_code == 401


# ---- khoá / disabled --------------------------------------------------------------------------------------------------------


def test_locked_ad_account_blocks_authenticate(c: TestClient, agent: dict[str, str], executor: dict[str, str]) -> None:
    locked = _login(c, agent, "mai.tt", DEMO_PASSWORD)  # hr_head: seed khoá AD
    assert (locked.status_code, locked.json()) == (403, {"detail": "account_locked"})
    assert _login(c, agent, "mai.tt", "sai-mat-khau").status_code == 401  # sai mật khẩu không lộ trạng thái khoá
    assert _post(c, executor, "/ad/users/nv001/lock", account_type="ad").status_code == 200
    assert _login(c, agent, "an.nv", DEMO_PASSWORD).json() == {"detail": "account_locked"}
    unlock = _post(c, executor, "/ad/users/nv001/unlock", account_type="ad")
    assert unlock.status_code == 200 and unlock.json()["was_locked"] is True
    assert _login(c, agent, "an.nv", DEMO_PASSWORD).status_code == 200


def test_email_lock_does_not_block_ad_login(c: TestClient, agent: dict[str, str]) -> None:
    assert _login(c, agent, "giang.pt", DEMO_PASSWORD).status_code == 200  # nv007: khoá email, AD không khoá


def test_locked_account_with_temp_password_reports_locked_and_cannot_change(
    c: TestClient, executor: dict[str, str], agent: dict[str, str], temp: str
) -> None:
    _post(c, executor, "/ad/users/nv001/reset-password", channel="sms")
    _post(c, executor, "/ad/users/nv001/lock", account_type="ad")
    assert _login(c, agent, "an.nv", temp).json() == {"detail": "account_locked"}
    change = _post(c, executor, "/ad/change-password", username="an.nv", temp_password=temp, new_password=NEW_PASSWORD)
    assert (change.status_code, change.json()) == (403, {"detail": "account_locked"})
    _post(c, executor, "/ad/users/nv001/unlock", account_type="ad")
    assert _login(c, agent, "an.nv", temp).json() == {"detail": "password_change_required"}  # khoá không tiêu mật khẩu tạm


@pytest.mark.parametrize("channel", ["sms", "email"])
@pytest.mark.parametrize("user_id", ["nv004", "nv006"])  # disabled (ad enabled=false), terminated
def test_reset_disabled_or_terminated_409(c: TestClient, executor: dict[str, str], user_id: str, channel: str) -> None:
    r = _post(c, executor, f"/ad/users/{user_id}/reset-password", channel=channel)
    assert (r.status_code, r.json()) == (409, {"detail": "account_disabled"})
    assert c.get("/_admin/outbox").json() == []


def test_terminated_with_enabled_account_still_409(c: TestClient, executor: dict[str, str]) -> None:
    assert c.post("/_admin/users/nv001/status", json={"employment_status": "terminated"}).status_code == 200
    for path in ("/ad/users/nv001/reset-password", "/ad/users/nv001/unlock"):
        r = _post(c, executor, path, account_type="ad")
        assert (r.status_code, r.json()) == (409, {"detail": "account_disabled"})


def test_unlock_rules(c: TestClient, executor: dict[str, str]) -> None:
    not_locked = _post(c, executor, "/ad/users/nv001/unlock", account_type="ad")
    assert (not_locked.status_code, not_locked.json()) == (409, {"detail": "not_locked"})
    disabled = _post(c, executor, "/ad/users/nv004/unlock", account_type="ad")
    assert (disabled.status_code, disabled.json()) == (409, {"detail": "account_disabled"})
    ok = _post(c, executor, "/ad/users/nv007/unlock", account_type="email")
    assert ok.status_code == 200 and ok.json() == {"user_id": "nv007", "account_type": "email", "locked": False,
                                                   "was_locked": True}  # fmt: skip
    again = _post(c, executor, "/ad/users/nv007/unlock", account_type="email")
    assert again.json() == {"detail": "not_locked"}


# ---- email AD ---------------------------------------------------------------------------------------------------------------


def test_seed_emails_are_user_id_at_demo_domain() -> None:
    assert all(u.email == f"{u.user_id}@demo-corp.local" for u in load_seed().users)


def test_get_user_returns_email(c: TestClient, agent: dict[str, str]) -> None:
    assert c.get("/ad/users/nv001", headers=agent).json()["email"] == "nv001@demo-corp.local"


def _seed_with_email(tmp_path: Path, email: str) -> Path:
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    raw["users"][0]["email"] = email
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


@pytest.mark.parametrize("email", [REAL, "it_mgr01@demo-corp.local.evil.com", "IT_MGR01@DEMO-CORP.LOCAL"])
def test_seed_json_rejects_non_demo_domain_and_mock_refuses_start(
    tmp_path: Path, tokens: ServiceTokens, email: str
) -> None:
    path = _seed_with_email(tmp_path, email)
    with pytest.raises(ValidationError):
        load_seed(path)
    with pytest.raises(ValidationError):
        create_app(tokens=tokens, seed_path=path, now=lambda: NOW)


def test_seed_json_duplicate_email_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="email trùng"):
        load_seed(_seed_with_email(tmp_path, "l1_lead@demo-corp.local"))


def _write_local(path: Path, users: object) -> None:
    path.write_text(json.dumps({"users": users}), encoding="utf-8")


def test_seed_local_overrides_at_start_and_on_admin_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tokens: ServiceTokens, agent: dict[str, str]
) -> None:
    local = tmp_path / "seed.local.json"
    _write_local(local, {"nv001": {"email": REAL}})
    monkeypatch.setenv(SEED_LOCAL_ENV, str(local))
    with TestClient(create_app(tokens=tokens, now=lambda: NOW)) as c:
        assert c.get("/ad/users/nv001", headers=agent).json()["email"] == REAL
        assert c.get("/ad/users/nv002", headers=agent).json()["email"] == "nv002@demo-corp.local"
        _write_local(local, {"nv002": {"email": "khac.chu+binh@gmail.com"}})
        assert c.post("/_admin/reset").status_code == 200
        assert c.get("/ad/users/nv001", headers=agent).json()["email"] == "nv001@demo-corp.local"
        assert c.get("/ad/users/nv002", headers=agent).json()["email"] == "khac.chu+binh@gmail.com"
        local.unlink()
        c.post("/_admin/reset")
        assert c.get("/ad/users/nv002", headers=agent).json()["email"] == "nv002@demo-corp.local"


def test_seed_local_bad_rows_dropped_with_masked_warning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tokens: ServiceTokens, agent: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    local = tmp_path / "seed.local.json"
    _write_local(local, {
        "nv001": {"email": REAL},
        "nv002": {"email": "khong-phai-email"},
        "nv003": {"email": REAL.upper()},  # trùng nv001 (không phân biệt hoa thường)
        "nv005": {"email": "nv007@demo-corp.local"},  # trùng địa chỉ seed của nv007
        "ma_ao": {"email": "nguoi.la@gmail.com"},
        "nv007": "khong-phai-object",
    })  # fmt: skip
    monkeypatch.setenv(SEED_LOCAL_ENV, str(local))
    with caplog.at_level(logging.DEBUG), TestClient(create_app(tokens=tokens, now=lambda: NOW)) as c:
        emails = {u: c.get(f"/ad/users/{u}", headers=agent).json()["email"] for u in ("nv001", "nv002", "nv003", "nv005",
                                                                                      "nv007")}  # fmt: skip
    assert emails == {"nv001": REAL, "nv002": "nv002@demo-corp.local", "nv003": "nv003@demo-corp.local",
                      "nv005": "nv005@demo-corp.local", "nv007": "nv007@demo-corp.local"}  # fmt: skip
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 5
    log_text = caplog.text
    for address in (REAL, REAL.upper(), "khong-phai-email", "nguoi.la@gmail.com", "nv007@demo-corp.local"):
        assert address not in log_text
    assert "C***@G***" in log_text and "n***@d***" in log_text  # bản che của hai địa chỉ trùng


@pytest.mark.parametrize("content", ["{không phải json", "[]", '{"users": []}'])
def test_seed_local_broken_file_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tokens: ServiceTokens, agent: dict[str, str], content: str
) -> None:
    local = tmp_path / "seed.local.json"
    local.write_text(content, encoding="utf-8")
    monkeypatch.setenv(SEED_LOCAL_ENV, str(local))
    with TestClient(create_app(tokens=tokens, now=lambda: NOW)) as c:
        assert c.get("/ad/users/nv001", headers=agent).json()["email"] == "nv001@demo-corp.local"


def test_example_file_is_valid_and_uses_fake_addresses() -> None:
    example = json.loads(SEED_PATH.with_name("seed.local.example.json").read_text(encoding="utf-8"))
    seed_ids = {u.user_id for u in SeedData.model_validate(json.loads(SEED_PATH.read_text(encoding="utf-8"))).users}
    assert set(example["users"]) <= seed_ids
    assert all(v["email"].endswith("@example.com") for v in example["users"].values())  # RFC 2606: miền không có thật


# ---- email báo chủ tài khoản: chỉ hộp thư đi ---------------------------------------------------------------------------------


def test_notice_email_only_in_outbox_no_network(
    c: TestClient, executor: dict[str, str], temp: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_network(*_: object, **__: object) -> None:
        raise AssertionError("mock không được mở kết nối mạng khi đặt lại mật khẩu")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert _post(c, executor, "/ad/users/nv001/reset-password", channel="sms").status_code == 200
    rows = c.get("/_admin/outbox").json()
    assert [(r["channel"], r["to"]) for r in rows] == [("sms", "0900000001"), ("email", "n***@d***")]
    assert temp not in rows[1]["body"]


# ---- cổng /portal -----------------------------------------------------------------------------------------------------------


@pytest.fixture
def portal(monkeypatch: pytest.MonkeyPatch, c: TestClient) -> TestClient:
    monkeypatch.setenv("APP_ENV", "dev")
    return c


def _portal_login(c: TestClient, username: str, password: str) -> Any:
    return c.post("/portal/login", data={"username": username, "password": password})


def _portal_change(c: TestClient, temp_password: str, new: str = NEW_PASSWORD, confirm: str | None = None) -> Any:
    return c.post("/portal/change-password", data={"username": "an.nv", "temp_password": temp_password,
                                                   "new_password": new, "confirm_password": new if confirm is None else confirm})  # fmt: skip


@pytest.mark.parametrize("env", [None, "prod", "staging", "DEV"])
def test_portal_only_in_dev_test(c: TestClient, monkeypatch: pytest.MonkeyPatch, env: str | None) -> None:
    if env is not None:
        monkeypatch.setenv("APP_ENV", env)
    assert c.get("/portal").status_code == 404
    assert _portal_login(c, "an.nv", DEMO_PASSWORD).status_code == 404


@pytest.mark.parametrize("env", ["dev", "test"])
def test_portal_page_is_plain_html_no_script(c: TestClient, monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    monkeypatch.setenv("APP_ENV", env)
    page = c.get("/portal")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert "<script" not in page.text.lower() and "http" not in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert page.headers["cache-control"] == "no-store"


def test_portal_full_flow(portal: TestClient, executor: dict[str, str], temp: str) -> None:
    ok = _portal_login(portal, "an.nv", DEMO_PASSWORD)
    assert ok.status_code == 200 and "Đăng nhập thành công" in ok.text
    _post(portal, executor, "/ad/users/nv001/reset-password", channel="sms")
    old = _portal_login(portal, "an.nv", DEMO_PASSWORD)
    assert old.status_code == 401 and "không đúng" in old.text and "Đăng nhập thành công" not in old.text
    form = _portal_login(portal, "an.nv", temp)
    assert form.status_code == 200 and 'action="/portal/change-password"' in form.text
    assert temp not in form.text  # không điền sẵn mật khẩu tạm vào trang
    done = _portal_change(portal, temp)
    assert done.status_code == 200 and "Đăng nhập thành công" in done.text and NEW_PASSWORD not in done.text
    assert "Đăng nhập thành công" in _portal_login(portal, "an.nv", NEW_PASSWORD).text
    for stale in (DEMO_PASSWORD, temp):
        assert _portal_login(portal, "an.nv", stale).status_code == 401


def test_portal_change_validation(portal: TestClient, executor: dict[str, str], temp: str, clock: MutableClock) -> None:
    _post(portal, executor, "/ad/users/nv001/reset-password", channel="sms")
    mismatch = _portal_change(portal, temp, confirm="Khac@Mat-Khau-2027")
    assert mismatch.status_code == 422 and "không khớp" in mismatch.text
    short = _portal_change(portal, temp, new="Ngan@2026")
    assert short.status_code == 422 and "12 ký tự" in short.text
    wrong = _portal_change(portal, "sai-mat-khau-tam")
    assert wrong.status_code == 401 and "Mật khẩu tạm sai hoặc đã hết hạn" in wrong.text
    clock.t = NOW + ad.TEMP_PASSWORD_TTL + timedelta(seconds=1)
    assert _portal_change(portal, temp).status_code == 401
    assert _portal_login(portal, "an.nv", NEW_PASSWORD).status_code == 401


def test_portal_locked_and_disabled(portal: TestClient) -> None:
    locked = _portal_login(portal, "mai.tt", DEMO_PASSWORD)
    assert locked.status_code == 403 and "bị khoá" in locked.text
    disabled = _portal_login(portal, "dung.dv", DEMO_PASSWORD)  # nv004
    assert disabled.status_code == 403 and "vô hiệu hoá" in disabled.text
    assert _portal_login(portal, "khong.co", DEMO_PASSWORD).status_code == 401


def test_portal_escapes_username(portal: TestClient, executor: dict[str, str], temp: str) -> None:
    r = portal.post("/portal/change-password", data={"username": '"><b>x', "temp_password": "a", "new_password": "b",
                                                     "confirm_password": "c"})  # fmt: skip
    assert r.status_code == 422 and '"><b>x' not in r.text and "&quot;&gt;&lt;b&gt;x" in r.text
