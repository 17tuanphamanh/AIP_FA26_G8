"""B10 — node THẬT (phase3 mục 10.3; PLAN-3g chốt Q-3g-1, Q-3g-2, Q-3g-3, f1). Node giả (Phase 2, `FAKE_SCENARIO`):
`graph/nodes/fake/b10_route.py`.

1. LLM fast `b10_need_type` — chạy TRƯỚC mọi kiểm ngưỡng (S0-P2). `action` → B11 (`need_type=action`, không trả lời gì)
   BẤT KỂ điểm truy hồi (S0-P3, Q-4-U A+, D-34: căn cứ của hành động là `procedure_doc` kiểm ở B11, không phải độ giống văn
   bản); cờ `GROUNDING_GATE_ACTIONS=true` (ablation Phase 10, S0-P11) → hành động cũng qua B9 như 3h. `info` → B9.
   B9 (S0-P2): không chunk hoặc `retrieval_score` < `RETRIEVAL_THRESHOLD` → E3 `no_grounding` với step `B9`, event
   `no_evidence` — Y HỆT nhánh cũ ở B8 (B20, mẫu tin E3, M9 không đổi); 0 `expand`, 0 `b10_answer`. Mọi dòng audit của B10
   có `grounding = {top_score, above_threshold, kb_gap}` (M9: chỉ số "yêu cầu hành động thiếu KB").
2. `expand_for_answer(top-5 ĐẠT NGƯỠNG — R2 soát 12/11)` trên CÙNG `kb_version` đã ghim ở B8 (D-24) — `RetrievalSystemError` → E2
   `rag_system_error`. Đoạn dưới `RETRIEVAL_THRESHOLD` bị bỏ (audit `below_threshold_dropped`), nên không là anchor hợp lệ.
   Không khối bằng chứng nào → E3 `no_grounding`, không gọi LLM viết câu trả lời.
3. LLM strong `b10_answer`. Gateway phải cắt khối bằng chứng (`trimmed_evidence > 0`) → E3 `invalid_citation`,
   `evidence_truncated=true` (f1: LLM không thấy đủ bằng chứng — không đoán anchor).
4. Hậu kiểm bằng CODE (`domain.answer.check_citations`): `cannot_answer` → E3 `no_grounding` (Q-3g-1); trích dẫn ngoài
   anchor → E3 `invalid_citation`. Anchor = `chunk_id` top-5 ∩ anchor của khối THẬT SỰ gửi LLM — không bao giờ là chunk
   liền kề (chúng chỉ là ngữ cảnh đọc thêm).
5. Q2 M2: `cap_steps` giữ tối đa 3 bước (audit `steps_truncated`); `render_answer` theo mẫu (không LLM, câu kết cố định sau các bước) → output guard (P4) → vi phạm → E3 `output_guard_block`, 0 tin gửi đi.
6. `notify_user` (needs=confirm) + hạn `confirm` 48 h, đều qua `effects.once` (chạy lại node / resume `confirm_wait` không gửi
   lại — D-18); `lineage` (prompt, model, `kb_version`) ghi CÙNG transaction với audit của `goto` (Q-3g-3) → `S_CONFIRMING`.

Q2 M1 (ĐP 09/11) — "báo lỗi VPN khi chứng chỉ còn hạn": sau `b10_need_type`, nếu `symptom_to_info(state)` (intent `vpn`, need
`action`, CHƯA có slot `action`, fact B6 `device_owner_is_requester is True`, `device_registered is True`, `cert_status == "valid"`)
→ đi nhánh info (B9 → expand → b10_answer) thay vì B11 — không có hành động nào hợp lý để hỏi "cấp mới/gia hạn/thu hồi". Cổng
grounding giữ nguyên (thiếu bằng chứng → E3). Câu mở đầu theo fact (`messages.symptom_intro`, CODE) ghép TRƯỚC câu trả lời; output
guard chạy trên toàn tin. State `need_type="info"` (đã trả lời như info); audit giữ `need_type` của LLM + `symptom_to_info` (bool).

D-76 (ĐP chốt 09/11, bản demo lo-0811): intent chỉ-trả-lời (`it_help`) → KHÔNG gọi `b10_need_type`, ép `info` (audit `need_type="info"`,
`answer_only=true`) → B9 → expand → `b10_answer` như mọi câu trả lời KB; thiếu căn cứ → E3 như cũ. Không bao giờ sang B11.

Q13a (D-78, 11/11): `b10_answer` v4 nhận thêm `previous_answer` (`previous_answer(state)`) — ở vòng hỏi tiếp sau "Chưa ổn" là câu trả lời KB
đã gửi trước đó, để LLM không lặp bước; lượt thường là "(chưa có)".

Kiểm thử 17/11 (TA, D-100):
1. Vòng hỏi tiếp sau "Chưa ổn" (`followup_round` > 0) mà thiếu căn cứ (`no_evidence`, `cannot_answer` — `_dead_end`; KHÔNG áp cho
   `invalid_citation`/`output_guard_block`): → E8 (người dùng báo chưa ổn, `user_feedback` = ghi chú của vòng đó) thay cho E3 "chưa có
   thông tin". Cùng lý do: câu trả lời của vòng hỏi tiếp mà HỨA chuyển kỹ thuật viên (`PROMISES_HANDOFF`, máy in 17/11) → E8 thật.
2. Câu HỎI trạng thái chứng chỉ VPN máy của CHÍNH người gửi (`vpn_status_fallback`: chữ khớp `VPN_STATUS_QUESTION`, không phải câu hỏi
   cách làm, không có động từ ghi; B6 có fact chứng chỉ) → B11 với `action=check_vpn_status` (CHỈ ĐỌC, R16, vẫn qua B11–B13), ngay sau
   `b10_need_type` — KB không có số liệu từng máy: trước đây ra E3, hoặc LLM trả lời "không có thông tin về hạn chứng chỉ" dù B6 đã biết.
   Ghi đè cả `action` B6 tự suy từ chứng chỉ (`renew_vpn_cert`/`reissue_vpn_access`) vì câu không có động từ ghi — người dùng hỏi, chưa
   nhờ gia hạn; tin kết quả Q2 M3 đã gợi ý bước tiếp. Câu báo lỗi (Q2 M1) không khớp mẫu → giữ nguyên.

Lỗi: `LLMSchemaError` → E2 `llm_schema_error`; `LLMUnavailable`/`LLMBudgetExceeded` → E2 `llm_unavailable`; hết hạn cả lượt
(ở LLM hoặc RAG) → E2 `turn_budget_exceeded`, bắt tường minh (`step` hằng). Không `except Exception` — lỗi khác → E9.
Audit `detail`: chỉ enum, định danh, số đếm — không câu người dùng, không chữ LLM.
"""

