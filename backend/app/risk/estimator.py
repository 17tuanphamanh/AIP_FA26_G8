"""Lớp 2 của M5 (B14 — ước lượng xác suất cần người duyệt). Phase 3: `DisabledEstimator` (3-Q30, phase3 11.3) — mọi ca
không luật nào khớp đi E5 `llm_layer_disabled`, KHÔNG tự làm. Phase 6 (6B): `LlmRiskEstimator` — LLM strong qua `LlmPort`
(chưa nối B12 — 6C).

Input của estimator (mọi phase): `Action` + `RiskContext` + trích đoạn KB — KHÔNG câu người dùng (B12 §5.1). Biến prompt
chỉ dựng qua hàm thuần `estimator_vars` (phase6 5.1 P2–P4); whitelist `allowed_vars` của 2 prompt `b14_*` chặn thêm ở gateway.

Phase 4 S0-P9 (Q-4-U A+, D-34): B12 đưa trích đoạn KB cho estimator CHỈ qua `evidence_for_estimator` — đoạn dưới ngưỡng
truy hồi không bao giờ tới B14 (chúng không phải căn cứ). Ràng buộc cho Phase 6: không luật nào khớp + `kb_gap` → route tối
đa HITL, không AUTO.
"""

import asyncio
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.core.errors import LLMUnavailable
from app.domain.action import PARAMS_BY_ACTION, PERMISSION_LEVELS, Action, FactValue
from app.domain.risk_factors import FactorCode
from app.domain.ticket_state import ChunkRef
from app.llm.ports import CachePolicy, LLMMeta, LlmPort
from app.llm.schemas import RiskEstimateOut, RiskVoteOut
from app.risk.models import RiskContext

type PMethod = Literal["self_report", "sampling_k5"]

MAX_EVIDENCE = 3  # P4
K = 5  # P6 — hỏi 5 lần (G6-3)
MAX_FACTORS = 5
SELF_REPORT_TEMPERATURE = 0.0  # P5
VOTE_TEMPERATURE = 0.7  # P6
_REQUESTER_KEYS = ("role", "department", "employment_status", "tenure_days", "is_privileged_account")  # P3
# 6C P8 (N1): danh sách trắng `intended_action` — chữ người dùng không bao giờ tới prompt B14. `params` chỉ khoá có giá trị ĐÓNG/mẫu
# chặt (bỏ `software_name`, `resource_path` — rủi ro của chúng đã ở fact `in_catalog`, `resource_sensitivity`…); giá trị trượt mẫu → bỏ
# khoá (Action đã qua B11 — lệch là bug, an toàn là không gửi). `[0-9]` thay `\d` (chữ số Unicode). Mẫu theo `config/slots.yaml`.
_DEVICE_ID = re.compile(r"[A-Z]{2,4}-[0-9]{3,5}")
_DEVICE_TARGET = re.compile(r"device:[A-Z]{2,4}-[0-9]{3,5}")
_TARGET_KINDS = frozenset({"folder", "user", "device"})
_ACCOUNT_TYPES = frozenset({"ad", "email", "erp"})
_DURATION_MAX = 999  # value_rules.duration ^[1-9][0-9]{0,2}$
_DROPPED_ACTION_KEYS = ("requested_for",)  # người bị tác động: đã có ở `ctx.target_is_other`
# Q5 (ĐP 09/11): fact KHÔNG gửi B14 — giữ đầu vào `b14_risk_estimate`/`b14_risk_vote` giống bản đo RQ1 (bf94df2). Ca bị cấm đã dừng ở
# luật deny R21 trước lớp LLM nên B14 không cần fact này.
B14_EXCLUDED_FACTS = frozenset({"software_prohibited"})


def evidence_for_estimator(chunks: Sequence[ChunkRef], score: float | None, threshold: float) -> list[ChunkRef]:
    """S0-P9 — hàm thuần: `chunks` khi `score` ≥ `threshold` (bằng ngưỡng là đạt, như B9), không thì `[]`. Thiếu `score`
    (None) hoặc NaN → `[]` (fail-closed; `not score >= threshold` thay cho `score < threshold` — NaN so sánh luôn False)."""
    if score is None or not score >= threshold:
        return []
    return list(chunks)


