"""f3 — `tools/diagnosis/vpn.infer_vpn` (phase3 mục 9.5; 9.6 f3): 0 / 1 / 2 máy; máy của người khác; máy không tồn tại;
cert expired / revoked / valid / none; cert MỚI NHẤT theo `issued_at`; kết nối mới nhất theo `at`. Hàm thuần — dữ liệu
dựng bằng model tool thật (`DeviceList`, `CertList`, `ConnectionList`), `None` = 404/rỗng.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.domain.facts import FACT_KEYS, check_facts
from app.tools.diagnosis.vpn import TOOLS, calls, infer_vpn
from app.tools.models import (
    Cert,
    CertList,
    Connection,
    ConnectionList,
    Device,
    DeviceList,
)
from app.tools.specs import TOOL_MAP

NOW = datetime(2026, 9, 29, tzinfo=UTC)
ME, OTHER = "nv001", "nv002"


def dev(device_id: str, owner: str = ME, registered: bool = True) -> Device:
    return Device(device_id=device_id, owner_id=owner, kind="laptop", os="Windows 11", registered=registered,
                  registered_at=NOW - timedelta(days=100) if registered else None)  # fmt: skip


def cert(device_id: str, status: str, *, issued_days_ago: int = 100, days: int = 30, serial: str = "S") -> Cert:
    return Cert(serial=f"{serial}-{device_id}-{issued_days_ago}", device_id=device_id,
                issued_at=NOW - timedelta(days=issued_days_ago), expires_at=NOW + timedelta(days=days),
                status=status, days_to_expiry=days)  # type: ignore[arg-type]  # fmt: skip


def conn(result: str, days_ago: float, device_id: str = "LAP-0342") -> Connection:
    return Connection(at=NOW - timedelta(days=days_ago), device_id=device_id, result=result,  # type: ignore[arg-type]
                      error_code=None if result == "success" else "CERT_EXPIRED")  # fmt: skip


def diag(devices: list[Device] | None = None, certs: list[Cert] | None = None,
         conns: list[Connection] | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "check_device_registered": DeviceList(devices) if devices else None,
        "check_vpn_cert_expiry": CertList(certs) if certs else None,
        "check_last_connection": ConnectionList(conns) if conns else None,
    }


def run(d: dict[str, Any], device_id: str | None = None) -> tuple[dict[str, str], dict[str, Any]]:
    slots, facts = infer_vpn(d, requester_id=ME, device_id=device_id)
    check_facts(facts)  # đúng key + đúng kiểu (FactKeyViolation nếu không)
    return slots, facts


def test_tools_match_tool_map_and_calls() -> None:
    assert TOOLS == TOOL_MAP["vpn"]
    assert calls(ME, None) == [
        ("check_device_registered", {"user_id": ME}), ("check_vpn_cert_expiry", {"user_id": ME}),
        ("check_last_connection", {"user_id": ME}),
    ]  # fmt: skip
    assert calls(ME, "LAP-0417")[:2] == [
        ("check_device_registered", {"user_id": ME, "device_id": "LAP-0417"}),
        ("check_vpn_cert_expiry", {"user_id": ME, "device_id": "LAP-0417"}),
    ]  # fmt: skip


# ---- không nêu máy: 0 / 1 / 2 máy ----------------------------------------------------------------------------------


def test_f3_zero_devices() -> None:
    slots, facts = run(diag())
    assert slots == {} and facts == {"device_count": 0, "has_registered_device": False}


def test_f3_one_device_expired_cert_infers_device_and_renew() -> None:
    slots, facts = run(diag([dev("LAP-0342")], [cert("LAP-0342", "expired", days=-3)],
                            [conn("failed", 0.1), conn("success", 4)]))  # fmt: skip
    assert slots == {"device_id": "LAP-0342", "action": "renew_vpn_cert"}
    assert facts == {
        "device_count": 1, "has_registered_device": True, "device_registered": True,
        "device_owner_is_requester": True, "cert_status": "expired", "cert_days_to_expiry": -3,
        "last_connection_ok": False,
    }  # fmt: skip


def test_f3_one_device_revoked_cert_reissue() -> None:
    slots, facts = run(diag([dev("LAP-0610")], [cert("LAP-0610", "revoked", days=65)]))
    assert slots == {"device_id": "LAP-0610", "action": "reissue_vpn_access"}
    assert facts["cert_status"] == "revoked"


def test_f3_one_device_valid_cert_no_action() -> None:
    slots, facts = run(diag([dev("LAP-0417")], [cert("LAP-0417", "valid", days=200)], [conn("success", 1)]))
    assert slots == {"device_id": "LAP-0417"} and facts["cert_status"] == "valid"
    assert facts["last_connection_ok"] is True


def test_f3_one_unregistered_device_is_inferred_but_not_registered() -> None:
    slots, facts = run(diag([dev("PC-0977", registered=False)]))
    assert slots == {"device_id": "PC-0977"}  # ĐÚNG 1 máy (đăng ký hay chưa) mới suy
    assert (facts["has_registered_device"], facts["device_registered"], facts["cert_status"]) == (False, False, "none")
    assert "cert_days_to_expiry" not in facts


def test_f3_two_devices_never_inferred() -> None:  # M-3f-4
    slots, facts = run(diag([dev("LAP-0417"), dev("PC-0977", registered=False)], [cert("LAP-0417", "expired")]))
    assert slots == {}
    assert facts == {"device_count": 2, "has_registered_device": True}
    assert not ({"device_registered", "device_owner_is_requester", "cert_status"} & set(facts))


# ---- có nêu máy ----------------------------------------------------------------------------------------------------


def test_f3_other_persons_device_owner_false_no_action() -> None:  # M-3f-3, M-3f-9 (G-02)
    # cert của người gửi không có cho máy đó (tool chỉ trả cert của chính người gửi) — kể cả cert người gửi bị hết hạn
    slots, facts = run(diag([dev("LAP-0417", owner=OTHER)], [cert("LAP-0342", "expired", days=-3)]), "LAP-0417")
    assert slots == {}
    assert facts == {"device_registered": True, "device_owner_is_requester": False, "cert_status": "none"}


def test_f3_other_persons_device_never_gets_action_even_if_cert_shows_expired() -> None:  # M-3f-9
    """Phòng thủ: dữ liệu bất thường (cert trùng device_id của máy người khác) vẫn không tự sinh hành động."""
    slots, facts = run(diag([dev("LAP-0417", owner=OTHER)], [cert("LAP-0417", "expired", days=-1)]), "LAP-0417")
    assert "action" not in slots and facts["device_owner_is_requester"] is False


def test_f3_nonexistent_device_not_registered() -> None:  # M-3f-5
    slots, facts = run(diag(), "LAP-9999")
    assert slots == {}
    assert facts == {"device_registered": False, "device_owner_is_requester": False, "cert_status": "none"}


def test_f3_named_own_device_expired() -> None:
    slots, facts = run(diag([dev("LAP-0342")], [cert("LAP-0342", "expired", days=-3)]), "LAP-0342")
    assert slots == {"action": "renew_vpn_cert"}  # device_id đã do người dùng nêu — không trả lại
    assert (facts["device_registered"], facts["device_owner_is_requester"]) == (True, True)
    assert "device_count" not in facts  # tra theo máy, không theo người


# ---- cert mới nhất, kết nối mới nhất -------------------------------------------------------------------------------


@pytest.mark.parametrize(("newest", "action"), [("valid", None), ("expired", "renew_vpn_cert"),
                                                ("revoked", "reissue_vpn_access")])  # fmt: skip
def test_f3_newest_cert_by_issued_at_wins(newest: str, action: str | None) -> None:
    old = cert("LAP-0342", "revoked" if newest != "revoked" else "valid", issued_days_ago=400, serial="OLD")
    new = cert("LAP-0342", newest, issued_days_ago=10, serial="NEW")
    for certs in ([old, new], [new, old]):  # không tin thứ tự trả về
        slots, facts = run(diag([dev("LAP-0342")], certs))
        assert facts["cert_status"] == newest and slots.get("action") == action


def test_f3_last_connection_by_time_not_order() -> None:
    _, facts = run(diag([dev("LAP-0342")], None, [conn("success", 5), conn("failed", 0.2)]))
    assert facts["last_connection_ok"] is False
    _, facts = run(diag([dev("LAP-0342")], None, [conn("failed", 5), conn("success", 0.2)]))
    assert facts["last_connection_ok"] is True


def test_f3_facts_only_known_keys_and_types() -> None:
    for d, device_id in [(diag(), None), (diag([dev("A-100")]), None), (diag(), "LAP-9999"),
                         (diag([dev("LAP-0342")], [cert("LAP-0342", "expired")], [conn("success", 1)]), None)]:  # fmt: skip
        _, facts = run(d, device_id)
        assert set(facts) <= FACT_KEYS
