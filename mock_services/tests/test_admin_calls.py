"""/_admin/calls + /_admin/users/{id}/status (phase3 mục 3.7, 11.5 — PLAN-3h S13): đếm ở NƠI NHẬN, kể cả request bị bơm lỗi."""

from fastapi.testclient import TestClient

RENEW = "/vpn/certs/nv001/renew"


def _count(client: TestClient, prefix: str = "/", method: str | None = None) -> int:
    params = {"path_prefix": prefix, **({"method": method} if method else {})}
    r = client.get("/_admin/calls", params=params)
    assert r.status_code == 200, r.text
    return int(r.json()["count"])


def test_write_counted_once_by_prefix_and_method(client: TestClient, agent: dict[str, str],
                                                 executor: dict[str, str]) -> None:  # fmt: skip
    assert client.post(RENEW, headers=executor, json={"device_id": "LAP-0342"}).status_code == 200
    assert client.get("/vpn/certs/nv001", headers=agent).status_code == 200
    assert _count(client, RENEW) == 1
    assert _count(client, "/vpn", "POST") == 1
    assert _count(client, "/vpn", "GET") == 1
    assert _count(client, "/vpn") == 2
    body = client.get("/_admin/calls", params={"path_prefix": RENEW}).json()
    assert body == {"count": 1, "calls": [{"method": "POST", "path": RENEW, "count": 1, "statuses": {"200": 1}}]}


def test_injected_fault_is_still_counted(client: TestClient, executor: dict[str, str]) -> None:
    """Middleware đếm nằm NGOÀI middleware bơm lỗi: lời gọi ghi bị 500 vẫn là một lời gọi đã tới hệ thống đích."""
    client.post("/_admin/faults", json={"path_prefix": "/vpn/certs/", "method": "POST", "mode": "error", "status": 500})
    assert client.post(RENEW, headers=executor, json={"device_id": "LAP-0342"}).status_code == 500
    [row] = client.get("/_admin/calls", params={"path_prefix": RENEW}).json()["calls"]
    assert (row["count"], row["statuses"]) == (1, {"500": 1})


def test_rejected_token_is_counted(client: TestClient, agent: dict[str, str]) -> None:
    assert client.post(RENEW, json={"device_id": "LAP-0342"}).status_code == 401
    assert client.post(RENEW, headers=agent, json={"device_id": "LAP-0342"}).status_code == 403
    assert _count(client, RENEW) == 2


def test_admin_and_health_not_counted(client: TestClient) -> None:
    client.get("/health")
    client.get("/_admin/faults")
    client.get("/_admin/calls")
    assert client.get("/_admin/calls").json() == {"count": 0, "calls": []}


def test_reset_calls_and_full_reset_clear_counter(client: TestClient, agent: dict[str, str]) -> None:
    client.get("/ad/users/nv001", headers=agent)
    assert _count(client) == 1
    assert client.post("/_admin/calls/reset").status_code == 200
    assert _count(client) == 0
    client.get("/ad/users/nv001", headers=agent)
    assert client.post("/_admin/reset").status_code == 200
    assert _count(client) == 0


def test_bad_query_rejected(client: TestClient) -> None:
    assert client.get("/_admin/calls", params={"path_prefix": "vpn"}).status_code == 422
    assert client.get("/_admin/calls", params={"method": "DELETE"}).status_code == 422


def test_set_employment_status_then_reset_restores(client: TestClient, agent: dict[str, str]) -> None:
    r = client.post("/_admin/users/nv001/status", json={"employment_status": "disabled"})
    assert r.json() == {"user_id": "nv001", "employment_status": "disabled"}
    assert client.get("/ad/users/nv001", headers=agent).json()["employment_status"] == "disabled"
    client.post("/_admin/reset")
    assert client.get("/ad/users/nv001", headers=agent).json()["employment_status"] == "active"


def test_set_status_rejects_unknown_user_value_and_extra_keys(client: TestClient) -> None:
    assert client.post("/_admin/users/khong_co/status", json={"employment_status": "disabled"}).status_code == 404
    assert client.post("/_admin/users/nv001/status", json={"employment_status": "fired"}).status_code == 422
    assert client.post("/_admin/users/nv001/status",
                       json={"employment_status": "disabled", "role": "admin"}).status_code == 422  # fmt: skip
    assert client.post("/_admin/faults", json={"path_prefix": "/_admin/users", "mode": "error"}).status_code == 422
