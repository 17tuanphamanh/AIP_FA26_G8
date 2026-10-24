"""Mock-fidelity (F1–F5): phần mềm / license / VPN / thư mục chạy như hệ thống thật.

Mỗi điểm kiểm cả hai chiều: trạng thái đọc lại được sau khi ghi, và ca phủ định (không đổi gì khi bị từ chối).
"""

import copy
from typing import Any

import pytest
from app.seed_model import SeedData
from app.state import SEED_PATH, Installed, load_seed
from fastapi.testclient import TestClient

Headers = dict[str, str]

# 7 tên phần mềm viết trong kb/software/KB-SW-001.md → slug trong seed
KB_NAMES = {
    "7-Zip": "7zip",
    "Adobe Acrobat Pro": "adobe-acrobat-pro",
    "AutoCAD": "autocad",
    "Microsoft Office": "ms-office",
    "Microsoft Project": "ms-project",
    "Visual Studio Code": "vscode",
    "Zoom Workplace": "zoom",
}


def _installed(client: TestClient, agent: Headers, device_id: str) -> list[dict[str, Any]]:
    resp = client.get(f"/software/installed/{device_id}", headers=agent)
    assert resp.status_code == 200
    return resp.json()


def _pool(client: TestClient, agent: Headers, name: str) -> dict[str, Any]:
    resp = client.get(f"/software/licenses/{name}", headers=agent)
    assert resp.status_code == 200
    return resp.json()


def _assign(client: TestClient, executor: Headers, name: str, user_id: str) -> Any:
    return client.post(f"/software/licenses/{name}/assign", headers=executor, json={"user_id": user_id})


def _install(client: TestClient, executor: Headers, device_id: str, name: str) -> Any:
    return client.post(f"/software/installed/{device_id}/install", headers=executor, json={"software_name": name})


def _uninstall(client: TestClient, executor: Headers, device_id: str, name: str) -> Any:
    return client.post(f"/software/installed/{device_id}/uninstall", headers=executor, json={"software_name": name})


# ---- F1: tên phần mềm theo KB ------------------------------------------------------------------


@pytest.mark.parametrize(("kb_name", "slug"), KB_NAMES.items())
def test_f1_kb_display_name_resolves_to_entry(client: TestClient, agent: Headers, kb_name: str, slug: str) -> None:
    for variant in (kb_name, kb_name.lower(), f"  {kb_name.upper()}  "):
        resp = client.get(f"/software/catalog/{variant}", headers=agent)
        assert resp.status_code == 200, variant
        assert (resp.json()["name"], resp.json()["display_name"]) == (slug, kb_name)


@pytest.mark.parametrize("slug", sorted(KB_NAMES.values()))
def test_f1_slug_still_resolves(client: TestClient, agent: Headers, slug: str) -> None:
    assert client.get(f"/software/catalog/{slug}", headers=agent).json()["name"] == slug


@pytest.mark.parametrize("unknown", ["utorrent", "Zoom Workplace Pro", "Microsoft", "Visual Studio", "7"])
def test_f1_unknown_name_is_404(client: TestClient, agent: Headers, unknown: str) -> None:
    assert client.get(f"/software/catalog/{unknown}", headers=agent).status_code == 404
    assert client.get(f"/software/licenses/{unknown}", headers=agent).status_code == 404


@pytest.mark.parametrize(
    ("alias", "slug"),
    [("vs code", "vscode"), ("VS  Code", "vscode"), ("7z", "7zip"), ("7 zip", "7zip"), ("Acrobat Pro", "adobe-acrobat-pro"),
     ("office", "ms-office"), ("MS Project", "ms-project"), ("Zoom Meeting", "zoom")],
)  # fmt: skip
def test_f1_alias_from_seed_resolves(client: TestClient, agent: Headers, alias: str, slug: str) -> None:
    resp = client.get(f"/software/catalog/{alias}", headers=agent)
    assert resp.status_code == 200 and resp.json()["name"] == slug
    assert client.get(f"/software/licenses/{alias}", headers=agent).json()["name"] == slug