import re
import unicodedata
from datetime import timedelta
from typing import Any

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.answer import cap_steps, check_citations, render_answer
from app.domain.exit_codes import ExitCode
from app.domain.intents import ANSWER_ONLY_INTENTS
from app.domain.messages import (
    NO_PREVIOUS_ANSWER,
    answer_msg,
    followup_note,
    last_answer,
    symptom_intro,
)
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_RETRIEVING
from app.domain.ticket_state import ChunkRef
from app.graph import effects
from app.graph.context import current_run
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import AnswerOut, NeedTypeOut, RewriteQueryOut
from app.rag.models import RetrievalSystemError
from app.rag.query import build_query


def _info() -> dict[str, Any]:
    return {
        "need_type": None, "prompt": None, "llm_error": None, "rag_error": None, "evidence_blocks": None,
        "trimmed_evidence": None, "evidence_truncated": False, "citation": None, "cited": [], "guard": None,
        "grounding": None, "symptom_to_info": False, "steps_truncated": False, "answer_only": False, "rewrite": None,
    }  # fmt: skip


def grounding(chunks: list[ChunkRef], score: float | None, threshold: float) -> dict[str, Any]:
    """S0-P3: đạt ngưỡng = có chunk VÀ `score` ≥ ngưỡng (bằng ngưỡng là đạt — c15). Thiếu `score` → coi như dưới ngưỡng."""
    above = bool(chunks) and score is not None and score >= threshold
    return {"top_score": score, "above_threshold": above, "kb_gap": not above}


# K3 (soát 12/11, agent 16 V22): slot `action` CHỈ ĐỌC mà B3 đã nhận → nhánh hành động dù `b10_need_type` nói `info`
# ("Em đang có quyền gì" → danh sách quyền CỦA người gửi qua B11 → M5, không phải bài KB liệt kê mọi thư mục). Chỉ `view_permissions`:
# `check_vpn_status` giữ hành vi cũ (Q2 M1 trả lời theo KB có chủ đích); hành động GHI không bao giờ bị ép ở đây.
INFO_TO_ACTION_SLOTS: frozenset[str] = frozenset({"view_permissions"})


def symptom_to_info(state: Any) -> bool:
    """Q2 M1: báo lỗi VPN mà máy của chính người gửi đã đăng ký, chứng chỉ còn hạn, chưa nêu hành động → trả lời theo KB."""
    facts = state.get("facts") or {}
    return (
        state.get("intent") == "vpn"
        and not (state.get("slots") or {}).get("action")
        and facts.get("device_owner_is_requester") is True
        and facts.get("device_registered") is True
        and facts.get("cert_status") == "valid"
    )