@dataclass(frozen=True)
class RiskEstimate:
    """Kết quả B14 (phase6 P1). `prompt_id`, `prompt_version`, `model` từ `LLMMeta` — cho lineage (6C). Không có
    `rationale` của LLM (Q-6-5). `evidence_trimmed` (6C P9, N4) = số khối bằng chứng gateway cắt (`LLMMeta.trimmed_evidence`;
    k = 5: lớn nhất trong 5 phiếu) — B12 tính `kb_gap` trên phần bằng chứng THỰC gửi. `LlmRiskEstimator` luôn đặt tường minh."""

    raw_prob: float
    p_method: PMethod
    factors: tuple[FactorCode, ...]
    prompt_id: str
    prompt_version: str
    model: str
    evidence_trimmed: int = 0


class RiskEstimator(Protocol):
    async def estimate(self, action: Action, ctx: RiskContext, retrieved: Sequence[ChunkRef]) -> RiskEstimate: ...


class DisabledEstimator:
    """Luôn ném `LLMUnavailable` → B12 nhánh sẵn có → `ESCALATE_L2` / E5 `llm_layer_disabled`. Trả `p=0` thay vì ném là
    lỗ tự làm (M-3h-9)."""

    async def estimate(self, action: Action, ctx: RiskContext, retrieved: Sequence[ChunkRef]) -> RiskEstimate:
        raise LLMUnavailable("lớp LLM rủi ro (B14) chưa bật ở Phase 3 — 3-Q30")


def _param_ok(key: str, value: FactValue) -> bool:
    if key == "device_id":
        return type(value) is str and _DEVICE_ID.fullmatch(value) is not None
    if key == "account_type":
        return type(value) is str and value in _ACCOUNT_TYPES
    if key == "permission_level":
        return type(value) is str and value in PERMISSION_LEVELS
    if key == "duration_days":
        return type(value) is int and 1 <= value <= _DURATION_MAX
    return False  # software_name, resource_path, khoá lạ — không bao giờ gửi


def _target_kind(target: str) -> str:
    if _DEVICE_TARGET.fullmatch(target):
        return target
    kind, sep, _ = target.partition(":")
    return kind if sep and kind in _TARGET_KINDS else "other"


def intended_action_vars(action: Action) -> dict[str, Any]:
    """6C P8 (N1): `Action` → biến `intended_action` — bỏ `requested_for`; `params` chỉ khoá ∈ `PARAMS_BY_ACTION[type]` có giá trị
    đạt mẫu chặt (`_param_ok`); `target` giữ khi là `device:<mã máy>` đúng mẫu, còn lại chỉ còn loại đích (`folder`/`user`/`device`,
    lạ → `other`). Trường còn lại là enum/tập đóng (`facts` — `domain/facts.FACT_VALUE_SETS`; bỏ `B14_EXCLUDED_FACTS`, Q5)."""
    data = action.model_dump(mode="json")
    for key in _DROPPED_ACTION_KEYS:
        data.pop(key, None)
    allowed = PARAMS_BY_ACTION.get(action.type, {})
    data["params"] = {k: v for k, v in action.params.items() if k in allowed and _param_ok(k, v)}
    data["target"] = _target_kind(action.target)
    data["facts"] = {k: v for k, v in action.facts.items() if k not in B14_EXCLUDED_FACTS}
    return data


def estimator_vars(action: Action, ctx: RiskContext, evidence: Sequence[ChunkRef]) -> dict[str, Any]:
    """Biến prompt B14 — hàm thuần, CHỈ từ `Action`, `RiskContext`, trích đoạn KB (P2). `intended_action` qua danh sách trắng N1
    (`intended_action_vars`, 6C P8); `risk_context` bỏ trường đổi theo thời gian/định danh (`now`, `captured_at`, `user_id`,
    `manager_id`, P3 — khoá cache tái lập được); trích đoạn: ≤ 3 khối điểm cao nhất (hoà giữ thứ tự B12), ánh xạ sang 5 khoá
    renderer cần (`llm/context._evidence`, P4)."""
    requester = ctx.requester
    top = sorted(evidence, key=lambda c: -c.score)[:MAX_EVIDENCE]  # sorted ổn định
    return {
        "intended_action": intended_action_vars(action),
        "risk_context": {
            "requester": {k: getattr(requester, k) for k in _REQUESTER_KEYS},
            "within_business_hours": ctx.within_business_hours,
            "target_is_other": ctx.target_is_other,
        },
        "evidence": [
            {"anchor_chunk_id": c.chunk_id, "title": c.title, "heading_path": c.heading_path, "text": c.excerpt,
             "score": float(c.score)}
            for c in top
        ],
    }  # fmt: skip


