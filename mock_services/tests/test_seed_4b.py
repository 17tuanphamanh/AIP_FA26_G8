"""Seed mock Phase 4 chặng 4b P14 (Q-4-Q, G4-22): `l1_lead` (sếp của `l1_01`, báo cáo `it_mgr01`) + 3 máy CHƯA đăng ký cho ca xung
đột bảng 3.2 (x2 `PC-0124` của l1_01, x3 `LAP-0700` của l1_lead, x4 `LAP-0900` của it_mgr01) — khớp R17 ở mọi giờ, không cert.
Viết từ phase4 mục 5.1 P14; khuôn `test_seed.py`, `test_endpoints.py`. Chạy: `uv run pytest mock_services/tests -o pythonpath=mock_services`.
"""

import pytest
from app.seed_model import SeedData
from app.state import load_seed
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from tests.test_seed import DEMO_PASSWORD

NEW_DEVICES = {"PC-0124": "l1_01", "LAP-0700": "l1_lead", "LAP-0900": "it_mgr01"}


@pytest.fixture(scope="module")
def seed() -> SeedData:
    return load_seed()


def test_p14_l1_lead_attributes(seed: SeedData) -> None:
    users = {u.user_id: u for u in seed.users}
    lead = users["l1_lead"]
    assert (lead.username, lead.full_name, lead.title, lead.department) == (
        "khoa.dv", "Đặng Văn Khoa", "Trưởng nhóm Helpdesk", "IT")  # fmt: skip
    assert lead.groups == ["IT-Users", "IT-L1"]
    assert (lead.manager_id, lead.employment_status, lead.hired_days_ago) == ("it_mgr01", "active", 1500)
    assert lead.is_privileged_account is False
    assert lead.password_hash.startswith("$argon2id$")
    assert PasswordHasher().verify(lead.password_hash, DEMO_PASSWORD)  # cùng mật khẩu demo như mọi người trong seed


def test_p14_l1_01_reports_to_l1_lead_chain_to_it_mgr01(seed: SeedData) -> None:
    users = {u.user_id: u for u in seed.users}
    assert users["l1_01"].manager_id == "l1_lead"
    assert users["it_mgr01"].manager_id is None
    assert users["l1_02"].manager_id == "it_mgr01"  # chỉ l1_01 đổi sếp (P14)


def test_p14_new_unregistered_devices_without_certs(seed: SeedData) -> None:
    devices = {d.device_id: d for d in seed.devices}
    for device_id, owner in NEW_DEVICES.items():
        d = devices[device_id]
        assert (d.owner_id, d.registered, d.registered_days_ago) == (owner, False, None), device_id
    assert not [c for c in seed.certs if c.device_id in NEW_DEVICES]


def test_p14_manager_chain_endpoint(client: TestClient, agent: dict[str, str]) -> None:
    chain = client.get("/ad/users/l1_01/manager-chain", headers=agent).json()
    assert [c["user_id"] for c in chain] == ["l1_lead", "it_mgr01"]
    assert [c["user_id"] for c in client.get("/ad/users/l1_lead/manager-chain", headers=agent).json()] == ["it_mgr01"]


def test_p14_new_devices_via_vpn_endpoints(client: TestClient, agent: dict[str, str]) -> None:
    for device_id, owner in NEW_DEVICES.items():
        dev = client.get(f"/vpn/devices/{device_id}", headers=agent).json()
        assert (dev["owner_id"], dev["registered"]) == (owner, False), device_id
        assert client.get(f"/vpn/certs/{owner}", headers=agent, params={"device_id": device_id}).json() == []


def test_p14_l1_lead_authenticates_with_demo_password(client: TestClient, agent: dict[str, str]) -> None:
    r = client.post("/ad/authenticate", headers=agent, json={"username": "khoa.dv", "password": DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == "l1_lead"
