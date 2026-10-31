"""Mock console (`app/console.py`): chỉ phục vụ khi APP_ENV ∈ {dev, test} VÀ cờ MOCK_CONSOLE_ENABLED bật (1 | true), chỉ đọc, và mật khẩu tạm chỉ lộ ở trang điện thoại
của đúng nhân viên đó (`/console/phone/{user_id}`).

Mật khẩu tạm biết được nhờ monkeypatch `app.ad.new_temp_password` (mỗi lần gọi ra một canary khác nhau).
"""

import re
from collections.abc import Iterator
from datetime import datetime, timedelta

import pytest
from app import ad
from app.main import create_app
from app.security import ServiceTokens
from fastapi.testclient import TestClient
from tests.conftest import NOW
from tests.test_seed import DEMO_PASSWORD

USER_A, USER_B = "nv001", "nv002"
STATIC_PAGES = ["/console", "/console/ad", "/console/vpn", "/console/fileserver", "/console/software",
                "/console/outbox", "/console/calls", f"/console/phone/{USER_A}"]  # fmt: skip
NOT_PHONE_PAGES = [p for p in STATIC_PAGES if "/phone/" not in p]
SMS = {"account_type": "ad", "channel": "sms"}


class Clock:
    def __init__(self, t: datetime) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock(NOW)


@pytest.fixture
def canaries(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    issued: list[str] = []

    def fake() -> str:
        issued.append(f"Canary-Tmp-{len(issued) + 1}-Zq8Wx")
        return issued[-1]

    monkeypatch.setattr(ad, "new_temp_password", fake)
    yield issued


@pytest.fixture(autouse=True)
def dev_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "dev")
    monkeypatch.setenv("MOCK_CONSOLE_ENABLED", "1")


@pytest.fixture
def c(tokens: ServiceTokens, clock: Clock) -> Iterator[TestClient]:
    with TestClient(create_app(tokens=tokens, now=clock)) as client:
        yield client


def _reset_sms(c: TestClient, executor: dict[str, str], user_id: str) -> None:
    assert c.post(f"/ad/users/{user_id}/reset-password", json=SMS, headers=executor).status_code == 200


# ---- cổng môi trường -------------------------------------------------------------------------------