def _merge_factors(votes: Sequence[RiskVoteOut]) -> tuple[FactorCode, ...]:
    """P6: hợp các phiếu, tần suất giảm rồi theo mã, ≤ 5. Mỗi mã tính tối đa 1 lần/phiếu (TQ-5)."""
    counts = Counter(code for vote in votes for code in set(vote.factors))
    return tuple(sorted(counts, key=lambda c: (-counts[c], c.value))[:MAX_FACTORS])


class LlmRiskEstimator:
    """B14 qua `LlmPort` (P5, P6). `rationale` của LLM không đi ra khỏi lớp này (Q-6-5). Lỗi gateway (`LLMUnavailable`,
    `LLMSchemaError`, `LLMBudgetExceeded`, `TurnBudgetExceeded`…) ném nguyên — B12 quyết đường lỗi."""

    def __init__(self, llm: LlmPort, *, p_method: PMethod, eval_mode: bool) -> None:
        self._llm = llm
        self._p_method: PMethod = p_method
        # Q-6-6: vận hành không cache B14 (ca giống nhau theo thời gian phải được đánh giá lại); đánh giá thì cache để tái lập
        self._cache_policy: CachePolicy = "default" if eval_mode else "bypass"

    async def estimate(self, action: Action, ctx: RiskContext, retrieved: Sequence[ChunkRef]) -> RiskEstimate:
        variables = estimator_vars(action, ctx, retrieved)
        if self._p_method == "self_report":
            return await self._self_report(variables)
        return await self._sampling(variables)

    async def _self_report(self, variables: dict[str, Any]) -> RiskEstimate:
        out, meta = await self._llm.complete(
            "strong", "b14_risk_estimate", variables, RiskEstimateOut,
            temperature=SELF_REPORT_TEMPERATURE, cache_policy=self._cache_policy,
        )  # fmt: skip
        return RiskEstimate(out.prob_needs_human, "self_report", tuple(out.factors), meta.prompt_id,
                            meta.prompt_version, meta.model, evidence_trimmed=meta.trimmed_evidence)  # fmt: skip

    async def _vote(self, variables: dict[str, Any], idx: int) -> tuple[RiskVoteOut, LLMMeta]:
        return await self._llm.complete(
            "strong", "b14_risk_vote", {**variables, "sample_idx": idx}, RiskVoteOut,
            temperature=VOTE_TEMPERATURE, cache_policy=self._cache_policy,
        )  # fmt: skip

    async def _sampling(self, variables: dict[str, Any]) -> RiskEstimate:
        # Chờ đủ 5 rồi mới xét lỗi (TQ-4): lỗi tất định theo sample_idx, không để lời gọi nào chạy mồ côi. KHÔNG BAO GIỜ tính p
        # từ < 5 phiếu (P6) — một lỗi là cả ước lượng lỗi.
        results = await asyncio.gather(*(self._vote(variables, i) for i in range(K)), return_exceptions=True)
        for r in results:
            if isinstance(r, BaseException):
                raise r
        votes = [r for r in results if not isinstance(r, BaseException)]
        meta = votes[0][1]
        p = sum(v.needs_human for v, _ in votes) / K
        trimmed = max(m.trimmed_evidence for _, m in votes)  # 6C P9: phiếu bị cắt nhiều nhất quyết định kb_gap
        return RiskEstimate(p, "sampling_k5", _merge_factors([v for v, _ in votes]), meta.prompt_id,
                            meta.prompt_version, meta.model, evidence_trimmed=trimmed)  # fmt: skip
