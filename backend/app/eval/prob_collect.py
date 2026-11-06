"""G10 nối mốc G — dựng đầu vào cho `scripts/eval/prob_variants.py collect-no-evidence` từ một lượt harness + DB (chỉ đọc).

Nguồn (mỗi ca đi lớp LLM của lượt):
- **Chọn ca / WITH**: `predictions.jsonl` của lượt (`load_predictions`): ca `decided_by == "llm"`, có `route` và `raw_prob`; ca CHƯA NHÃN
  (`expected_route` null) bị bỏ + đếm; ca `llm` có route mà `raw_prob` null không vào danh sách (như trước) và được đếm `llm_no_raw_prob`. WITH = `{scenario_id, family, split, gold_route = expected_route, raw_prob, kb_gap}`.
- **kb_gap**: `audit_logs.detail->>'kb_gap'` của dòng `step = 'B13/B14'` — ĐÚNG giá trị đã truyền vào `decide()` (`b12_assess.py`, ca LLM).
  KHÔNG dùng `grounding.kb_gap` của B10 (nghĩa khác: điểm truy hồi dưới ngưỡng). Thiếu khoá → bỏ ca (lý do `no_kb_gap`), không đoán.
- **raw_prob / p_method** của audit phải khớp bản ghi dự đoán / `--p-method`: lệch p_method → `CollectError` cả lượt (so sánh biến thể
  chỉ có nghĩa khi cùng cách lấy xác suất); lệch raw_prob → bỏ ca (`raw_prob_mismatch`).
- **Action / RiskContext**: từ checkpoint LangGraph của ticket (`intended_action`, `requester_context`, `ctx_flags`), dựng bằng chính
  `risk.context.build_ctx` (một nguồn logic) với `now` = `created_at` của dòng audit B13/B14 và `business_hours` đọc từ `policy.json` trong
  `config_dir` (không `get_policy()` — nó đọc `Settings()` có `.env`). `within_business_hours` có thể lệch vài ms so với `now` của node ở
  sát 08:00/18:00 (prompt B14 không dùng `now` nên chỉ cờ này bị ảnh hưởng) — chấp nhận, ghi README.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from app.domain.policy import BusinessHours
from app.eval.dbread import Reader
from app.eval.predictions import PredictionRecord
from app.risk.context import build_ctx

LOG4_STEP = "B13/B14"
RAW_PROB_TOL = 1e-9
_LOG4 = (
    "SELECT created_at, raw_prob, p_method, detail->>'kb_gap' FROM audit_logs "
    "WHERE ticket_id = :t AND step = 'B13/B14' ORDER BY log_id DESC LIMIT 1"
)


class CollectError(ValueError):
    """Dữ liệu của cả lượt sai hợp đồng — thông điệp không có chữ người dùng."""


@dataclass
class Gathered:
    recorded: list[dict[str, Any]] = field(default_factory=list)
    cases: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def llm_records(records: Sequence[PredictionRecord]) -> tuple[list[PredictionRecord], Counter[str]]:
    """Ca đi lớp LLM của lượt, sắp theo `scenario_id`; đếm các ca bỏ vì chưa nhãn và ca lớp LLM không có `raw_prob`
    (`llm_no_raw_prob` — `offline.py` giữ route hệ thống cho ca đó, đếm `llm_no_prob`)."""
    skipped: Counter[str] = Counter()
    out: list[PredictionRecord] = []
    for r in sorted(records, key=lambda x: x.scenario_id):
        if r.decided_by != "llm" or r.route is None:
            continue
        if r.raw_prob is None:
            skipped["llm_no_raw_prob"] += 1
            continue
        if r.expected_route is None:
            skipped["unlabeled"] += 1
            continue
        out.append(r)
    return out, skipped


async def gather(
    reader: Reader, records: Sequence[PredictionRecord], *, hours: BusinessHours, p_method: str
) -> Gathered:
    todo, skipped = llm_records(records)
    got = Gathered()
    for r in todo:
        async with reader.engine.connect() as conn:
            row = (await conn.execute(text(_LOG4), {"t": r.ticket_id})).one_or_none()
        if row is None:
            skipped["no_log4"] += 1
            continue
        created, raw_prob, recorded_method, kb_gap = row
        if recorded_method != p_method:
            raise CollectError(f"p_method của audit ({recorded_method!r}) khác --p-method ({p_method!r}); lượt không so sánh được")
        if raw_prob is None or abs(float(raw_prob) - r.raw_prob) > RAW_PROB_TOL:  # type: ignore[operator]
            skipped["raw_prob_mismatch"] += 1
            continue
        if kb_gap not in ("true", "false"):
            skipped["no_kb_gap"] += 1
            continue
        state = await reader.state(r.ticket_id)
        if state is None or not all(state.get(k) is not None for k in ("intended_action", "requester_context")):
            skipped["no_state"] += 1
            continue
        ctx = build_ctx(
            {"intended_action": state["intended_action"], "requester_context": state["requester_context"],
             "ctx_flags": state.get("ctx_flags") or {}}, created, hours,
        )  # fmt: skip
        got.recorded.append({"scenario_id": r.scenario_id, "family": r.family, "split": r.split, "gold_route": r.expected_route,
                             "raw_prob": r.raw_prob, "kb_gap": kb_gap == "true"})  # fmt: skip
        got.cases.append({"scenario_id": r.scenario_id, "action": state["intended_action"].model_dump(mode="json"),
                          "ctx": ctx.model_dump(mode="json")})  # fmt: skip
    got.report = {
        "n_predictions": len(records), "n_llm_cases": len(todo), "n_gathered": len(got.recorded),
        "n_kb_gap": sum(1 for x in got.recorded if x["kb_gap"]), "skipped": dict(sorted(skipped.items())),
    }  # fmt: skip
    return got
