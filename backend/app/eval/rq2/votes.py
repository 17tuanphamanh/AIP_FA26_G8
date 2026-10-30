"""(b) hỏi 5 lần — ĐỌC LẠI phiếu của S1, không gọi LLM.

Phiếu: `llm_cache.response_json.needs_human` (mode `eval`, prompt `b14_risk_vote`). Khoá tính lại bằng chính `app.llm.cache.cache_key`
từ messages của dòng phiếu (`prompt_full`), cùng tham số gateway dùng ở S1 (`client.py` `_run`): provider/model của dòng, `model_version`
của CẤU HÌNH (`roles.strong.model_version` — không phải `llm_calls.model_version` do provider trả), schema `RiskVoteOut`, temperature
`VOTE_TEMPERATURE`, n = 1, `kb_version` None (estimator không truyền), mode `eval`.
p_b = số phiếu `needs_human = true` / K — đúng công thức `risk/estimator.py:181`. Đối chiếu: p_b phải bằng `raw_prob` ở điểm log 4 của S1
(`predictions.jsonl`), lệch → loại (`audit_mismatch`). Thiếu phiếu nào → không tính (`vote_cache_missing`), trừ khi người chạy cho phép
lấy `raw_prob` của điểm log 4 (`allow_audit`) — `p_b_source` ghi rõ nguồn từng lá.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import ValidationError

from app.eval.rq2.source import VOTE_PROMPT, VoteCall
from app.llm.cache import cache_key
from app.llm.schemas import RiskVoteOut
from app.risk.estimator import VOTE_TEMPERATURE, K

AUDIT_TOL: Final = 1e-9
type PbSource = Literal["votes", "audit_raw_prob"]
type VoteReject = Literal["vote_calls_count", "vote_call_error", "prompt_full_missing", "vote_cache_missing", "vote_invalid",
                          "audit_mismatch", "audit_missing"]  # fmt: skip


@dataclass(frozen=True)
class VoteResult:
    p_b: float | None
    votes: tuple[bool, ...] | None
    source: PbSource | None
    reason: VoteReject | None


def vote_key(call: VoteCall, *, model_version: str | None) -> str:
    return cache_key(
        provider=call.provider, model=call.model, model_version=model_version, prompt_id=VOTE_PROMPT,
        prompt_version=call.prompt_version, messages=call.messages, json_schema=RiskVoteOut.model_json_schema(),
        temperature=VOTE_TEMPERATURE, n=1, kb_version=None, mode="eval",
    )  # fmt: skip


def _fail(reason: VoteReject, audit_raw: float | None, allow_audit: bool) -> VoteResult:
    if allow_audit and audit_raw is not None and reason in ("vote_cache_missing", "prompt_full_missing"):
        return VoteResult(audit_raw, None, "audit_raw_prob", reason)
    return VoteResult(None, None, None, reason)


def p_from_votes(
    calls: Sequence[VoteCall], cache: Mapping[str, Mapping[str, Any]], audit_raw: float | None, *, model_version: str | None,
    allow_audit: bool = False,
) -> VoteResult:  # fmt: skip
    if audit_raw is None:
        return VoteResult(None, None, None, "audit_missing")
    if len(calls) != K:
        return VoteResult(None, None, None, "vote_calls_count")
    if any(c.error is not None for c in calls):
        return VoteResult(None, None, None, "vote_call_error")
    if any(c.prompt_full is None for c in calls):
        return _fail("prompt_full_missing", audit_raw, allow_audit)
    votes = []
    for c in calls:
        hit = cache.get(vote_key(c, model_version=model_version))
        if hit is None:
            return _fail("vote_cache_missing", audit_raw, allow_audit)
        try:
            votes.append(RiskVoteOut.model_validate(hit).needs_human)
        except ValidationError:
            return VoteResult(None, None, None, "vote_invalid")
    p = sum(votes) / K
    if abs(p - audit_raw) > AUDIT_TOL:
        return VoteResult(None, tuple(votes), None, "audit_mismatch")
    return VoteResult(p, tuple(votes), "votes", None)