# Kiểm thử 17/11: câu trả lời của vòng hỏi tiếp hứa chuyển kỹ thuật viên ("mình sẽ chuyển bạn cho kỹ thuật viên nhé") — hệ thống không
# chuyển gì cả nếu gửi câu đó kèm nút Đã ổn / Chưa ổn. So trên bản thường hoá (bỏ hoa, gộp khoảng trắng).
PROMISES_HANDOFF = re.compile(r"(?:sẽ|đã|để mình|mình)\s+(?:\w+\s+){0,3}?chuyển\b[^.\n]{0,60}?kỹ thuật viên")


def promises_handoff(text: str) -> bool:
    return PROMISES_HANDOFF.search(" ".join(text.casefold().split())) is not None


# D-100 (kiểm thử 17/11): câu HỎI trạng thái chứng chỉ ("… còn hạn không", "hết hạn chưa", "khi nào hết hạn", "kiểm tra … còn hạn") — so
# trên bản thường hoá (NFC, bỏ hoa, gộp khoảng trắng). Câu báo lỗi ("chứng chỉ còn hạn mà vẫn lỗi 809") KHÔNG khớp: cần từ hỏi ngay sau.
_ASK = r"(?:không|ko|k|chưa|chứ|hông|hong|hok|hay\s+không|hay\s+chưa)\b"
VPN_STATUS_QUESTION = re.compile(
    rf"còn\s+hạn(?:\s+(?:sử\s+dụng|dùng))?\s+{_ASK}"
    rf"|còn\s+(?:hiệu\s+lực|dùng\s+được|sử\s+dụng\s+được)\s+{_ASK}"
    r"|hết\s+hạn\s+(?:chưa|hay\s+chưa|khi\s+nào|lúc\s+nào|bao\s+giờ|ngày\s+nào|vào\s+(?:ngày|lúc)\s+nào)"
    r"|(?:khi\s+nào|lúc\s+nào|bao\s+giờ|ngày\s+nào|hôm\s+nào)\s+(?:\S+\s+){0,6}?hết\s+hạn"
    r"|hạn(?:\s+(?:dùng|sử\s+dụng))?\s+(?:đến|tới)\s+(?:khi\s+nào|lúc\s+nào|bao\s+giờ|ngày\s+nào)"
    r"|còn\s+(?:bao\s+nhiêu|mấy)\s+ngày"
    r"|(?:kiểm\s+tra|xem|tra|check)\s+(?:giúp|hộ|dùm|giùm)?\s*(?:\S+\s+){0,6}?(?:trạng\s+thái|hiệu\s+lực|hạn\s+chứng\s+chỉ)"
    r"|trạng\s+thái\s+(?:của\s+)?(?:vpn|chứng\s+chỉ)"
)
# Hỏi CÁCH làm → câu trả lời KB (không ép kiểm tra); có động từ ghi → người dùng nhờ làm, giữ `action` của B3/B6.
VPN_HOW_TO = re.compile(r"làm\s+(?:sao|thế\s+nào|cách\s+nào)|cách\s+(?:nào|để|kiểm\s+tra|xem)|hướng\s+dẫn|thế\s+nào\s+để|tự\s+(?:kiểm\s+tra|xem|check)|ở\s+đâu")
VPN_WRITE_VERB = re.compile(r"gia\s+hạn|cấp\s+(?:lại|mới)|đăng\s+ký|thu\s+hồi|renew|reissue")
STATUS_FALLBACK_ACTIONS: frozenset[str | None] = frozenset({None, "check_vpn_status", "renew_vpn_cert", "reissue_vpn_access"})


def vpn_status_question(text: str) -> bool:
    t = " ".join(unicodedata.normalize("NFC", text).casefold().split())
    return VPN_STATUS_QUESTION.search(t) is not None and VPN_HOW_TO.search(t) is None and VPN_WRITE_VERB.search(t) is None


def vpn_status_fallback(state: Any) -> bool:
    """D-100: câu HỎI trạng thái chứng chỉ VPN máy của CHÍNH người gửi, B6 đã có fact chứng chỉ → kiểm tra (chỉ đọc) thay cho câu trả lời
    KB (KB không có số liệu từng máy). Không áp cho vòng hỏi tiếp; `action` khác nhóm VPN (B3) → không ép."""
    facts = state.get("facts") or {}
    slots = state.get("slots") or {}
    return (
        state.get("intent") == "vpn"
        and int(state.get("followup_round") or 0) == 0
        and slots.get("action") in STATUS_FALLBACK_ACTIONS
        and bool(slots.get("device_id"))
        and facts.get("device_owner_is_requester") is True
        and isinstance(facts.get("cert_status"), str)
        and vpn_status_question(str(state.get("redacted_request") or ""))
    )