@pytest.mark.parametrize("env", ["dev", "test"])
@pytest.mark.parametrize("path", STATIC_PAGES)
def test_page_200_in_dev_and_test(
    c: TestClient, monkeypatch: pytest.MonkeyPatch, env: str, path: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    r = c.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "MÔI TRƯỜNG GIẢ LẬP" in r.text
    assert "26/09/2026 19:00:00" in r.text  # NOW = 12:00 UTC → giờ VN 19:00
    assert '<meta http-equiv="refresh" content="5">' in r.text
    assert r.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("env", ["prod", "staging", "production", "", "DEV", "dev "])
@pytest.mark.parametrize("path", STATIC_PAGES)
def test_page_404_when_env_not_dev_or_test(
    c: TestClient, monkeypatch: pytest.MonkeyPatch, env: str, path: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    assert c.get(path).status_code == 404


@pytest.mark.parametrize("path", STATIC_PAGES)
def test_page_404_when_env_unset(c: TestClient, monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.delenv("APP_ENV")
    assert c.get(path).status_code == 404


# ---- cờ MOCK_CONSOLE_ENABLED (P5 tuần 8): mặc định TẮT, chỉ nhận 1 | true, và vẫn cần APP_ENV dev/test ----------------------


@pytest.mark.parametrize("flag", ["1", "true"])
@pytest.mark.parametrize("env", ["dev", "test"])
@pytest.mark.parametrize("path", STATIC_PAGES)
def test_page_200_when_flag_on_in_dev_test(
    c: TestClient, monkeypatch: pytest.MonkeyPatch, flag: str, env: str, path: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("MOCK_CONSOLE_ENABLED", flag)
    assert c.get(path).status_code == 200


@pytest.mark.parametrize("env", ["dev", "test"])
@pytest.mark.parametrize("path", STATIC_PAGES)
def test_page_404_when_flag_unset_default_off(
    c: TestClient, monkeypatch: pytest.MonkeyPatch, env: str, path: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.delenv("MOCK_CONSOLE_ENABLED")
    assert c.get(path).status_code == 404


@pytest.mark.parametrize("flag", ["0", "false", "", "yes", "on", "TRUE", "True", " 1", "2"])
@pytest.mark.parametrize("path", STATIC_PAGES)
def test_page_404_when_flag_not_exactly_on(c: TestClient, monkeypatch: pytest.MonkeyPatch, flag: str, path: str) -> None:
    monkeypatch.setenv("MOCK_CONSOLE_ENABLED", flag)
    assert c.get(path).status_code == 404


@pytest.mark.parametrize("env", ["prod", "staging", ""])
@pytest.mark.parametrize("path", STATIC_PAGES)
def test_page_404_outside_dev_test_even_with_flag_on(
    c: TestClient, monkeypatch: pytest.MonkeyPatch, env: str, path: str
) -> None:
    monkeypatch.setenv("APP_ENV", env)
    monkeypatch.setenv("MOCK_CONSOLE_ENABLED", "1")
    assert c.get(path).status_code == 404


def test_flag_off_applies_to_unknown_subpages_and_users(c: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_CONSOLE_ENABLED", "0")
    for path in ("/console/phone/khong-co-ai", "/console/khong-ton-tai", "/console/"):
        assert c.get(path).status_code == 404, path


def test_gate_applies_to_unknown_user_too(c: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    assert c.get("/console/phone/khong-co").status_code == 404
    assert c.get("/console/khong-co").status_code == 404


@pytest.mark.parametrize("path", STATIC_PAGES)
def test_read_only(c: TestClient, path: str) -> None:
    for method in ("post", "put", "patch", "delete"):
        assert getattr(c, method)(path).status_code == 405


def test_get_does_not_change_state(c: TestClient, executor: dict[str, str], canaries: list[str]) -> None:
    _reset_sms(c, executor, USER_A)
    state = c.app.state.mock  # type: ignore[attr-defined]
    before = (len(state.outbox), state.users[USER_A].password_hash, state.users[USER_A].must_change_password)
    for p in STATIC_PAGES:
        c.get(p)
    assert (len(state.outbox), state.users[USER_A].password_hash, state.users[USER_A].must_change_password) == before


# ---- mật khẩu ----------------------------------------------------------------------------------


def test_seed_phones_are_unique(c: TestClient) -> None:
    phones = [u.phone for u in c.app.state.mock.users.values() if u.phone]  # type: ignore[attr-defined]
    assert len(phones) == len(set(phones))  # C5 tách SMS theo số — số trùng sẽ lộ chéo


def test_temp_password_not_shown_outside_phone_page(
    c: TestClient, executor: dict[str, str], canaries: list[str]
) -> None:
    _reset_sms(c, executor, USER_A)
    _reset_sms(c, executor, USER_B)
    assert len(canaries) == 2
    for path in NOT_PHONE_PAGES:
        text = c.get(path).text
        for secret in canaries:
            assert secret not in text, path
        assert "$argon2" not in text, path
        assert DEMO_PASSWORD not in text, path
    # trang điện thoại của người KHÁC cũng không chứa mật khẩu của hai người trên
    other = c.get("/console/phone/l1_01").text
    assert not any(s in other for s in canaries)
    assert "$argon2" not in c.get(f"/console/phone/{USER_A}").text
    assert DEMO_PASSWORD not in c.get(f"/console/phone/{USER_A}").text


def test_ad_page_shows_temp_password_flags_only(
    c: TestClient, executor: dict[str, str], canaries: list[str], clock: Clock
) -> None:
    def row(text: str, user_id: str) -> str:
        return next(line for line in text.split("<tr>") if f"<td>{user_id}</td>" in line)

    before = row(c.get("/console/ad").text, USER_A)
    assert before.count("<td>không</td>") >= 3  # không khoá + không phải đổi + không có mật khẩu tạm
    _reset_sms(c, executor, USER_A)
    after = row(c.get("/console/ad").text, USER_A)
    assert after.endswith("<td>có</td><td>có</td></tr>")  # phải đổi mật khẩu = có; mật khẩu tạm còn hạn = có
    assert canaries[0] not in after
    clock.t = NOW + timedelta(minutes=16)  # quá hạn 15 phút
    expired = row(c.get("/console/ad").text, USER_A)
    assert expired.endswith("<td>có</td><td>không</td></tr>")
    assert "19:00:00" in after  # password_last_set = lúc reset (giờ VN)


def test_ad_page_masks_phone_and_email(c: TestClient) -> None:
    text = c.get("/console/ad").text
    assert "0900***001" in text
    assert "0900000001" not in text
    assert "<th>Email (che)</th>" in text
    assert "<td>n***@d***</td>" in text  # nv001@demo-corp.local đã che
    assert "@demo-corp.local" not in text


def test_ad_page_masks_overridden_email_and_dash_when_missing(c: TestClient) -> None:
    users = c.app.state.mock.users  # type: ignore[attr-defined]
    users[USER_A].email = "chu.tai.khoan+anv@gmail.com"  # như nạp từ seed.local.json
    users[USER_B].email = None
    text = c.get("/console/ad").text
    assert "chu.tai.khoan" not in text and "gmail.com" not in text
    assert "<td>c***@g***</td>" in text
    cells_b = re.findall(r"<td>(.*?)</td>", text[text.index(f"<td>{USER_B}</td>"):].split("</tr>")[0])
    assert cells_b[0] == USER_B and cells_b[2] == "—"  # cột thứ 3 = Email (che)


def test_outbox_masks_password(c: TestClient, executor: dict[str, str], canaries: list[str]) -> None:
    _reset_sms(c, executor, USER_A)
    text = c.get("/console/outbox").text
    assert "******" in text
    assert canaries[0] not in text
    assert "Mat khau tam cua ban" in text  # tin SMS vẫn hiện, chỉ che mật khẩu
    assert "email" in text and "sms" in text
    # email báo chủ tài khoản vẫn hiện
    assert "yêu cầu đặt lại mật khẩu qua SMS" in text


def test_outbox_empty(c: TestClient) -> None:
    assert "(chưa có tin nào)" in c.get("/console/outbox").text


def test_phone_page_shows_own_temp_password(
    c: TestClient, executor: dict[str, str], canaries: list[str]
) -> None:
    _reset_sms(c, executor, USER_A)
    text = c.get(f"/console/phone/{USER_A}").text
    assert canaries[0] in text
    assert "******" not in text
    assert "0900000001" in text


def test_phone_page_does_not_show_other_users_sms(
    c: TestClient, executor: dict[str, str], canaries: list[str]
) -> None:
    _reset_sms(c, executor, USER_A)
    _reset_sms(c, executor, USER_B)
    a, b = canaries
    page_a = c.get(f"/console/phone/{USER_A}").text
    page_b = c.get(f"/console/phone/{USER_B}").text
    assert a in page_a and b not in page_a
    assert b in page_b and a not in page_b
    assert "0900000002" not in page_a
    assert "0900000001" not in page_b
    assert page_a.count("Mat khau tam cua ban") == 1  # đúng 1 SMS, không lẫn
    assert "yêu cầu đặt lại mật khẩu qua SMS" not in page_a  # email báo chủ tài khoản không phải SMS


def test_phone_page_empty_before_any_sms(c: TestClient) -> None:
    text = c.get(f"/console/phone/{USER_A}").text
    assert "(chưa có SMS nào)" in text


def test_phone_page_user_without_phone_and_unknown_user(c: TestClient, executor: dict[str, str]) -> None:
    r = c.get("/console/phone/nv006")
    assert r.status_code == 200
    assert "Không có số điện thoại" in r.text
    assert c.get("/console/phone/khong-co").status_code == 404


def test_phone_page_after_password_changed_still_lists_history(
    c: TestClient, executor: dict[str, str], canaries: list[str]
) -> None:
    _reset_sms(c, executor, USER_A)
    username = c.app.state.mock.users[USER_A].username  # type: ignore[attr-defined]
    body = {"username": username, "temp_password": canaries[0], "new_password": "Moi@Mat-Khau-2026"}
    assert c.post("/ad/change-password", json=body, headers=executor).status_code == 200
    ad_text = c.get("/console/ad").text
    assert "Moi@Mat-Khau-2026" not in ad_text
    assert "Moi@Mat-Khau-2026" not in c.get("/console/outbox").text
    assert "Moi@Mat-Khau-2026" not in c.get(f"/console/phone/{USER_A}").text


# ---- nội dung từng trang -----------------------------------------------------------------------


def test_index_links_every_page(c: TestClient) -> None:
    text = c.get("/console").text
    for href in ["/console/ad", "/console/vpn", "/console/fileserver", "/console/software", "/console/outbox",
                 "/console/calls", f"/console/phone/{USER_A}"]:  # fmt: skip
        assert f'href="{href}"' in text


def test_ad_page_lists_users_with_lock_and_status(c: TestClient) -> None:
    text = c.get("/console/ad").text
    for col in ["user_id", "Tên", "password_last_set", "Phải đổi mật khẩu", "Có mật khẩu tạm còn hạn"]:
        assert f"<th>{col}</th>" in text
    assert "nv007" in text and "email (bad_password)" in text  # nv007 bị khoá email
    assert "disabled" in text  # nv004


def test_vpn_page(c: TestClient) -> None:
    text = c.get("/console/vpn").text
    assert "VPN-2025-0342" in text and "expired" in text and "LAP-0342" in text
    assert "CERT_EXPIRED" in text  # kết nối gần nhất của nv001


def test_fileserver_page(c: TestClient) -> None:
    text = c.get("/console/fileserver").text
    assert "finance/Q3" in text and "expired" in text and "high" in text


def test_software_page_and_license_holder(c: TestClient, executor: dict[str, str]) -> None:
    text = c.get("/console/software").text
    assert "LAP-0342" in text and "ms-office" in text
    assert "ms-project" in text
    r = c.post("/software/licenses/adobe-acrobat-pro/assign", json={"user_id": USER_A}, headers=executor)
    assert r.status_code == 200
    after = c.get("/console/software").text
    assert f"<td>{USER_A}</td></tr>" in after.split("adobe-acrobat-pro")[1]  # người giữ license hiện ra


def test_calls_page_lists_endpoints_with_status(c: TestClient, agent: dict[str, str]) -> None:
    c.get(f"/ad/users/{USER_A}", headers=agent)
    c.get("/ad/users/khong-co", headers=agent)
    c.get("/console/ad")
    text = c.get("/console/calls").text
    assert f"/ad/users/{USER_A}" in text and "200 ×1" in text
    assert "/ad/users/khong-co" in text and "404 ×1" in text
    assert "/console" not in text.split("<table>")[1]  # lời gọi tới chính màn này bị ẩn


def test_calls_page_empty(c: TestClient) -> None:
    c.get("/console")
    assert "(chưa có lời gọi nào)" in c.get("/console/calls").text


def test_html_is_escaped(c: TestClient) -> None:
    c.app.state.mock.users[USER_A].full_name = "<script>alert(1)</script>"  # type: ignore[attr-defined]
    for path in ("/console/ad", "/console", f"/console/phone/{USER_A}"):
        text = c.get(path).text
        assert "<script>alert(1)</script>" not in text
        assert "&lt;script&gt;" in text
