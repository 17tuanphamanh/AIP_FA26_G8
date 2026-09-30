"""B10 — node THẬT (phase3 mục 10.3; PLAN-3g chốt Q-3g-1, Q-3g-2, Q-3g-3, f1). Node giả (Phase 2, `FAKE_SCENARIO`):
`graph/nodes/fake/b10_route.py`.

1. LLM fast `b10_need_type` — chạy TRƯỚC mọi kiểm ngưỡng (S0-P2). `action` → B11 (`need_type=action`, không trả lời gì)
   BẤT KỂ điểm truy hồi (S0-P3, Q-4-U A+, D-34: căn cứ của hành động là `procedure_doc` kiểm ở B11, không phải độ giống văn
   bản); cờ `GROUNDING_GATE_ACTIONS=true` (ablation Phase 10, S0-P11) → hành động cũng qua B9 như 3h. `info` → B9.
   B9 (S0-P2): không chunk hoặc `retrieval_score` < `RETRIEVAL_THRESHOLD` → E3 `no_grounding` với step `B9`, event
   `no_evidence` — Y HỆT nhánh cũ ở B8 (B20, mẫu tin E3, M9 không đổi); 0 `expand`, 0 `b10_answer`. Mọi dòng audit của B10
   có `grounding = {top_score, above_threshold, kb_gap}` (M9: chỉ số "yêu cầu hành động thiếu KB").
2. `expand_for_answer(top-5)` trên CÙNG `kb_version` đã ghim ở B8 (D-24) — `RetrievalSystemError` → E2 `rag_system_error`.
   Không khối bằng chứng nào → E3 `no_grounding`, không gọi LLM viết câu trả lời.
3. LLM strong `b10_answer`. Gateway phải cắt khối bằng chứng (`trimmed_evidence > 0`) → E3 `invalid_citation`,
   `evidence_truncated=true` (f1: LLM không thấy đủ bằng chứng — không đoán anchor).
4. Hậu kiểm bằng CODE (`domain.answer.check_citations`): `cannot_answer` → E3 `no_grounding` (Q-3g-1); trích dẫn ngoài
   anchor → E3 `invalid_citation`. Anchor = `chunk_id` top-5 ∩ anchor của khối THẬT SỰ gửi LLM — không bao giờ là chunk
   liền kề (chúng chỉ là ngữ cảnh đọc thêm).
5. `render_answer` theo mẫu (không LLM) → output guard (P4) → vi phạm → E3 `output_guard_block`, 0 tin gửi đi.
6. `notify_user` (needs=confirm) + hạn `confirm` 48 h, đều qua `effects.once` (chạy lại node / resume `confirm_wait` không gửi
   lại — D-18); `lineage` (prompt, model, `kb_version`) ghi CÙNG transaction với audit của `goto` (Q-3g-3) → `S_CONFIRMING`.

Lỗi: `LLMSchemaError` → E2 `llm_schema_error`; `LLMUnavailable`/`LLMBudgetExceeded` → E2 `llm_unavailable`; hết hạn cả lượt
(ở LLM hoặc RAG) → E2 `turn_budget_exceeded`, bắt tường minh (`step` hằng). Không `except Exception` — lỗi khác → E9.
Audit `detail`: chỉ enum, định danh, số đếm — không câu người dùng, không chữ LLM.
"""

from datetime import timedelta
from typing import Any

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.answer import check_citations, render_answer
from app.domain.exit_codes import ExitCode
from app.domain.messages import answer_msg
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import AnswerOut, NeedTypeOut
from app.rag.models import RetrievalSystemError


def _info() -> dict[str, Any]:
    return {
        "need_type": None, "prompt": None, "llm_error": None, "rag_error": None, "evidence_blocks": None,
        "trimmed_evidence": None, "evidence_truncated": False, "citation": None, "cited": [], "guard": None,
        "grounding": None,
    }  # fmt: skip


def grounding(chunks: list[ChunkRef], score: float | None, threshold: float) -> dict[str, Any]:
    """S0-P3: đạt ngưỡng = có chunk VÀ `score` ≥ ngưỡng (bằng ngưỡng là đạt — c15). Thiếu `score` → coi như dưới ngưỡng."""
    above = bool(chunks) and score is not None and score >= threshold
    return {"top_score": score, "above_threshold": above, "kb_gap": not above}


