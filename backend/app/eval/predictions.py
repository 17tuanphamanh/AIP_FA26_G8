"""Hợp đồng bản ghi `predictions.jsonl` v1.1 — runner G2 ghi, T29 (metrics, stats) và offline đọc (P8 §2; v1 duyệt ở #32 ngày 13/10;
v1.1 = P8 v1.4 §5.6, giao Dương ở #32 ngày 18/10).

Mỗi dòng = một **ticket lá** (D-30) của một lần chạy. Tên trường theo DB/audit. Nguồn từng trường (runner T28 lấy đúng như sau):

| Trường | Nguồn | Dùng ở (P8 §6) |
|---|---|---|
| `run_id`, `strategy`, `split` | manifest / RunConfig (P8 §5.1) | 1 file = 1 lần chạy = 1 tập; `split` chặn số calibration lọt vào bảng báo cáo |
| `scenario_id`, `family` | `id`, `family` của kịch bản | gắn gold; bootstrap theo họ (§6.4) |
| `ticket_id`, `parent_ticket_id` | `tickets` (lá: `is_parent = false`) | khoá duy nhất; nhóm lá theo yêu cầu (M1) |
| `expected_route` | `gold.expected_route`; `None` = chưa nhãn (G2-Q22) | FNR, FPR, accuracy, macro-F1, chi phí, nhãn y ECE/Brier, nhóm 70/20/10 — metrics bỏ qua lá `None` + đếm `n_unlabeled` |
| `route` | `audit_logs.detail.route` dòng điểm log 4 (KHÔNG phải cột; dòng = dưới đây) | pred §6.1; `None` = không tới M5 → ngoài mẫu số §6.1 |
| `decided_by`, `raw_prob`, `calibrated_prob`, `p_method` | cột `audit_logs` dòng điểm log 4 | ECE/Brier (chỉ `llm`): trước = `raw_prob`, sau = `calibrated_prob`, CÙNG lần chạy test |
| `final_state`, `exit_code`, `close_reason`, `resolution_path` | `tickets` (điểm log 8) | Automation, Escalation, Deflection, Giải quyết một lượt |
| `has_approval` | có dòng `approvals` của lá | Automation ("không phiếu duyệt") |
| `clarification_turns` | dòng B11 của lá (dưới đây) | Lượt hỏi lại TB (RQ3), Giải quyết một lượt |
| `intent`, `gold_intent` | `tickets.intent` của lá; `gold.intents` | Intent macro-F1 (§6.3) |
| `doc_ids`, `gold_doc_ids` | cột `audit_logs.doc_ids` dòng B8 (theo hạng); `gold.gold_doc_ids` | Recall@5, MRR@5, nDCG@5 (§6.3) |

v1.1 (P8 v1.4 §5.6) — mọi trường BẮT BUỘC có mặt, không mặc định; chưa có nguồn hợp lệ → runner ghi `null` tường minh và liệt kê
tên ở manifest `predictions_unavailable` (không ghi False giả):

| Trường | Nguồn | Dùng ở (P8 v1.4) |
|---|---|---|
| `schema_version` | `"1.1"`; thiếu = file v1 → `load_predictions` từ chối (V11-Q6) | đọc file |
| `fold` | 1..`CV_K`, họ → phần ở `SPLIT.md` (§2, §4.3) — chưa có `split.py`; lượt stack ghi `null` (G2-Q3, V11-Q3). Một file: mọi dòng có `fold` hoặc không dòng nào; một họ một phần | §4.3, §5.3 `fit_fold`, §6.1 gộp 5 phần đo |
| `kb_gap` | audit B10 `detail.grounding.kb_gap` (P6 22/10), CHỈ ca đi lớp LLM (`decided_by = llm`); không có dòng → `null` (manifest đếm `kb_gap_missing`). Như trường rủi ro: `route = None` ⇒ `None` | §5.3 chặn AUTO khi tính route offline (D-34), §5.4 |
| `hidden_factor` | `gold.hidden_factor` (§4.1) — dữ liệu thật CHƯA có khoá này → `null` (V11-Q1) | §6.1 FNR nhóm yếu tố M5 không thấy (ghi nợ, chưa tính) |
| `run_started_at` | giờ bắt đầu TỪNG kịch bản của harness (= `outcomes.jsonl`; không phải giờ bắt đầu lượt ở manifest), ISO 8601 CÓ offset | §5.2 khung giờ, manifest số ca theo khung |
| `in_business_hours` | khung giờ hành chính của `run_started_at` theo `business_hours` — việc G7 (G2-Q10, V11-Q5) → `null` tới G7 | §5.2 |
| `m5_aborted` | audit của lớp bọc lỗi (`graph/boundary.py`): `True` khi ticket có dòng `event ∈ {turn_budget_exceeded, unhandled_exception}` với `from_status = S_ASSESSING` (M5 bị ngắt giữa chừng); có audit mà không có dòng đó → `False`; ticket không có dòng audit nào → `null` (manifest đếm `m5_aborted_unknown`) | §5.4 "ca không tới điểm log 4": `route = None` ∧ `True` → ESCALATE_L2; ∧ `False` → ngoài mẫu số; lá đã nhãn ∧ `null` → DỪNG (`m5_outcome`) |

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
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
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
SchemaVersion = Literal["1.1"]
SCHEMA_VERSION: Final[SchemaVersion] = "1.1"
CV_K: Final = 5  # P8 §8 `CV_K` — số phần kiểm tra chéo (§4.3)

RunId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{12}$")]  # P8 §5.1: sha256(...)[:12]
Id = Annotated[str, StringConstraints(min_length=1)]
Prob = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
Fold = Annotated[int, Field(ge=1, le=CV_K)]


def _aware_iso(v: str) -> str:
    """ISO 8601 có offset; giữ nguyên chuỗi. Lỗi không in giá trị."""
    try:
        t = datetime.fromisoformat(v)
    except ValueError:
        raise ValueError("phải là ISO 8601") from None
    if t.tzinfo is None:
        raise ValueError("thiếu múi giờ (cần offset, vd +07:00)")
    return v


AwareIso = Annotated[str, AfterValidator(_aware_iso)]

# Trường lấy từ cột DB → chỉ nhận giá trị DB nhận (CHECK của `audit_logs`/`tickets`, app/db/models.py).
_DB_ENUMS: Mapping[str, tuple[str, ...]] = MappingProxyType({
    "decided_by": DECIDED_BY, "p_method": P_METHODS, "final_state": FINAL_STATES, "exit_code": EXIT_CODES,
    "close_reason": CLOSE_REASONS, "resolution_path": RESOLUTION_PATHS, "intent": INTENTS,
})  # fmt: skip
_RISK_FIELDS = ("decided_by", "raw_prob", "calibrated_prob", "p_method", "kb_gap")  # trường điểm log 4 (kb_gap: P8 §0.1)


class PredictionRecord(BaseModel, frozen=True, extra="forbid", strict=True, hide_input_in_errors=True):
    run_id: RunId
    strategy: Strategy
    split: Split
    scenario_id: Id
    family: Id
    ticket_id: Id
    parent_ticket_id: Id | None
    expected_route: Route | None  # None = kịch bản CHƯA NHÃN (dữ liệu thật tới 25/10 — G2-schema, G2-Q22)
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
    schema_version: SchemaVersion
    fold: Fold | None
    kb_gap: bool | None
    hidden_factor: bool | None
    run_started_at: AwareIso
    in_business_hours: bool | None
    m5_aborted: bool | None

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
            raise ValueError("route = None (không tới M5): decided_by, raw_prob, calibrated_prob, p_method, kb_gap phải là None")
        return self


type M5Outcome = Literal["log4", "aborted", "out"]


def m5_outcome(r: PredictionRecord) -> M5Outcome:
    """P8 §5.4 [Chốt 22/10] — MỘT quy tắc cho `offline.py` và `report.py` (mẫu số các phương án giống nhau):
    `log4` = lá có route (đã tới điểm log 4); `aborted` = `route = None` ∧ `m5_aborted` (M5 bị ngắt: hết hạn lượt / lỗi không lường tại
    `S_ASSESSING`) → tính ESCALATE_L2 với phương án có LLM; `out` = `route = None` ∧ không ngắt (E1, lỗi ở bước khác, kẹt B11…) → ngoài mẫu
    số §6.1. Lá chưa nhãn → `out`. Lá đã nhãn, `route = None`, `m5_aborted = None` → `ValueError` (không đoán)."""
    if r.route is not None:
        return "log4"
    if r.expected_route is None:
        return "out"
    if r.m5_aborted is None:
        raise ValueError("m5_aborted null ở lá đã nhãn không có route — collector phải điền m5_aborted (P8 §5.4)")
    return "aborted" if r.m5_aborted else "out"


def _where(e: ValidationError) -> str:
    locs = {".".join(str(p) for p in err["loc"]) or "<bản ghi>" for err in e.errors(include_url=False, include_input=False)}
    return ", ".join(sorted(locs))


def _is_v1(e: ValidationError) -> bool:
    return any(err["type"] == "missing" and tuple(err["loc"]) == ("schema_version",)
               for err in e.errors(include_url=False, include_input=False))  # fmt: skip


def load_predictions(path: Path) -> list[PredictionRecord]:
    """Đọc `predictions.jsonl` (giữ thứ tự dòng). Kiểm: mỗi dòng hợp lệ v1.1 (dòng v1 — không có `schema_version` — bị từ chối,
    không điền mặc định); 1 `run_id`, 1 `strategy`, 1 `split`; `ticket_id` không trùng; không lá kịch bản nhiều ý (Q-T29-1);
    `scenario_id` không trùng (v1: một kịch bản một bộ gold → một lá); `fold` có ở mọi dòng hoặc không dòng nào, một họ một phần
    (P8 §4.3)."""
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
            if _is_v1(e):
                raise ValueError(f"predictions dòng {no}: bản v1 (không có schema_version) — hợp đồng v{SCHEMA_VERSION} không đọc "
                                 "file v1; chạy lại harness") from None  # fmt: skip
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
    folded = [r.fold is not None for r in records]
    if any(folded) and not all(folded):
        raise ValueError("predictions: fold gán dở (một file: mọi dòng có fold hoặc không dòng nào)")
    fold_of: dict[str, int] = {}
    for no, r in enumerate(records, start=1):
        if r.fold is not None and fold_of.setdefault(r.family, r.fold) != r.fold:
            raise ValueError(f"predictions dòng {no}: một họ (family) nằm ở hai phần fold khác nhau (P8 §4.3)")
    return records
