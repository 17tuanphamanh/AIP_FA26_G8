"""Endpoint đọc/ghi của mock với seed (NOW cố định trong conftest)."""

from fastapi.testclient import TestClient
from tests.test_seed import DEMO_PASSWORD


def test_authenticate(client: TestClient, agent: dict[str, str]) -> None:
    ok = client.post("/ad/authenticate", headers=agent,
                     json={"username": "an.nv", "password": DEMO_PASSWORD})  # fmt: skip
    assert ok.status_code == 200
    body = ok.json()
    assert body["user_id"] == "nv001" and body["groups"] == ["IT-Users"]
    assert "password_hash" not in ok.text and "argon2" not in ok.text
    wrong = client.post("/ad/authenticate", headers=agent, json={"username": "an.nv", "password": "sai"})
    unknown = client.post("/ad/authenticate", headers=agent,
                          json={"username": "khong.co", "password": DEMO_PASSWORD})  # fmt: skip
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # không dò được username


def test_disabled_user_still_authenticates_backend_decides(client: TestClient, agent: dict[str, str]) -> None:
    resp = client.post("/ad/authenticate", headers=agent,
                       json={"username": "dung.dv", "password": DEMO_PASSWORD})  # fmt: skip
    assert resp.status_code == 200 and resp.json()["employment_status"] == "disabled"


def test_user_and_account_type(client: TestClient, agent: dict[str, str]) -> None:
    u = client.get("/ad/users/nv007", headers=agent, params={"account_type": "email"}).json()
    assert u["account"] == {"account_type": "email", "enabled": True, "locked": True,
                            "lock_reason": "bad_password", "password_last_set": u["account"]["password_last_set"]}  # fmt: skip
    assert client.get("/ad/users/nv007", headers=agent, params={"account_type": "erp"}).status_code == 404
    assert client.get("/ad/users/khong_co", headers=agent).status_code == 404


def test_lockouts_newest_first_and_empty_list(client: TestClient, agent: dict[str, str]) -> None:
    rows = client.get("/ad/users/nv007/lockouts", headers=agent).json()
    assert [r["account_type"] for r in rows] == ["email"] * 3
    assert rows[0]["at"] > rows[1]["at"] > rows[2]["at"]
    assert client.get("/ad/users/nv002/lockouts", headers=agent).json() == []


def test_privilege_and_manager_chain(client: TestClient, agent: dict[str, str]) -> None:
    p = client.get("/ad/users/svc_backup/privilege", headers=agent).json()
    assert p["level"] == "admin" and p["is_privileged_account"] is True
    chain = client.get("/ad/users/l1_01/manager-chain", headers=agent).json()
    assert [c["user_id"] for c in chain] == ["l1_lead", "it_mgr01"]  # Phase 4 P14: l1_01 → l1_lead → it_mgr01 (chuỗi 2 cấp)
    assert client.get("/ad/users/fin_head/manager-chain", headers=agent).json() == []


def test_vpn(client: TestClient, agent: dict[str, str]) -> None:
    assert client.get("/vpn/devices/LAP-0342", headers=agent).json()["registered"] is True
    assert client.get("/vpn/devices/PC-0977", headers=agent).json()["registered"] is False
    assert client.get("/vpn/devices/KHONG-CO", headers=agent).status_code == 404
    certs = client.get("/vpn/certs/nv001", headers=agent, params={"device_id": "LAP-0342"}).json()
    assert [(c["status"], c["days_to_expiry"]) for c in certs] == [("expired", -3)]
    assert client.get("/vpn/certs/nv001", headers=agent, params={"device_id": "PC-0977"}).json() == []
    conns = client.get("/vpn/connections/nv001", headers=agent).json()
    assert conns[0]["error_code"] == "CERT_EXPIRED"
    assert client.get("/vpn/connections/nv003", headers=agent).json() == []


def test_software(client: TestClient, agent: dict[str, str]) -> None:
    zoom = client.get("/software/catalog/Zoom", headers=agent).json()
    assert zoom["paid"] is False and zoom["in_catalog"] is True
    assert client.get("/software/catalog/utorrent", headers=agent).status_code == 404
    assert client.get("/software/licenses/adobe acrobat pro", headers=agent).json()["available"] == 3
    assert client.get("/software/licenses/ms-project", headers=agent).json()["available"] == 0
    assert client.get("/software/licenses/zoom", headers=agent).json()["available"] is None
    assert client.get("/software/installed/PC-0977", headers=agent).json() == []
    assert [i["name"] for i in client.get("/software/installed/LAP-0342", headers=agent).json()] == [
        "ms-office", "zoom"]  # fmt: skip


def test_files(client: TestClient, agent: dict[str, str]) -> None:
    assert client.get("/files/resources/finance/Q3", headers=agent).json()["sensitivity"] == "high"
    assert client.get("/files/resources/khong/co", headers=agent).status_code == 404
    perms = client.get("/files/permissions/nv002", headers=agent, params={"resource_path": "finance/Q3"})
    assert [p["status"] for p in perms.json()] == ["expired"]
    assert client.get("/files/permissions/nv003", headers=agent).json() == []


def test_writes_mutate_state_and_reset_restores(client: TestClient, executor: dict[str, str],
                                                agent: dict[str, str]) -> None:  # fmt: skip
    renewed = client.post("/vpn/certs/nv001/renew", headers=executor, json={"device_id": "LAP-0342"})
    assert renewed.status_code == 200 and renewed.json()["status"] == "valid"
    statuses = [c["status"] for c in client.get("/vpn/certs/nv001", headers=agent).json()]
    assert sorted(statuses) == ["revoked", "valid"]
    ext = client.post("/files/permissions/nv002/extend", headers=executor,
                      json={"resource_path": "finance/Q3", "duration_days": 30}).json()  # fmt: skip
    assert ext["status"] == "active" and ext["previous_expires_at"] is not None
    reset = client.post("/_admin/reset")
    assert reset.status_code == 200 and reset.json()["users"] == 17  # Phase 4 P14: + l1_lead
    assert [c["status"] for c in client.get("/vpn/certs/nv001", headers=agent).json()] == ["expired"]


def test_write_business_errors(client: TestClient, executor: dict[str, str]) -> None:
    unreg = client.post("/vpn/certs/nv002/renew", headers=executor, json={"device_id": "PC-0977"})
    assert unreg.status_code == 409
    none_left = client.post("/software/licenses/ms-project/assign", headers=executor,
                            json={"user_id": "nv001"})  # fmt: skip
    assert none_left.status_code == 409
    reset = client.post("/ad/users/nv001/reset-password", headers=executor, json={})
    assert reset.status_code == 200 and "password" not in {k.lower() for k in reset.json()}


def test_devices_of_owner(client: TestClient, agent: dict[str, str]) -> None:
    rows = client.get("/vpn/devices", headers=agent, params={"owner_id": "nv002"}).json()
    assert [(d["device_id"], d["registered"]) for d in rows] == [("LAP-0417", True), ("PC-0977", False)]
    assert client.get("/vpn/devices", headers=agent, params={"owner_id": "nv006"}).json() == []
    assert client.get("/vpn/devices", headers=agent, params={"owner_id": "khong_co"}).status_code == 404
