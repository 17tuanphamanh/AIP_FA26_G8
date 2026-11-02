"""Chẩn đoán VPN (phase3 mục 9.4, 9.5; 3-Q8, 3-Q38) — bộ lời gọi 3 tool đọc + `infer_vpn` (hàm thuần).

`infer_vpn` đọc DUY NHẤT dữ liệu tool (`DeviceList`, `CertList`, `ConnectionList`; `None` = 404/rỗng = dữ liệu hợp lệ):

- Người dùng KHÔNG nêu máy → `device_count`, `has_registered_device`; có ĐÚNG 1 máy (đăng ký hay chưa) mới tự suy
  `device_id`; ≥ 2 máy → không suy (B11 hỏi).
- Có máy (nêu hoặc suy) → `device_registered` (tồn tại và registered; 404 → false), `device_owner_is_requester`
  (`owner_id == người gửi`; 404 → false), `cert_status`/`cert_days_to_expiry` của cert MỚI NHẤT theo `issued_at`
  (`check_vpn_cert_expiry` chỉ trả cert của CHÍNH người gửi → máy của người khác luôn `"none"`).
- Chỉ khi máy là của người gửi mới tự đặt `action`: expired → `renew_vpn_cert`, revoked → `reissue_vpn_access`. Máy của
  người khác KHÔNG BAO GIỜ tự sinh hành động (G-02).
- `last_connection_ok`: lần kết nối MỚI NHẤT (theo `at`, không tin thứ tự trả về) là `success`; rỗng → không đặt.

Phần MÁY tách thành `device_facts` (T20a P3, TQ-4) — dùng chung với `software.infer_software`; hành vi VPN không đổi.

`device_id` (có thể do người dùng nêu) chỉ là KHOÁ TRA CỨU — không bao giờ là giá trị của một fact; `slots` trả về chỉ để
B6 bổ sung slot người dùng chưa nêu. Test AST P3 (`test_facts_ast.py`): không phép gán `facts[...]` nào lấy từ slot.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from app.domain.facts import FACT_KEYS
from app.tools.models import CertList, ConnectionList, Device, DeviceList
from app.tools.specs import REGISTRY

TOOLS = ("check_device_registered", "check_vpn_cert_expiry", "check_last_connection")  # = tools.specs.TOOL_MAP["vpn"]
ACTION_BY_CERT = {"expired": "renew_vpn_cert", "revoked": "reissue_vpn_access"}
# 3g (P6 (a)): fact phụ thuộc MÁY — B11 `validate_targets` bỏ hết giá trị cũ rồi tính lại cho `slots.device_id`. Fact theo
# NGƯỜI (`device_count`, `has_registered_device`, `last_connection_ok`) giữ nguyên.
DEVICE_FACTS = frozenset({"device_registered", "device_owner_is_requester", "cert_status", "cert_days_to_expiry"})
# Tool đọc có `device_id` trong `arg_slots` (`tools.specs`, D-20) — `validate_targets` chỉ gọi đúng các tool này.
TARGET_TOOLS = tuple(t for t in TOOLS if "device_id" in REGISTRY[t].arg_slots)


def calls(requester_id: str, device_id: str | None) -> list[tuple[str, dict[str, str]]]:
    """3 lời gọi của B6 — `device_id` tuỳ chọn (3-Q8): không có → tra theo người gửi."""
    args = {"user_id": requester_id, **({"device_id": device_id} if device_id else {})}
    return [
        ("check_device_registered", args),
        ("check_vpn_cert_expiry", args),
        ("check_last_connection", {"user_id": requester_id}),
    ]


def target_calls(requester_id: str, device_id: str) -> list[tuple[str, dict[str, str]]]:
    """B11 `validate_targets` (3g, P6 (a)): chỉ tool nhận `device_id` — `check_device_registered`, `check_vpn_cert_expiry`."""
    return [(t, {"user_id": requester_id, "device_id": device_id}) for t in TARGET_TOOLS]


def device_facts(
    devices: Sequence[Device], *, requester_id: str, device_id: str | None, allow_infer: bool = True
) -> tuple[dict[str, str], dict[str, str | int | bool]]:
    """T20a P3 (TQ-4): phần MÁY của `infer_vpn`, dùng chung với `infer_software` — `devices` = đầu ra `check_device_registered`
    (rỗng khi 404). Không nêu máy → `device_count`, `has_registered_device`; ĐÚNG 1 máy mới suy slot `device_id` (≥ 2 → để B11 hỏi).
    Có máy (nêu hoặc suy) → `device_registered` (tồn tại và registered), `device_owner_is_requester` (`owner_id == người gửi`).
    be-target-guard-2: `allow_infer=False` (cờ `target_is_other` bật — câu nhắm máy NGƯỜI KHÁC) → KHÔNG suy máy duy nhất của người gửi;
    vẫn đặt fact theo người (`device_count`, `has_registered_device`)."""
    slots: dict[str, str] = {}
    facts: dict[str, str | int | bool] = {}
    if device_id is None:  # tra theo người: danh sách máy của chính họ
        facts["device_count"] = len(devices)
        facts["has_registered_device"] = any(d.registered for d in devices)
        if len(devices) == 1 and allow_infer:  # ĐÚNG 1 máy mới tự suy; ≥ 2 hoặc cờ người khác → để B11 hỏi
            device_id = devices[0].device_id
            slots["device_id"] = device_id
    if device_id is not None:
        dev = next((d for d in devices if d.device_id == device_id), None)
        facts["device_registered"] = dev is not None and dev.registered
        facts["device_owner_is_requester"] = dev is not None and dev.owner_id == requester_id
    return slots, facts


def infer_vpn(
    diag: Mapping[str, Any], *, requester_id: str, device_id: str | None, allow_infer: bool = True
) -> tuple[dict[str, str], dict[str, str | int | bool]]:
    devices = diag["check_device_registered"].root if isinstance(diag["check_device_registered"], DeviceList) else []
    certs = diag["check_vpn_cert_expiry"].root if isinstance(diag["check_vpn_cert_expiry"], CertList) else []
    conns = diag["check_last_connection"].root if isinstance(diag["check_last_connection"], ConnectionList) else []
    slots, facts = device_facts(devices, requester_id=requester_id, device_id=device_id, allow_infer=allow_infer)
    device_id = slots.get("device_id", device_id)
    if device_id is not None:
        mine = sorted((c for c in certs if c.device_id == device_id), key=lambda c: c.issued_at, reverse=True)
        facts["cert_status"] = mine[0].status if mine else "none"
        if mine:
            facts["cert_days_to_expiry"] = mine[0].days_to_expiry
        if facts["device_owner_is_requester"] and (action := ACTION_BY_CERT.get(str(facts["cert_status"]))):
            slots["action"] = action
    if conns:
        facts["last_connection_ok"] = max(conns, key=lambda c: c.at).result == "success"
    assert set(facts) <= FACT_KEYS  # hợp đồng nội bộ; build_action kiểm lại bằng FactKeyViolation
    return slots, facts
