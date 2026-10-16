"""Hợp đồng bản ghi `predictions.jsonl` v1 — T28 (runner) ghi, T29 (metrics, stats) đọc (P8 §2; duyệt ở #32 ngày 13/10).

Mỗi dòng = một **ticket lá** (D-30) của một lần chạy. Tên trường theo DB/audit. Nguồn từng trường (runner T28 lấy đúng như sau):

| Trường | Nguồn | Dùng ở (P8 §6) |
|---|---|---|
| `run_id`, `strategy`, `split` | manifest / RunConfig (P8 §5.1) | 1 file = 1 lần chạy = 1 tập; `split` chặn số calibration lọt vào bảng báo cáo |
| `scenario_id`, `family` | `id`, `family` của kịch bản | gắn gold; bootstrap theo họ (§6.4) |
| `ticket_id`, `parent_ticket_id` | `tickets` (lá: `is_parent = false`) | khoá duy nhất; nhóm lá theo yêu cầu (M1) |
| `expected_route` | `gold.expected_route` | FNR, FPR, accuracy, macro-F1, chi phí, nhãn y ECE/Brier, nhóm 70/20/10 |
| `route` | `audit_logs.detail.route` dòng điểm log 4 (KHÔNG phải cột; dòng = dưới đây) | pred §6.1; `None` = không tới M5 → ngoài mẫu số §6.1 |
| `decided_by`, `raw_prob`, `calibrated_prob`, `p_method` | cột `audit_logs` dòng điểm log 4 | ECE/Brier (chỉ `llm`): trước = `raw_prob`, sau = `calibrated_prob`, CÙNG lần chạy test |
| `final_state`, `exit_code`, `close_reason`, `resolution_path` | `tickets` (điểm log 8) | Automation, Escalation, Deflection, Giải quyết một lượt |
| `has_approval` | có dòng `approvals` của lá | Automation ("không phiếu duyệt") |
| `clarification_turns` | dòng B11 của lá (dưới đây) | Lượt hỏi lại TB (RQ3), Giải quyết một lượt |
| `intent`, `gold_intent` | `tickets.intent` của lá; `gold.intents` | Intent macro-F1 (§6.3) |
| `doc_ids`, `gold_doc_ids` | cột `audit_logs.doc_ids` dòng B8 (theo hạng); `gold.gold_doc_ids` | Recall@5, MRR@5, nDCG@5 (§6.3) |

Luật cho runner (chốt #32, 13/10; đính chính review #42):
- Dòng điểm log 4 = `audit_logs` `step = 'B13/B14'` (node `b12_assess`; event `risk_decided` hoặc `llm_layer_disabled`) — KHÔNG
  phải `step = 'B12'` (lọc `'B12'` → `route = None` cho mọi lá).
- `clarification_turns = max(detail.turn + (event == "asked"))` trên các dòng `audit_logs` `step='B11'` của lá; không có dòng B11
  → 0. `detail.turn` là số câu đã hỏi TRƯỚC lần B11 đó (b11_slots.py); dạng max không đếm đôi dòng ghi lại khi chạy lại.
  Bỏ qua dòng B11 KHÔNG có `detail.turn` (dòng của `clarify_wait` khi hết hạn / chặn injection): dạng max trong SQL tự bỏ NULL,
  code Python phải kiểm.
- Mỗi lá tối đa một lần node `b12_assess` (`S_ASSESSING` không có đường quay lại): nhiều dòng điểm log 4 (`step = 'B13/B14'`)
  cùng `route` → giữ một; khác `route` → lỗi (`ValueError`), không chọn.
- B8 nhiều dòng (chỉ khi `REDIAGNOSE_ON_NEW_SLOT`, mặc định tắt) → dòng cuối theo `created_at`. Lá không tới B8 → `doc_ids = None`.
- `intent` = `tickets.intent` của lá (lá con T20b không chạy B3 riêng).
- Kịch bản nhiều ý (lá có `parent_ticket_id`) bị `load_predictions` từ chối tới khi P8 §4.1 có `gold.leaves` (Q-T29-1).
- Độ trễ, chi phí LLM, tin/lượt (P8:369–371) KHÔNG ở đây — v2, bản ghi cấp yêu cầu gốc (M1).
- `strict=True`: `doc_ids` (JSONB) và `gold_doc_ids` (YAML) đọc ra là `list` → `model_validate` từ chối; đổi sang `tuple` hoặc
  dựng bản ghi qua JSON (`model_dump_json` / `model_validate_json` nhận mảng JSON).

Lỗi đầu vào → `ValueError` (`ValidationError` là lớp con); thông điệp nêu tên trường / số dòng, KHÔNG in giá trị dữ liệu.
"""

