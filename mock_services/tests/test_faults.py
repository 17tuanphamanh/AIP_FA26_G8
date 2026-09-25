"""/_admin/faults [Chốt P5 mục 7]: bật 500/429/timeout/latency theo endpoint, tắt được."""

import time

from fastapi.testclient import TestClient


def test_error_fault_on_prefix_then_clear(client: TestClient, agent: dict[str, str]) -> None:
    created = client.post("/_admin/faults", json={"path_prefix": "/ad", "mode": "error", "status": 500})
    assert created.status_code == 201
    assert client.get("/ad/users/nv001", headers=agent).status_code == 500
    assert client.get("/vpn/devices/LAP-0342", headers=agent).status_code == 200  # hệ thống khác
    assert client.get("/health").status_code == 200
    assert client.delete("/_admin/faults").status_code == 200
    assert client.get("/ad/users/nv001", headers=agent).status_code == 200


def test_fault_limited_times_and_429(client: TestClient, agent: dict[str, str]) -> None:
    client.post("/_admin/faults", json={"path_prefix": "/software", "mode": "error", "status": 429,
                                         "times": 2})  # fmt: skip
    codes = [client.get("/software/catalog/zoom", headers=agent).status_code for _ in range(3)]
    assert codes == [429, 429, 200]
    assert client.get("/_admin/faults").json() == []


def test_method_filter(client: TestClient, agent: dict[str, str], executor: dict[str, str]) -> None:
    client.post("/_admin/faults", json={"path_prefix": "/vpn", "method": "POST", "mode": "error"})
    assert client.get("/vpn/devices/LAP-0342", headers=agent).status_code == 200
    assert client.post("/vpn/certs/nv001/renew", headers=executor,
                       json={"device_id": "LAP-0342"}).status_code == 500  # fmt: skip


def test_timeout_and_latency(client: TestClient, agent: dict[str, str]) -> None:
    client.post("/_admin/faults", json={"path_prefix": "/files", "mode": "timeout", "delay_ms": 50,
                                         "times": 1})  # fmt: skip
    assert client.get("/files/resources/finance/Q3", headers=agent).status_code == 504
    client.post("/_admin/faults", json={"path_prefix": "/files", "mode": "latency", "delay_ms": 150,
                                         "times": 1})  # fmt: skip
    start = time.perf_counter()
    assert client.get("/files/resources/finance/Q3", headers=agent).status_code == 200
    assert time.perf_counter() - start >= 0.15


def test_remove_one_and_admin_is_not_faultable(client: TestClient, agent: dict[str, str]) -> None:
    fid = client.post("/_admin/faults", json={"path_prefix": "/ad", "mode": "error"}).json()["fault_id"]
    assert client.delete(f"/_admin/faults/{fid}").status_code == 200
    assert client.delete(f"/_admin/faults/{fid}").status_code == 404
    assert client.post("/_admin/faults", json={"path_prefix": "/_admin", "mode": "error"}).status_code == 422
    assert client.post("/_admin/faults", json={"path_prefix": "/health", "mode": "error"}).status_code == 422


def test_reset_clears_faults(client: TestClient, agent: dict[str, str]) -> None:
    client.post("/_admin/faults", json={"path_prefix": "/ad", "mode": "error"})
    client.post("/_admin/reset")
    assert client.get("/ad/users/nv001", headers=agent).status_code == 200