def test_f1_every_seed_name_is_unique_across_catalog() -> None:
    seen: dict[str, str] = {}
    for c in load_seed().catalog:
        for raw in (c.name, c.display_name, *c.aliases):
            key = "-".join(raw.lower().split())
            assert seen.setdefault(key, c.name) == c.name, key


def _catalog_with(mutate: Any) -> dict[str, Any]:
    raw = load_seed(SEED_PATH).model_dump(mode="json")
    data = copy.deepcopy(raw)
    mutate({c["name"]: c for c in data["catalog"]})
    return data


@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: c["zoom"].update(aliases=["vs code"]),  # alias của phần mềm khác
        lambda c: c["zoom"].update(aliases=["autocad"]),  # alias trùng slug phần mềm khác
        lambda c: c["zoom"].update(aliases=["Visual  Studio Code"]),  # trùng tên hiển thị phần mềm khác (sau chuẩn hoá)
        lambda c: c["zoom"].update(aliases=["a b", "A  B"]),  # trùng nhau trong cùng mục
        lambda c: c["zoom"].update(aliases=["zoom"]),  # trùng slug của chính nó
        lambda c: c["zoom"].update(aliases=["Zoom  Workplace"]),  # trùng tên hiển thị của chính nó
        lambda c: c["zoom"].update(aliases=["  "]),  # rỗng
        lambda c: c["zoom"].update(display_name="  "),
        lambda c: c["zoom"].update(display_name=" Zoom Workplace"),
        lambda c: c["zoom"].update(display_name="visual studio code"),  # tên hiển thị trùng phần mềm khác
        lambda c: c["zoom"].update(name="Zoom App"),  # slug có chữ hoa / dấu cách
    ],
)
def test_f1_seed_rejects_bad_names_and_aliases(mutate: Any) -> None:
    with pytest.raises(ValueError):
        SeedData.model_validate(_catalog_with(mutate))


def test_f1_seed_accepts_entry_without_aliases() -> None:
    SeedData.model_validate(_catalog_with(lambda c: c["zoom"].pop("aliases")))


