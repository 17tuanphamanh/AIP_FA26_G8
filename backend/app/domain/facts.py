"""facts — DỮ KIỆN về thế giới cho luật M5 (phase3 mục 3.2, 3-Q1 — vá G-01).

`facts` KHÁC `slots`: slot là tham số người dùng/LLM đưa ra (có thể sai, có thể bịa) — không bao giờ là căn cứ cho luật.
Fact CHỈ do code đọc từ tool/AD ghi: B6 (`tools/diagnosis/vpn.infer_vpn`) và B11 `validate_targets` (3g). B3 đặt lại `{}`.
Danh sách ĐÓNG: key ngoài `FACT_KEYS` ở `build_action` = bug → `FactKeyViolation` → E9.

Dữ kiện về người gửi (`employment_status`, `role`) KHÔNG nằm ở đây — luật đọc qua `requester.*` của `RiskContext`.
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
}
FACT_KEYS: frozenset[str] = frozenset(FACT_TYPES)
CERT_STATUSES: frozenset[str] = frozenset({"valid", "expired", "revoked", "none"})


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
    if "cert_status" in facts and facts["cert_status"] not in CERT_STATUSES:
        raise FactKeyViolation("fact cert_status ngoài tập giá trị")
