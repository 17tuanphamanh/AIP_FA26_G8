"""(a) tự nói con số — GỌI THÊM `b14_risk_estimate` (temperature 0) trên đầu vào B14 đã dựng của S1 (`source.rebuild`).

Dùng lại đúng đường self_report của estimator: `LlmRiskEstimator(llm, p_method="self_report", eval_mode=True)._self_report(variables)`
(`risk/estimator.py:152-158`; hàm private — đầu vào ở đây là biến đã kiểm byte, không phải `Action`/`RiskContext`). `eval_mode=True` →
cache_policy `default`; gateway do script dựng với `cache_mode="eval"` + `FileLlmStore` → chạy lại đọc cache trong thư mục run.
Lỗi gateway được lường (`LLMUnavailable`, `LLMSchemaError`, `LLMBudgetExceeded`) → lá không có p_a, ghi tên lớp lỗi; lỗi khác ném lên.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.core.errors import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.ports import LlmPort
from app.risk.estimator import SELF_REPORT_TEMPERATURE, LlmRiskEstimator

TEMPERATURE = SELF_REPORT_TEMPERATURE
RECOVERABLE = (LLMUnavailable, LLMSchemaError, LLMBudgetExceeded)


@dataclass(frozen=True)
class SelfReport:
    p_a: float | None
    error: str | None
    model: str | None
    trimmed_evidence: int | None


async def self_report(llm: LlmPort, variables: Mapping[str, Any]) -> SelfReport:
    estimator = LlmRiskEstimator(llm, p_method="self_report", eval_mode=True)
    try:
        est = await estimator._self_report(dict(variables))
    except RECOVERABLE as e:
        return SelfReport(None, type(e).__name__, None, None)
    return SelfReport(est.raw_prob, None, est.model, est.evidence_trimmed)
