"""facts — DỮ KIỆN về thế giới cho luật M5 (phase3 mục 3.2, 3-Q1 — vá G-01).

`facts` KHÁC `slots`: slot là tham số người dùng/LLM đưa ra (có thể sai, có thể bịa) — không bao giờ là căn cứ cho luật.
Fact CHỈ do code đọc từ tool/AD ghi: B6 (`tools/diagnosis/vpn.infer_vpn`) và B11 `validate_targets` (3g). B3 đặt lại `{}`.
Danh sách ĐÓNG: key ngoài `FACT_KEYS` ở `build_action` = bug → `FactKeyViolation` → E9.

Dữ kiện về người gửi (`employment_status`, `role`) KHÔNG nằm ở đây — luật đọc qua `requester.*` của `RiskContext`.

Phase 5 T22a (phase5 mục 4.3, P2): 12 fact cho `account`, `software`, `access` — T20 cho B6 đọc từ tool (cột "Tool nguồn"). Quy ước
`requested_for` (P4, D-41): fact `target_*` mô tả NGƯỜI BỊ TÁC ĐỘNG = `Action.requested_for` (account: chủ tài khoản đích; access: người
được cấp/gia hạn/xem quyền; software, vpn: người gửi — chủ máy kiểm bằng `device_owner_is_requester`). Fact chuỗi có tập giá trị đóng
(`FACT_VALUE_SETS`) — `check_facts` kiểm như `cert_status`.
"""

from collections.abc import Mapping

# fact → kiểu (nguồn duy nhất: mục 3.2). `bool` là lớp con của `int` → kiểm kiểu chặt, không dùng isinstance.
FACT_TYPES: Mapping[str, type] = {
    "device_count": int,  # check_device_registered(user_id) không kèm máy — số máy (đăng ký hay chưa)
    "has_registered_device": bool,  # như trên — có ít nhất 1 máy registered
    "device_registered": bool,  # check_device_registered(user_id, device_id) — tồn tại và registered; 404 → false
    "device_owner_is_requester": bool,  # như trên — owner_id == người gửi; 404 → false
    "cert_status": str,  # check_vpn_cert_expiry — cert MỚI NHẤT (issued_at) của máy; không có → "none"
    "cert_days_to_expiry": int,  # như trên; âm khi đã hết hạn; không có cert → không đặt
    "last_connection_ok": bool,  # check_last_connection — lần gần nhất success; rỗng → không đặt
    # ---- Phase 5 T22a (mục 4.3): mọi fact `target_*` nói về `requested_for` (P4) ----
    "target_account_privilege": str,  # check_privilege_level.level
    "target_is_service_account": bool,  # check_account_status.is_service_account (P7)
    "target_user_status": str,  # check_account_status.employment_status
    "target_disable_reason": str,  # check_account_status.disable_reason (P7) — chỉ khi disabled
    "target_account_locked": bool,  # check_account_status.account.locked (theo account_type)
    "target_lock_reason": str,  # check_account_status.account.lock_reason — chỉ khi khoá; giá trị lạ → "other"
    "in_catalog": bool,  # check_catalog_entry.in_catalog
    "license_paid": bool,  # check_catalog_entry.paid
    "requires_local_admin": bool,  # check_catalog_entry.requires_local_admin (P7)
    "resource_sensitivity": str,  # check_resource_sensitivity.sensitivity
    "same_department": bool,  # owner_department của thư mục == phòng ban (AD) của requested_for (Q-5-4, R09)
    "has_permission_record": bool,  # check_current_permissions — có dòng quyền (còn hạn hoặc hết hạn)
    # ---- Phase 5 T20a (P1, Q-5-8, Q-T22a-8) ----
    "existing_permission_level": str,  # check_current_permissions — mức CAO NHẤT (read < write < full) mọi dòng của đúng thư mục
}
FACT_KEYS: frozenset[str] = frozenset(FACT_TYPES)
CERT_STATUSES: frozenset[str] = frozenset({"valid", "expired", "revoked", "none"})
# Tập giá trị đóng của fact chuỗi — giá trị ngoài tập = bug (đường nào đó chép chữ tự do vào facts) → FactKeyViolation.
FACT_VALUE_SETS: Mapping[str, frozenset[str]] = {
    "cert_status": CERT_STATUSES,
    "target_account_privilege": frozenset({"standard_user", "elevated", "admin"}),
    "target_user_status": frozenset({"active", "probation", "disabled", "terminated"}),
    "target_disable_reason": frozenset({"security", "other"}),
    "target_lock_reason": frozenset({"bad_password", "admin", "inactivity", "other"}),
    "resource_sensitivity": frozenset({"low", "medium", "high"}),
    "existing_permission_level": frozenset({"read", "write", "full"}),
}


class FactKeyViolation(AssertionError):
    """`facts` có key ngoài `FACT_KEYS` hoặc sai kiểu — bug (một đường nào đó đưa slot/đầu ra LLM vào facts) → E9.
    Lớp con của `AssertionError` (hợp đồng mục 3.2) nhưng raise tường minh: vẫn có hiệu lực dưới `python -O`."""


def check_facts(facts: Mapping[str, object]) -> None:
    unknown = sorted(set(facts) - FACT_KEYS)
    if unknown:
        raise FactKeyViolation(f"facts có key ngoài FACT_KEYS: {unknown}")
    for key, value in facts.items():
        if type(value) is not FACT_TYPES[key]:
            raise FactKeyViolation(f"fact {key}: kiểu {type(value).__name__}, cần {FACT_TYPES[key].__name__}")
    for key in sorted(set(facts) & set(FACT_VALUE_SETS)):
        if facts[key] not in FACT_VALUE_SETS[key]:
            raise FactKeyViolation(f"fact {key} ngoài tập giá trị")
