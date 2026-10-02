"""Nguồn dữ liệu của chỉ số và luật M9 (kế hoạch M9 5.3; hợp đồng mục 3; Q-M9-A1-7) + hằng N3 (Q-M9-1), hằng E1.

- `METRIC_SOURCES`: CHỈ khóa chỉ số có trong response dashboard ↔ (bảng, step, event) nguồn. Test hai chiều áp cho
  dict này. `status="pending"`: chưa có node nào ghi nguồn → chỉ số `null` + tên trong `unavailable` (không trả 0).
- `PENDING_SOURCES`: nguồn mà luật của B kiểm bằng `is_pending(...)` thay vì tự đặt chuỗi pending. Chỉ luật có nguồn
  TỪNG pending mới gọi `is_pending`; luật 11 (`policy_saved`) chạy truy vấn thật, không gọi — không thêm khóa "cho đủ".
- Khóa có ở cả hai dict (`override_count`) phải cùng trạng thái (test ghim).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

type Status = Literal["ready", "pending"]


@dataclass(frozen=True)
class MetricSource:
    tables: tuple[str, ...]
    status: Status
    step: str | None = None
    event: str | None = None
    pending_reason: str | None = None  # bắt buộc khi status="pending": chờ gì


def _ready(*tables: str, step: str | None = None, event: str | None = None) -> MetricSource:
    return MetricSource(tables=tables, status="ready", step=step, event=event)


def _pending(reason: str, *tables: str, step: str | None = None, event: str | None = None) -> MetricSource:
    return MetricSource(tables=tables, status="pending", step=step, event=event, pending_reason=reason)


METRIC_SOURCES: Mapping[str, MetricSource] = MappingProxyType({
    # ---- dashboard nghiệp vụ (kế hoạch M9 5.1, A1); A2 thêm khóa dashboard AI ----
    "automation_rate": _ready("tickets", "approvals", "escalations"),
    "escalation_rate_raw": _ready("tickets"),
    "escalation_rate_weighted": _ready("tickets", "audit_logs", step="B13/B14"),
    "deflection_rate": _ready("tickets"),
    "approval_expired_count": _ready("tickets", "approvals"),
    "decided_by_distribution": _ready("audit_logs", step="B13/B14"),
    "top_matched_rules": _ready("audit_logs", step="B13/B14"),
    "override_count": _pending("phase4d_override", "audit_logs", step="OVERRIDE", event="override_recorded"),
    "e1_split": _ready("tickets", "escalations", step="B4"),
    "e3_cases": _ready("tickets", "audit_logs"),
})  # fmt: skip

PENDING_SOURCES: Mapping[str, Status] = MappingProxyType({
    "override_count": "pending",  # Phase 4d: step OVERRIDE, event override_recorded
    "multi_intent": "pending",  # Phase 5
    "b3_cascade": "pending",  # luật 13 (Q-M9-9): cascade model → LLM là Phase 5
    "tool_spans": "pending",  # luật 5 (Q-M9-4): span tool chưa ghi bảng `spans`
    "approval_view": "ready",  # luật 7: nguồn audit B16 có từ 4c
})  # fmt: skip


def is_pending(key: str) -> bool:
    """True khi nguồn chưa có node ghi (tra `METRIC_SOURCES` và `PENDING_SOURCES`). Khóa lạ → `KeyError`
    (Q-M9-A1-9): gõ sai tên thì luật phải lỗi to tiếng, không được lặng lẽ chạy trên nguồn chưa có."""
    source = METRIC_SOURCES.get(key)
    statuses = [s for s in (source.status if source else None, PENDING_SOURCES.get(key)) if s]
    if not statuses:
        raise KeyError(f"không có trong METRIC_SOURCES/PENDING_SOURCES: {key!r}")
    return "pending" in statuses


# ---- e1_split: `escalations.reason_detail` NGUYÊN VĂN mà B3/B4 ghi (graph/nodes/b03_classify.py) ----
# Không ánh xạ sang tên event audit (`intent_out_of_scope`). reason_detail khác → E1_OTHER.
E1_REASONS: tuple[str, ...] = ("out_of_scope", "multi_intent_not_enabled", "intent_low_confidence", "intent_not_enabled")
E1_OTHER = "other"

# ---- N3: escalation rate có trọng số (decisions.md N3, Q-M9-1) — hằng MỘT chỗ ----
GROUPS: tuple[str, ...] = ("routine", "approval", "sensitive")
N3_WEIGHTS: Mapping[str, float] = MappingProxyType({"routine": 0.7, "approval": 0.2, "sensitive": 0.1})
N3_SENSITIVITY: Mapping[str, Mapping[str, float]] = MappingProxyType({
    "60/30/10": MappingProxyType({"routine": 0.6, "approval": 0.3, "sensitive": 0.1}),
    "80/15/5": MappingProxyType({"routine": 0.8, "approval": 0.15, "sensitive": 0.05}),
})  # fmt: skip