def previous_answer(state: Any) -> str:
    """Q13a (D-78): biến `previous_answer` của `b10_answer` — câu trả lời KB đã gửi ở vòng trước (chỉ khi đang ở vòng hỏi tiếp), còn lại
    `NO_PREVIOUS_ANSWER`. Là chữ BOT đã qua output guard, không phải chữ người dùng."""
    if int(state.get("followup_round") or 0) <= 0:
        return NO_PREVIOUS_ANSWER
    return last_answer(state) or NO_PREVIOUS_ANSWER


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
        if state.get("intent") in ANSWER_ONLY_INTENTS:  # D-76: chỉ trả lời — ép `info`, KHÔNG gọi b10_need_type
            info["need_type"], info["answer_only"] = "info", True
            return await _answer(state, info, chunks, kb_version, above, symptom=False)
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
        need_type = need.type
        if need_type == "info" and (state.get("slots") or {}).get("action") in INFO_TO_ACTION_SLOTS:
            info["need_type_override"], need_type = "view_permissions_slot", "action"  # K3 (V22): B3 đã nhận việc xem quyền
        if vpn_status_fallback(state):  # D-100: hỏi trạng thái chứng chỉ máy của mình → kiểm tra (chỉ đọc), không trả lời bằng KB
            info["need_type_override"] = "vpn_status_question"
            return await goto(
                state, S_RETRIEVING, next_node="b11_slots", step="B10", event="needs_action", audit_detail=info,
                need_type="action", slots={**(state.get("slots") or {}), "action": "check_vpn_status"},
            )  # fmt: skip
        info["symptom_to_info"] = symptom = need_type == "action" and symptom_to_info(state)
        if need_type == "action" and not symptom:
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
        return await _answer(state, info, chunks, kb_version, above, symptom=symptom)

    async def _dead_end(
        state: Any, info: dict[str, Any], *, step: str, event: str, kb_version: str | None = None
    ) -> dict[str, Any]:
        """Thiếu căn cứ để trả lời (D-100): vòng hỏi tiếp → E8; còn lại E3 như cũ (`step` B9 | B10 giữ đúng dòng audit cũ)."""
        if int(state.get("followup_round") or 0) > 0:
            note = followup_note(state)
            info["followup_dead_end"] = event
            extra: dict[str, Any] = {"user_feedback": note} if note else {}
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="followup_unresolved", audit_detail=info,
                exit_code=ExitCode.E8.value, need_type="info", **extra,
            )  # fmt: skip
        if step == "B9":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B9", event="no_evidence", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="no_grounding", kb_version=kb_version,
            )  # fmt: skip
        if event == "cannot_answer":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="cannot_answer", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="no_grounding",
            )  # fmt: skip
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B10", event="no_evidence", audit_detail=info,
            exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="no_grounding",
        )  # fmt: skip

    async def _answer(
        state: Any, info: dict[str, Any], chunks: list[ChunkRef], kb_version: str, above: bool, *, symptom: bool
    ) -> dict[str, Any]:
        """B9 → expand → `b10_answer` → hậu kiểm → output guard → gửi (nhánh `info` — cũ, và `it_help` D-76).

        R1 (soát 12/11, agent 16 F4): D-80 viết lại ĐẠT ngưỡng → cập nhật `retrieved`, `retrieval_score`, `kb_version` của state theo kết quả
        MỚI (mọi kết cục sau đó) — ghi chú bàn giao L2 đọc state, không được thấy bài cũ dưới ngưỡng."""
        fresh: dict[str, Any] = {}
        if not above and deps.enable_query_rewrite:  # D-80: viết lại câu hỏi rồi truy hồi lại MỘT lần, CÙNG ngưỡng
            chunks, kb_version, above, score = await _rewrite_retry(state, info, chunks, kb_version)
            if above:
                fresh = {"retrieved": chunks, "retrieval_score": score, "kb_version": kb_version}
        out = await _grounded(state, info, chunks, kb_version, above, symptom=symptom)
        return {**out, **fresh}

    async def _grounded(
        state: Any, info: dict[str, Any], chunks: list[ChunkRef], kb_version: str, above: bool, *, symptom: bool
    ) -> dict[str, Any]:
        if not above:  # B9 (S0-P2): câu trả lời cần đoạn KB đạt ngưỡng — kiểm TRƯỚC expand/b10_answer
            # kb_version: cột audit_logs.kb_version như dòng B9 cũ ở B8 (soát NGHI-5)
            return await _dead_end(state, info, step="B9", event="no_evidence", kb_version=kb_version)
        # R2 (soát 12/11, agent 16 F2): ngưỡng áp MỌI đoạn làm bằng chứng — đoạn dưới ngưỡng (vd bài gây nhiễu 0,02 xếp hạng 2) không vào
        # `expand_for_answer` nên cũng không là anchor hợp lệ (trích nó → `invalid_citation`). Hạng 1 đã đạt ở B9 → còn ít nhất một đoạn.
        floor = deps.constants.RETRIEVAL_THRESHOLD
        if any(c.score < floor for c in chunks):
            info["below_threshold_dropped"] = sum(c.score < floor for c in chunks)
            chunks = [c for c in chunks if c.score >= floor]
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
            return await _dead_end(state, info, step="B10", event="no_evidence")
        try:
            ans, meta = await deps.llm.complete(
                "strong", "b10_answer",
                {"question": state["redacted_request"], "evidence": evidence, "previous_answer": previous_answer(state)},
                AnswerOut,
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
            return await _dead_end(state, info, step="B10", event="cannot_answer")
        if info["citation"] == "invalid_citation":
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B10", event="invalid_citation", audit_detail=info,
                exit_code=ExitCode.E3.value, need_type="info", escalation_reason_detail="invalid_citation",
            )  # fmt: skip
        by_id = {c.chunk_id: c for c in chunks}
        cited = [by_id[i] for i in dict.fromkeys(ans.citations)]
        info["cited"] = [c.chunk_id for c in cited]
        intro = symptom_intro((state.get("slots") or {}).get("device_id"), state.get("facts") or {}) if symptom else None
        steps, info["steps_truncated"] = cap_steps(ans.steps)  # Q2 M2: tối đa 3 bước, bước LLM xếp đầu được giữ
        body = render_answer(ans.answer_markdown, steps, cited, intro=intro)
        if int(state.get("followup_round") or 0) > 0 and promises_handoff(ans.answer_markdown):  # hứa chuyển → chuyển thật (E8)
            return await _dead_end(state, info, step="B10", event="answer_promises_handoff")
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

    async def _rewrite_retry(
        state: Any, info: dict[str, Any], chunks: list[ChunkRef], kb_version: str
    ) -> tuple[list[ChunkRef], str, bool, float | None]:
        """D-80 (chấm thử 11/11): câu hỏi gõ không dấu / viết tắt / có lời chào, từ đệm cho điểm truy hồi dưới ngưỡng dù KB có bài. LLM
        `b09_rewrite_query` viết lại câu (CHỈ để truy hồi) → truy hồi lại một lần → áp CÙNG `RETRIEVAL_THRESHOLD`. Đạt → dùng đoạn mới
        làm căn cứ (câu hỏi gửi `b10_answer` vẫn là câu gốc đã che). Lỗi LLM/RAG, câu viết lại trùng câu gốc, hoặc vẫn dưới ngưỡng → giữ
        nguyên (E3 như trước) — lỗi KHÔNG đổi E3 thành E2. Audit chỉ điểm/cờ, không chữ."""
        original = state["redacted_request"]
        rec: dict[str, Any] = {"tried": True, "changed": False, "top_score": None, "above_threshold": False, "error": None}
        info["rewrite"] = rec
        try:
            out, _meta = await deps.llm.complete(
                "fast", "b09_rewrite_query", {"question": original}, RewriteQueryOut, kb_version=kb_version
            )  # fmt: skip
        except (LLMSchemaError, LLMUnavailable, LLMBudgetExceeded) as exc:
            rec["error"] = type(exc).__name__
            return chunks, kb_version, False, None
        rewritten = out.query.strip()
        if not rewritten or rewritten.casefold() == original.strip().casefold():
            return chunks, kb_version, False, None
        rec["changed"] = True
        q = build_query(rewritten, state.get("intent"), state.get("slots") or {}, query_slots=deps.query_slots)
        try:
            res = await deps.rag.retrieve(q, state["requester_context"])
        except RetrievalSystemError as exc:
            rec["error"] = exc.stage
            return chunks, kb_version, False, None
        g = grounding(list(res.chunks), res.top_score, deps.constants.RETRIEVAL_THRESHOLD)
        rec["top_score"], rec["above_threshold"] = res.top_score, g["above_threshold"]
        if not g["above_threshold"]:
            return chunks, kb_version, False, None
        info["grounding"] = g
        return list(res.chunks), res.kb_version, True, res.top_score

    return b10_route
