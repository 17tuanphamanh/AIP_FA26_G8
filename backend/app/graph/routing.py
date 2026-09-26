"""ROUTES — tập đích hợp lệ của TỪNG node [Chốt: định tuyến riêng từng node] (P1 mục 5).

Tên node lấy từ mã giả các file nhánh; bước con nằm trong node như đặc tả (B4, B5 trong
`b03_classify`; B7 trong `b06_diagnose`; B9 trong `b08_retrieve`; B13–B14 trong `b12_assess`; B16 trong
`approval_wait`; B18 trong `b17_execute`; B19 là `confirm_wait`).

`b20_audit` được thêm vào đích của MỌI node: boundary E9 (và mọi lối thoát) đi về B20 (bất biến 4).
Đích D-20 (`b06_diagnose` từ `b11_slots`/`clarify_wait`, `b11_slots` từ `b06_diagnose`) luôn có trong
bảng; chuyển `S_CLARIFYING → S_DIAGNOSING` chỉ qua được `goto` khi cờ REDIAGNOSE_ON_NEW_SLOT bật.
"""

from collections.abc import Mapping
from typing import Any, Final

from langgraph.graph import END

ENTRY: Final = "b01_identity"
AUDIT: Final = "b20_audit"

_ROUTES: Final[dict[str, tuple[str, ...]]] = {
    "b01_identity": ("b02_screen",),
    "b02_screen": ("b03_classify",),
    "b03_classify": ("b06_diagnose", "parent_wait"),
    "b06_diagnose": ("b08_retrieve", "b11_slots"),
    "b08_retrieve": ("b10_route",),
    "b10_route": ("b11_slots", "confirm_wait"),
    "b11_slots": ("b12_assess", "clarify_wait", "b06_diagnose"),
    "clarify_wait": ("b11_slots", "b06_diagnose"),
    "b12_assess": ("b17_execute", "b15_prepare_approval"),
    "b15_prepare_approval": ("approval_wait",),
    "approval_wait": ("b17_execute",),
    "b17_execute": ("confirm_wait",),
    "confirm_wait": (),
    "parent_wait": ("parent_wait", "parent_reply_wait"),
    "parent_reply_wait": ("parent_wait",),
}

ROUTES: Final[Mapping[str, frozenset[str]]] = {
    **{name: frozenset({*targets, AUDIT}) for name, targets in _ROUTES.items()},
    AUDIT: frozenset({END}),
}

# Node chờ người: dừng bằng interrupt() (D-08). Trạng thái lúc chờ + bước ghi audit `late_event`.
WAIT_NODES: Final[Mapping[str, str]] = {
    "clarify_wait": "B11",
    "approval_wait": "B16",
    "confirm_wait": "B19",
    "parent_wait": "B5",
    "parent_reply_wait": "B5",
}


def route_next(state: Mapping[str, Any]) -> str:
    """Đi theo `next` do goto() đặt — KHÔNG route theo status (P1 mục 5)."""
    return str(state["next"])
