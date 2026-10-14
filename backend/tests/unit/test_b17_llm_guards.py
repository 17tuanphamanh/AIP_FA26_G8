"""Phase 6 6C DỪNG 2 — chốt chặn B17 D-42 sau soát bảo mật (Tuấn Anh 14/10): agent chính viết (không phải test-writer).

- Q-6C-10 = A: `llm_auto` đòi thêm `risk.calibrated_prob is not None` — B12 chỉ ra AUTO do LLM khi đã hiệu chỉnh (D-38); state
  llm/AUTO, hash khớp mà `calibrated_prob` None (checkpoint giả / lỗi sau này) → E5 `recheck_failed`, không thực thi.
- Q-6C-11 = A: `risk` dạng dict hỏng → `RiskDecision.model_validate` ném → E9 qua boundary, 0 lời gọi ghi, 0 `begun`.
Khuôn + helper: `test_b17_llm_auto.py` (Env, `llm_auto_state`).
"""

from typing import Any

import pytest
from app.domain.states import S_ESCALATED
from tests.unit.test_b17_llm_auto import (
    IN_HOURS,
    Env,
    _assert_e5_recheck_zero_writes,
    _vpn,
    llm_auto_state,
    llm_risk,
)

pytestmark = pytest.mark.asyncio


async def test_q6c10_llm_auto_without_calibrated_prob_is_e5_not_executed() -> None:
    """Q-6C-10: `risk` llm/AUTO, hash khớp, luật hiện hành không khớp, KHÔNG qua duyệt nhưng `calibrated_prob` None → không ngoại
    lệ D-42 → E5 `recheck_failed` (`detail.recheck="not_approved"`), 0 lời gọi ghi, 0 `begun`."""
    env = Env(IN_HOURS)
    risk = llm_risk("AUTO").model_copy(update={"calibrated_prob": None})
    out = await env.b17(llm_auto_state(_vpn(owner=False), other=False, risk=risk))
    _assert_e5_recheck_zero_writes(env, out)
    assert env.rows("recheck_failed")[0]["detail"]["recheck"] == "not_approved"


@pytest.mark.parametrize("bad", [{}, {"decided_by": "llm"}], ids=["rong", "chi-decided_by"])
async def test_q6c11_broken_risk_dict_is_e9_zero_writes(bad: dict[str, Any]) -> None:
    """Q-6C-11: `risk` dạng dict hỏng (thiếu trường bắt buộc) ở ca không qua duyệt + không luật khớp → E9 qua boundary (không
    thực thi), 0 lời gọi ghi, 0 `begun`."""
    env = Env(IN_HOURS)
    out = await env.b17(llm_auto_state(_vpn(owner=False), other=False, risk=bad))
    assert (out.get("status"), out.get("exit_code")) == (S_ESCALATED, "E9"), (out, env.h.audit.events("t1"))
    assert env.writes_total() == 0 and env.txlog.rows == []
    assert env.rows("executed_ok") == []
    [row] = env.rows("unhandled_exception")  # boundary: E9 do chính `RiskDecision.model_validate` (không lỗi khác)
    assert row["step"] == "b17_execute" and row["detail"]["exception"].startswith("ValidationError"), row["detail"]