def test_f1_display_name_works_on_license_install_and_uninstall(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    assert _pool(client, agent, "Adobe Acrobat Pro")["available"] == 3
    assert _pool(client, agent, "Microsoft Project")["available"] == 0
    assert _install(client, executor, "LAP-0610", "Visual Studio Code").json()["name"] == "vscode"
    assert "vscode" in [i["name"] for i in _installed(client, agent, "LAP-0610")]
    body = _uninstall(client, executor, "LAP-0610", "Visual Studio Code").json()
    assert (body["name"], body["removed"]) == ("vscode", True)
    assert _installed(client, agent, "LAP-0610") == []


# ---- F2: license -------------------------------------------------------------------------------


def test_f2_licenses_list_who_holds_them(client: TestClient, agent: Headers, executor: Headers) -> None:
    before = _pool(client, agent, "adobe-acrobat-pro")
    assert before["assignments"] == [] and before["used"] == 7  # 7 chỗ dựng sẵn từ seed không có tên người giữ
    assert _pool(client, agent, "zoom")["assignments"] == []
    granted = _assign(client, executor, "adobe-acrobat-pro", "nv001")
    assert granted.status_code == 200
    after = _pool(client, agent, "adobe-acrobat-pro")
    assert after["assignments"] == [{"assignment_id": granted.json()["assignment_id"], "user_id": "nv001"}]
    assert (after["used"], after["available"]) == (8, 2)


def test_f2_assign_twice_to_same_user_is_409_and_changes_nothing(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    assert _assign(client, executor, "adobe-acrobat-pro", "nv001").status_code == 200
    again = _assign(client, executor, "Adobe Acrobat Pro", "nv001")  # đổi cách gọi tên vẫn là cùng license
    assert (again.status_code, again.json()["detail"]) == (409, "already_assigned")
    pool = _pool(client, agent, "adobe-acrobat-pro")
    assert (pool["used"], len(pool["assignments"])) == (8, 1)
    other = _assign(client, executor, "adobe-acrobat-pro", "nv002")
    assert other.status_code == 200
    assert {a["user_id"] for a in _pool(client, agent, "adobe-acrobat-pro")["assignments"]} == {"nv001", "nv002"}


def test_f2_already_assigned_wins_over_pool_full(client: TestClient, executor: Headers) -> None:
    for user in ("nv001", "nv002", "nv003"):  # autocad: total 3, used 3 → kho đã đầy từ seed
        assert _assign(client, executor, "autocad", user).json()["detail"] == "no_license_available"
    # đổ đầy kho bằng license acrobat rồi cấp lại cho người đã giữ: phải báo trùng, không báo hết
    for user in ("nv001", "nv002", "nv003"):
        assert _assign(client, executor, "adobe-acrobat-pro", user).status_code == 200
    assert _assign(client, executor, "adobe-acrobat-pro", "nv005").json()["detail"] == "no_license_available"
    assert _assign(client, executor, "adobe-acrobat-pro", "nv001").json()["detail"] == "already_assigned"


def test_f2_assign_free_software_still_409_not_a_paid_license(client: TestClient, executor: Headers) -> None:
    assert _assign(client, executor, "zoom", "nv001").json()["detail"] == "not_a_paid_license"


def test_f2_install_paid_without_license_is_409_and_installs_nothing(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    resp = _install(client, executor, "LAP-0342", "adobe-acrobat-pro")
    assert (resp.status_code, resp.json()["detail"]) == (409, "license_not_assigned")
    assert [i["name"] for i in _installed(client, agent, "LAP-0342")] == ["ms-office", "zoom"]
    _assign(client, executor, "adobe-acrobat-pro", "nv002")  # license của người khác không tính cho chủ máy
    assert _install(client, executor, "LAP-0342", "Adobe Acrobat Pro").json()["detail"] == "license_not_assigned"
    assert [i["name"] for i in _installed(client, agent, "LAP-0342")] == ["ms-office", "zoom"]


def test_f2_install_paid_with_license_of_device_owner_succeeds(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    _assign(client, executor, "adobe-acrobat-pro", "nv001")
    resp = _install(client, executor, "LAP-0342", "adobe-acrobat-pro")
    assert resp.status_code == 200 and resp.json()["already_installed"] is False
    assert [i["name"] for i in _installed(client, agent, "LAP-0342")] == ["adobe-acrobat-pro", "ms-office", "zoom"]


def test_f2_install_free_needs_no_license(client: TestClient, agent: Headers, executor: Headers) -> None:
    assert _install(client, executor, "LAP-0610", "zoom").status_code == 200
    assert [i["name"] for i in _installed(client, agent, "LAP-0610")] == ["zoom"]


def test_f2_uninstall_gives_license_back(client: TestClient, agent: Headers, executor: Headers) -> None:
    _assign(client, executor, "adobe-acrobat-pro", "nv001")
    _install(client, executor, "LAP-0342", "adobe-acrobat-pro")
    assert _pool(client, agent, "adobe-acrobat-pro")["available"] == 2
    body = _uninstall(client, executor, "LAP-0342", "adobe-acrobat-pro").json()
    assert (body["removed"], body["license_released"]) == (True, True)
    pool = _pool(client, agent, "adobe-acrobat-pro")
    assert (pool["used"], pool["available"], pool["assignments"]) == (7, 3, [])
    # trả rồi thì không còn cài được nếu không cấp lại, và cấp lại được
    assert _install(client, executor, "LAP-0342", "adobe-acrobat-pro").json()["detail"] == "license_not_assigned"
    assert _assign(client, executor, "adobe-acrobat-pro", "nv001").status_code == 200


def test_f2_uninstall_without_install_returns_no_license(client: TestClient, agent: Headers, executor: Headers) -> None:
    _assign(client, executor, "adobe-acrobat-pro", "nv001")  # có license nhưng chưa cài gì
    body = _uninstall(client, executor, "LAP-0342", "adobe-acrobat-pro").json()
    assert (body["removed"], body["license_released"]) == (False, False)
    pool = _pool(client, agent, "adobe-acrobat-pro")
    assert (pool["used"], len(pool["assignments"])) == (8, 1)


def test_f2_uninstall_free_or_unknown_releases_nothing(client: TestClient, executor: Headers) -> None:
    body = _uninstall(client, executor, "LAP-0342", "zoom").json()
    assert (body["removed"], body["license_released"]) == (True, False)
    body = _uninstall(client, executor, "LAP-0342", "utorrent").json()
    assert (body["name"], body["removed"], body["license_released"]) == ("utorrent", False, False)


def test_f2_license_kept_until_last_device_of_owner_is_cleaned(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    _assign(client, executor, "adobe-acrobat-pro", "nv002")  # nv002 có LAP-0417 và PC-0977
    assert _install(client, executor, "LAP-0417", "adobe-acrobat-pro").status_code == 200
    assert _install(client, executor, "PC-0977", "adobe-acrobat-pro").status_code == 200  # license theo người, không theo máy
    first = _uninstall(client, executor, "LAP-0417", "adobe-acrobat-pro").json()
    assert first["license_released"] is False
    assert [a["user_id"] for a in _pool(client, agent, "adobe-acrobat-pro")["assignments"]] == ["nv002"]
    second = _uninstall(client, executor, "PC-0977", "adobe-acrobat-pro").json()
    assert second["license_released"] is True
    assert _pool(client, agent, "adobe-acrobat-pro")["assignments"] == []


def test_f2_assignment_ids_stay_unique_after_a_release(client: TestClient, agent: Headers, executor: Headers) -> None:
    first = _assign(client, executor, "adobe-acrobat-pro", "nv001").json()["assignment_id"]
    second = _assign(client, executor, "adobe-acrobat-pro", "nv002").json()["assignment_id"]
    _install(client, executor, "LAP-0342", "adobe-acrobat-pro")
    _uninstall(client, executor, "LAP-0342", "adobe-acrobat-pro")  # nv001 trả → used lùi 1
    third = _assign(client, executor, "adobe-acrobat-pro", "nv003").json()["assignment_id"]
    ids = [a["assignment_id"] for a in _pool(client, agent, "adobe-acrobat-pro")["assignments"]]
    assert first != second and ids == [second, third] and len(set(ids)) == 2


# ---- F3: cài lại phần mềm đã có ----------------------------------------------------------------


def test_f3_install_existing_reports_current_version_and_changes_nothing(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    before = _installed(client, agent, "LAP-0342")
    resp = _install(client, executor, "LAP-0342", "Zoom Workplace")
    assert resp.status_code == 200
    body = resp.json()
    assert body["already_installed"] is True
    assert body["version"] == "6.1"  # bản đang cài, không phải bản 6.2 của danh mục
    assert _installed(client, agent, "LAP-0342") == before
    assert body["installed_at"] == next(i for i in before if i["name"] == "zoom")["installed_at"]


def test_f3_first_install_is_new_and_second_is_already_installed(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    first = _install(client, executor, "LAP-0610", "7zip").json()
    assert (first["already_installed"], first["version"]) == (False, "24.08")
    second = _install(client, executor, "LAP-0610", "7-Zip").json()
    assert (second["already_installed"], second["version"]) == (True, "24.08")
    assert second["installed_at"] == first["installed_at"]
    assert len(_installed(client, agent, "LAP-0610")) == 1


def test_f3_already_installed_paid_is_reported_before_license_check(client: TestClient, executor: Headers) -> None:
    state = client.app.state.mock  # type: ignore[attr-defined]
    state.installed.append(Installed("LAP-0342", "autocad", "2024", state.now()))  # cài từ trước, không có license cấp qua mock
    body = _install(client, executor, "LAP-0342", "AutoCAD")
    assert body.status_code == 200
    assert (body.json()["already_installed"], body.json()["version"]) == (True, "2024")


def test_f3_install_on_unknown_device_or_software_is_404(client: TestClient, executor: Headers) -> None:
    assert _install(client, executor, "KHONG-CO", "zoom").status_code == 404
    assert _install(client, executor, "LAP-0342", "utorrent").status_code == 404


# ---- F4: VPN kết nối thử -----------------------------------------------------------------------


def _connect(client: TestClient, executor: Headers, user_id: str, device_id: str) -> Any:
    return client.post("/vpn/connect", headers=executor, json={"user_id": user_id, "device_id": device_id})


def _last(client: TestClient, agent: Headers, user_id: str) -> dict[str, Any]:
    return client.get(f"/vpn/connections/{user_id}", headers=agent).json()[0]


@pytest.mark.parametrize(
    ("user_id", "device_id", "result", "error_code"),
    [
        ("nv002", "LAP-0417", "success", None),
        ("nv001", "LAP-0342", "failed", "CERT_EXPIRED"),
        ("nv004", "LAP-0233", "failed", "NO_CERT"),  # đã đăng ký nhưng chưa từng được cấp chứng chỉ
        ("nv002", "PC-0977", "failed", "DEVICE_NOT_REGISTERED"),
        ("l1_01", "PC-0124", "failed", "DEVICE_NOT_REGISTERED"),
        ("nv005", "LAP-0610", "failed", "CERT_REVOKED"),  # chỉ còn chứng chỉ đã thu hồi (seed đã có mã này)
    ],
)
def test_f4_connect_outcome_follows_real_state_and_is_recorded(
    client: TestClient, agent: Headers, executor: Headers, user_id: str, device_id: str, result: str,
    error_code: str | None,
) -> None:
    before = client.get(f"/vpn/connections/{user_id}", headers=agent).json()
    resp = _connect(client, executor, user_id, device_id)
    assert resp.status_code == 200
    body = resp.json()
    assert (body["result"], body["error_code"], body["device_id"]) == (result, error_code, device_id)
    after = client.get(f"/vpn/connections/{user_id}", headers=agent).json()
    assert len(after) == min(len(before) + 1, 10)
    assert after[0] == {"at": body["at"], "device_id": device_id, "result": result, "error_code": error_code}


def test_f4_connect_succeeds_after_renew_and_fails_after_revoke(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    assert _connect(client, executor, "nv001", "LAP-0342").json()["error_code"] == "CERT_EXPIRED"
    renewed = client.post("/vpn/certs/nv001/renew", headers=executor, json={"device_id": "LAP-0342"}).json()
    assert _connect(client, executor, "nv001", "LAP-0342").json()["result"] == "success"
    assert (_last(client, agent, "nv001")["result"], _last(client, agent, "nv001")["error_code"]) == ("success", None)
    client.post("/vpn/certs/nv001/revoke", headers=executor, json={"serial": renewed["serial"]})
    # cert hết hạn cũ đã bị thu hồi lúc renew, cert mới vừa bị thu hồi: không còn cái nào dùng được
    assert _connect(client, executor, "nv001", "LAP-0342").json()["error_code"] == "CERT_REVOKED"


def test_f4_valid_cert_beats_old_expired_one_on_same_device(client: TestClient, executor: Headers) -> None:
    state = client.app.state.mock  # type: ignore[attr-defined]
    old = next(c for c in state.certs if c.serial == "VPN-2025-0342")
    assert old.expires_at < state.now() and not old.revoked
    client.post("/vpn/certs/nv001/renew", headers=executor, json={"device_id": "LAP-0342"})
    old.revoked = False  # dựng ca: cert cũ hết hạn (chưa thu hồi) nằm cạnh cert mới còn hạn
    assert _connect(client, executor, "nv001", "LAP-0342").json()["result"] == "success"


def test_f4_connect_does_not_touch_certs(client: TestClient, agent: Headers, executor: Headers) -> None:
    before = client.get("/vpn/certs/nv001", headers=agent).json()
    _connect(client, executor, "nv001", "LAP-0342")
    assert client.get("/vpn/certs/nv001", headers=agent).json() == before


def test_f4_connect_negative_cases(client: TestClient, agent: Headers, executor: Headers) -> None:
    assert _connect(client, executor, "khong_co", "LAP-0342").status_code == 404
    assert _connect(client, executor, "nv001", "KHONG-CO").status_code == 404
    assert _connect(client, executor, "nv001", "LAP-0417").status_code == 404  # máy của người khác
    assert client.post("/vpn/connect", headers=executor, json={"user_id": "nv001"}).status_code == 422
    assert client.get("/vpn/connections/nv001", headers=agent).json()[0]["device_id"] == "LAP-0342"
    assert len(client.get("/vpn/connections/nv001", headers=agent).json()) == 4  # không ghi gì từ các lần bị từ chối


def test_f4_connect_is_a_write(client: TestClient, agent: Headers, worker: Headers) -> None:
    body = {"user_id": "nv001", "device_id": "LAP-0342"}
    assert client.post("/vpn/connect", headers=agent, json=body).status_code == 403
    assert client.post("/vpn/connect", headers=worker, json=body).status_code == 403
    assert client.post("/vpn/connect", json=body).status_code == 401
    assert len(client.get("/vpn/connections/nv001", headers=agent).json()) == 4


# ---- F5: thư mục -------------------------------------------------------------------------------


def _grant(client: TestClient, executor: Headers, user_id: str, path: str, level: str, days: int | None = 30) -> Any:
    return client.post(f"/files/permissions/{user_id}/grant", headers=executor,
                       json={"resource_path": path, "level": level, "duration_days": days})  # fmt: skip


def _perm(client: TestClient, agent: Headers, user_id: str, path: str) -> list[dict[str, Any]]:
    return client.get(f"/files/permissions/{user_id}", headers=agent, params={"resource_path": path}).json()


def _set_status(client: TestClient, user_id: str, status: str) -> None:
    assert client.post(f"/_admin/users/{user_id}/status", json={"employment_status": status}).status_code == 200


@pytest.mark.parametrize("user_id", ["nv004", "nv006"])  # disabled, terminated
def test_f5_grant_to_inactive_user_is_409_and_grants_nothing(
    client: TestClient, agent: Headers, executor: Headers, user_id: str
) -> None:
    resp = _grant(client, executor, user_id, "finance/public-reports", "read")
    assert (resp.status_code, resp.json()["detail"]) == (409, "user_not_active")
    assert _perm(client, agent, user_id, "finance/public-reports") == []


def test_f5_grant_to_probation_user_is_allowed(client: TestClient, agent: Headers, executor: Headers) -> None:
    assert _grant(client, executor, "nv003", "finance/public-reports", "read").status_code == 200  # nv003 đang thử việc
    assert _perm(client, agent, "nv003", "finance/public-reports")[0]["level"] == "read"


def test_f5_user_disabled_after_the_fact_cannot_be_granted_or_extended(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    before = _perm(client, agent, "nv001", "finance/Q3")
    _set_status(client, "nv001", "disabled")
    resp = _grant(client, executor, "nv001", "finance/Q3", "write")
    assert (resp.status_code, resp.json()["detail"]) == (409, "user_not_active")
    ext = client.post("/files/permissions/nv001/extend", headers=executor,
                      json={"resource_path": "finance/Q3", "duration_days": 30})  # fmt: skip
    assert (ext.status_code, ext.json()["detail"]) == (409, "user_not_active")
    assert _perm(client, agent, "nv001", "finance/Q3") == before  # quyền cũ nguyên vẹn
    _set_status(client, "nv001", "active")
    assert client.post("/files/permissions/nv001/extend", headers=executor,
                       json={"resource_path": "finance/Q3", "duration_days": 30}).status_code == 200  # fmt: skip


def test_f5_revoke_is_still_allowed_for_inactive_user(client: TestClient, agent: Headers, executor: Headers) -> None:
    _set_status(client, "nv007", "terminated")  # nghỉ việc: thu quyền phải làm được
    resp = client.post("/files/permissions/nv007/revoke", headers=executor, json={"resource_path": "hr/salaries"})
    assert resp.status_code == 200 and resp.json()["revoked"] is True
    assert _perm(client, agent, "nv007", "hr/salaries") == []


def test_f5_extend_inactive_user_without_permission_is_404_not_409(client: TestClient, executor: Headers) -> None:
    resp = client.post("/files/permissions/nv004/extend", headers=executor,
                       json={"resource_path": "finance/Q3", "duration_days": 5})  # fmt: skip
    assert resp.status_code == 404


def test_f5_grant_does_not_lower_a_higher_active_level(client: TestClient, agent: Headers, executor: Headers) -> None:
    before = _perm(client, agent, "nv007", "hr/salaries")[0]
    assert before["level"] == "write" and before["expires_at"] is None
    resp = _grant(client, executor, "nv007", "hr/salaries", "read", days=7)
    assert resp.status_code == 200
    body = resp.json()
    assert (body["level"], body["previous_level"], body["kept_higher_level"]) == ("write", "write", True)
    assert _perm(client, agent, "nv007", "hr/salaries") == [before]  # mức, ngày cấp, hạn đều giữ nguyên


def test_f5_grant_can_raise_or_refresh_level(client: TestClient, agent: Headers, executor: Headers) -> None:
    up = _grant(client, executor, "nv007", "hr/salaries", "full", days=10).json()
    assert (up["level"], up["previous_level"], up["kept_higher_level"]) == ("full", "write", False)
    assert _perm(client, agent, "nv007", "hr/salaries")[0]["level"] == "full"
    same = _grant(client, executor, "nv007", "hr/salaries", "full", days=None).json()
    assert (same["level"], same["previous_level"], same["kept_higher_level"], same["expires_at"]) == (
        "full", "full", False, None,
    )
    assert len(_perm(client, agent, "nv007", "hr/salaries")) == 1


def test_f5_first_grant_has_no_previous_level(client: TestClient, agent: Headers, executor: Headers) -> None:
    body = _grant(client, executor, "nv003", "shared/templates", "write").json()
    assert (body["level"], body["previous_level"], body["kept_higher_level"]) == ("write", None, False)
    assert _perm(client, agent, "nv003", "shared/templates")[0]["level"] == "write"


def test_f5_expired_higher_level_does_not_block_a_lower_grant(
    client: TestClient, agent: Headers, executor: Headers
) -> None:
    client.post("/files/permissions/nv007/restore-expiry", headers=executor,
                json={"resource_path": "hr/salaries", "expires_at": "2026-09-01T00:00:00Z"})  # fmt: skip
    assert _perm(client, agent, "nv007", "hr/salaries")[0]["status"] == "expired"
    body = _grant(client, executor, "nv007", "hr/salaries", "read").json()
    assert (body["level"], body["previous_level"], body["kept_higher_level"]) == ("read", "write", False)
    assert _perm(client, agent, "nv007", "hr/salaries")[0]["status"] == "active"


def test_f5_grant_negative_cases_keep_existing_404(client: TestClient, executor: Headers) -> None:
    assert _grant(client, executor, "khong_co", "finance/Q3", "read").status_code == 404
    assert _grant(client, executor, "nv001", "khong/co", "read").status_code == 404
    assert _grant(client, executor, "nv001", "finance/Q3", "admin").status_code == 422