from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)

from app.db.models import (
    CLOSE_REASONS,
    DECIDED_BY,
    EXIT_CODES,
    FINAL_STATES,
    INTENTS,
    P_METHODS,
    RESOLUTION_PATHS,
)
from app.risk.decision_math import Route

# Alias thường (không `type X = …`): `typing.get_args` đọc được Literal — test so `Strategy` với `settings.strategy`.
Strategy = Literal["manual", "full_auto", "rule_only", "llm_only", "hybrid", "hybrid_guarded"]
Split = Literal["calibration", "test"]  # P8 §5.1 RunConfig.split

RunId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]  # P8 §5.1: sha256(...)[:12]
Id = Annotated[str, StringConstraints(min_length=1)]
Prob = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]

# Trường lấy từ cột DB → chỉ nhận giá trị DB nhận (CHECK của `audit_logs`/`tickets`, app/db/models.py).
_DB_ENUMS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "decided_by": DECIDED_BY, "p_method": P_METHODS, "final_state": FINAL_STATES, "exit_code": EXIT_CODES,
    "close_reason": CLOSE_REASONS, "resolution_path": RESOLUTION_PATHS, "intent": INTENTS,
})  # fmt: skip
_RISK_FIELDS = ("decided_by", "raw_prob", "calibrated_prob", "p_method")


class PredictionRecord(BaseModel, frozen=True, extra="forbid", strict=True, hide_input_in_errors=True):
    run_id: RunId
    strategy: Strategy
    split: Split
    scenario_id: Id
    family: Id
    ticket_id: Id
    parent_ticket_id: Id | None
    expected_route: Route
    route: Route | None
    decided_by: str | None
    raw_prob: Prob | None
    calibrated_prob: Prob | None
    p_method: str | None
    final_state: str | None
    exit_code: str | None
    close_reason: str | None
    resolution_path: str | None
    has_approval: bool
    clarification_turns: int = Field(ge=0)
    intent: str | None
    gold_intent: str | None
    doc_ids: tuple[Id, ...] | None
    gold_doc_ids: tuple[Id, ...]

    @field_validator(*_DB_ENUMS)
    @classmethod
    def _db_enum(cls, v: str | None, info: ValidationInfo) -> str | None:
        name = info.field_name or ""
        if v is not None and v not in _DB_ENUMS[name]:
            raise ValueError(f"{name}: giá trị ngoài tập DB nhận")
        return v

    @model_validator(mode="after")
    def _no_m5_no_risk(self) -> "PredictionRecord":
        if self.route is None and any(getattr(self, f) is not None for f in _RISK_FIELDS):
            raise ValueError("route = None (không tới M5): decided_by, raw_prob, calibrated_prob, p_method phải là None")
        return self


def _where(e: ValidationError) -> str:
    locs = {".".join(str(p) for p in err["loc"]) or "<bản ghi>" for err in e.errors(include_url=False, include_input=False)}
    return ", ".join(sorted(locs))


def load_predictions(path: Path) -> list[PredictionRecord]:
    """Đọc `predictions.jsonl` (giữ thứ tự dòng). Kiểm: mỗi dòng hợp lệ; 1 `run_id`, 1 `strategy`, 1 `split`; `ticket_id` không
    trùng; không lá kịch bản nhiều ý (Q-T29-1); `scenario_id` không trùng (v1: một kịch bản một bộ gold → một lá)."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("predictions: file rỗng")
    records: list[PredictionRecord] = []
    for no, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"predictions dòng {no}: dòng trống")
        try:
            records.append(PredictionRecord.model_validate_json(line))
        except ValidationError as e:
            raise ValueError(f"predictions dòng {no}: không hợp lệ ({_where(e)})") from None
    for field in ("run_id", "strategy", "split"):
        if len({getattr(r, field) for r in records}) > 1:
            raise ValueError(f"predictions: nhiều giá trị {field} trong một file (1 file = 1 lần chạy)")
    tickets: set[str] = set()
    scenarios: set[str] = set()
    for no, r in enumerate(records, start=1):
        if r.parent_ticket_id is not None:
            raise ValueError(f"predictions dòng {no}: lá của kịch bản nhiều ý — chưa có gold.leaves (Q-T29-1)")
        if r.ticket_id in tickets:
            raise ValueError(f"predictions: ticket_id trùng ở dòng {no}")
        if r.scenario_id in scenarios:
            raise ValueError(f"predictions: scenario_id trùng ở dòng {no} (v1: một kịch bản một lá)")
        tickets.add(r.ticket_id)
        scenarios.add(r.scenario_id)
    return records
