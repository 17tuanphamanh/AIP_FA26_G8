"""Trường thêm của hợp đồng `predictions.jsonl` v1.1 (P8 v1.4 §5.6) — giá trị mặc định cho các bộ dựng bản ghi tổng hợp của test.

Như runner ghi ở lượt stack: `fold`, `hidden_factor`, `in_business_hours` = `None` (chưa có nguồn — liệt kê ở manifest
`predictions_unavailable`); `run_started_at` = giờ bắt đầu kịch bản (ISO 8601 có offset).
"""

from types import MappingProxyType
from typing import Any

V11: MappingProxyType[str, Any] = MappingProxyType({
    "schema_version": "1.1", "fold": None, "kb_gap": None, "hidden_factor": None,
    "run_started_at": "2026-10-19T10:00:00+07:00", "in_business_hours": None, "m5_aborted": None,
})  # fmt: skip
