"""Ngân sách thời gian MỘT lượt (PLAN-3e chốt B2; PROGRESS "Việc treo" 7; Q-3d-7).

Mỗi lời gọi đã có trần riêng < `WORKER_STALE_TURN_SECONDS`/2 (Q-3a-16, Q-3c-4, Q-3d-7), nhưng một lượt gọi NỐI TIẾP
nhiều lời gọi: tổng xấu nhất phải < `WORKER_STALE_TURN_SECONDS`, không thì worker coi lượt còn sống là dở dang. Cộng
từ hằng số thật (không viết tay con số) — ƯỚC TÍNH trần trên, chưa đo. 3f/3g/3h mở rộng khi thêm node thật gọi mạng
(B3 L4, B6 tool, B10 `b10_need_type` + `b10_answer`, B11, B17).
"""

from pathlib import Path

import pytest
from app.llm.config import load_llm_config
from app.ml.client import TIMEOUT_S as ML_TIMEOUT_S
from app.settings import Settings, get_policy
from app.tools.specs import READ_TIMEOUT_S

CONFIG = Path(__file__).resolve().parents[3] / "config"


def _retry_worst(timeout_s: float) -> float:
    """`tools/retry.call_with_retry` (dùng cho tool đọc và ml-service): (TOOL_RETRY+1)·timeout + Σ backoff."""
    c = get_policy().constants
    return (c.TOOL_RETRY + 1) * timeout_s + sum(c.BACKOFF_BASE_SECONDS * 2**k for k in range(c.TOOL_RETRY))


def first_turn_budget() -> dict[str, float]:
    """Lượt `submit` ở cuối 3e: B1 (AD) → B2 (ml classify → L4 fast) → B3–B6 giả → B8 (RAG) → … → chờ duyệt."""
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    fast = load_llm_config(CONFIG / "llm.yaml").roles["fast"]
    return {
        "B1 ad_get_user": _retry_worst(READ_TIMEOUT_S),
        "B2 L3 ml classify": _retry_worst(ML_TIMEOUT_S["classify"]),
        "B2 L4 b02_injection_judge (fast deadline_s)": fast.deadline_s,
        "B8 rag_deadline_s": settings.rag_deadline_s,
    }


def test_budget_items_come_from_constants() -> None:
    budget = first_turn_budget()
    assert budget["B1 ad_get_user"] == 18.0 and budget["B2 L3 ml classify"] == 9.0  # 3·5+1+2, 3·2+1+2
    assert len(budget) == 4


@pytest.mark.xfail(strict=True, reason="Q-3e-12 (làm ở 3f S0 — hạn cho cả lượt): lượt đầu 122 s ≥ 120 s")
def test_first_turn_worst_case_below_stale_threshold() -> None:
    budget = first_turn_budget()
    stale = Settings(_env_file=None).worker_stale_turn_seconds  # type: ignore[call-arg]
    total = sum(budget.values())
    assert total < stale, f"tổng xấu nhất {total:g}s ≥ WORKER_STALE_TURN_SECONDS {stale:g}s: {budget}"