def make(deps: NodeDeps) -> NodeFn:
    async def b10_route(state: Any) -> dict[str, Any]:
        info = _info()
        try:
            return await _route(state, info)
        except TurnBudgetExceeded:  # 9.0: ở LLM hoặc RAG — không cho qua, không E9
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="turn_budget_exceeded", audit_detail=info,
                exit_code=ExitCode.E2.value, escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip

    async def _route(state: Any, info: dict[str, Any]) -> dict[str, Any]:
        chunks: list[ChunkRef] = list(state["retrieved"])
        kb_version = state["kb_version"]
        info["grounding"] = grounding(chunks, state.get("retrieval_score"), deps.constants.RETRIEVAL_THRESHOLD)
        above = info["grounding"]["above_threshold"]
        try:
            need, meta = await deps.llm.complete(
                "fast", "b10_need_type",
                {"text": state["redacted_request"], "evidence_titles": [c.title for c in chunks]},
                NeedTypeOut, kb_version=kb_version,
            )  # fmt: skip
        except LLMSchemaError as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="llm_schema_error", audit_detail=info,
                exit_code=ExitCode.E2.value, escalation_reason_detail="llm_schema_error",
            )  # fmt: skip
        except (LLMUnavailable, LLMBudgetExceeded) as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="llm_unavailable", audit_detail=info,
                exit_code=ExitCode.E2.value, escalation_reason_detail="llm_unavailable",
            )  # fmt: skip
        info["need_type"], info["prompt"] = need.type, f"{meta.prompt_id}@{meta.prompt_version}"
        if need.type == "action":
            if deps.grounding_gate_actions and not above:  # S0-P11: ablation — hành vi 3h (B9 chặn cả hành động)
                return await goto(
                    state, S_ESCALATED, next_node="b20_audit", step="B9", event="no_evidence", audit_detail=info,
                    exit_code=ExitCode.E3.value, need_type="action", escalation_reason_detail="no_grounding",
                    kb_version=kb_version,
                )  # fmt: skip
            return await goto(  # S0-P3: tới B11 bất kể điểm — căn cứ hành động = procedure_doc (B11)
                state, S_RETRIEVING, next_node="b11_slots", step="B10", event="needs_action", audit_detail=info,
                need_type="action",
            )  # fmt: skip
        if not above:  # B9 (S0-P2): câu trả lời cần đoạn KB đạt ngưỡng — kiểm TRƯỚC expand/b10_answer
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B9", event="no_evidence", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="no_grounding",
                kb_version=kb_version,  # cột audit_logs.kb_version như dòng B9 cũ ở B8 (soát NGHI-5)
            )  # fmt: skip
        try:
            evidence = await deps.rag.expand_for_answer(chunks, state["requester_context"], kb_version=kb_version)
        except RetrievalSystemError as exc:
            info["rag_error"] = exc.stage
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="rag_system_error", audit_detail=info,
                exit_code=ExitCode.E2.value, retrieval_error=exc.stage, escalation_reason_detail="rag_system_error",
            )  # fmt: skip
        info["evidence_blocks"] = len(evidence)
        if not evidence:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="no_evidence", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="no_grounding",
            )  # fmt: skip
        try:
            ans, meta = await deps.llm.complete(
                "strong", "b10_answer", {"question": state["redacted_request"], "evidence": evidence}, AnswerOut,
                kb_version=kb_version,
            )  # fmt: skip
        except LLMSchemaError as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="llm_schema_error", audit_detail=info,
                exit_code=ExitCode.E2.value, escalation_reason_detail="llm_schema_error",
            )  # fmt: skip
        except (LLMUnavailable, LLMBudgetExceeded) as exc:
            info["llm_error"] = type(exc).__name__
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="llm_unavailable", audit_detail=info,
                exit_code=ExitCode.E2.value, escalation_reason_detail="llm_unavailable",
            )  # fmt: skip
        info["prompt"], info["trimmed_evidence"] = f"{meta.prompt_id}@{meta.prompt_version}", meta.trimmed_evidence
        if meta.trimmed_evidence > 0:  # f1: gateway bỏ bớt khối — LLM không thấy đủ bằng chứng, không đoán anchor
            info["evidence_truncated"] = True
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="invalid_citation", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="invalid_citation",
            )  # fmt: skip
        anchors = {c.chunk_id for c in chunks} & {b.anchor_chunk_id for b in evidence}
        info["citation"] = check_citations(ans.citations, cannot_answer=ans.cannot_answer, anchors=anchors)
        if info["citation"] == "no_grounding":  # Q-3g-1: LLM tự nhận không đủ căn cứ
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="cannot_answer", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="no_grounding",
            )  # fmt: skip
        if info["citation"] == "invalid_citation":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="invalid_citation", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="invalid_citation",
            )  # fmt: skip
        by_id = {c.chunk_id: c for c in chunks}
        cited = [by_id[i] for i in dict.fromkeys(ans.citations)]
        info["cited"] = [c.chunk_id for c in cited]
        body = render_answer(ans.answer_markdown, ans.steps, cited)
        info["guard"] = deps.output_guard.violation(body)
        if info["guard"] is not None:  # P4: chữ LLM có bí mật / canary / đoạn prompt hệ thống → không gửi, không lưu
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="output_guard_block", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="output_guard_block",
            )  # fmt: skip
        run = current_run()
        ref = await effects.once(
            state, "notify_user", deps.notifier.notify_user, state["ticket_id"], body, "confirm", step="B10",
        )  # fmt: skip
        deadline = run.clock.now() + timedelta(hours=deps.constants.CONFIRM_TIMEOUT_HOURS)
        await effects.once(
            state, "deadline_set", deps.deadlines.set, state["ticket_id"], "confirm", deadline, run.turn_id, step="B10",
        )  # fmt: skip
        return await goto(
            state, S_CONFIRMING, next_node="confirm_wait", step="B10", event="deflected_info_only", audit_detail=info,
            lineage={"prompt_id": meta.prompt_id, "prompt_version": meta.prompt_version, "model": meta.model,
                     "kb_version": kb_version, "commit_sha": deps.commit_sha},  # P4: commit của image (Settings)
            need_type="info", answer_ref=ref, conversation=[answer_msg(body, ref, cited)],
        )  # fmt: skip

    return b10_route
