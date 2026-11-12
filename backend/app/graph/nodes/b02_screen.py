"""B2 — sàng lọc prompt injection THẬT (B02 mục 2, 5; thiết kế Phase 3 mục 8.5; PLAN-3e).

Thứ tự rẻ → đắt, không lớp nào "mở cửa" khi lớp trước lỗi:
1. L2 regex (`guard.injection.match`, L0 bên trong): khớp → E0 `S_BLOCKED`, `layer_decided=regex`.
2. L3 `deps.ml.classify` (chưa nạp model → `model_missing` → xuống L4 ngay, không retry). ML-GAN — `B2_CLASSIFIER_MODE`
   đọc MỘT lần trong `make`: `active`: `p_mal ≥ TAU_BLOCK` → E0; `≤ TAU_PASS` → qua; giữa hai ngưỡng HOẶC lỗi → L4.
   `shadow` (mặc định): vẫn gọi, ghi `p_mal` (kể cả nhánh E2), nhưng KHÔNG chặn/cho qua theo điểm — luôn xuống L4, đúng
   đường của `model_missing`. `screening` (và audit B2) mang `clf_mode` ở mọi nhánh đã qua L3.
3. L4 LLM fast `b02_injection_judge` (prompt riêng, không cache — [Chốt 17.5]): `is_attack` → E0, không → qua.
   `LLMUnavailable`/`LLMBudgetExceeded`/`LLMSchemaError` → E2 `S_ESCALATED` + `security_flag` +
   `screening_unavailable` (không đi tiếp khi chưa sàng lọc được, nhưng cũng không gắn nhãn tấn công — B02 mục 6).
4. Hết hạn cả lượt (`TurnBudgetExceeded`, phase3 9.0) ở L3 hoặc L4 → E2 `turn_budget_exceeded` + `security_flag` (chưa
   sàng lọc xong — cùng lý do như `screening_unavailable`; bắt tường minh thay vì để boundary, Q-3f-2).

Phase 5 gói 1 (D-52; `dac-ta-bat-2-model.md` 4.1–4.4, bảng 4.2): quyết định sau L3/L4 ở `guard/b2_review.py` (thuần).
- `review`: L3 chấm trên bản đã THAY NHÃN CHE (`guard/mask_words.py` — chỉ đầu vào model; L4, văn bản lưu, audit giữ bản chưa
  thay); KHÔNG bao giờ quyết thẳng theo điểm — mọi câu không khớp regex đều qua L4. L4 nói tấn công HOẶC `category ≠ none` → E0;
  L4 nói không mà `p_mal ≥ τ` (`B2_TAU_REVIEW`) hoặc 422 `too_many_windows` → E1 `injection_suspected` (`S_ESCALATED`, quy tắc 2
  của D-29; KHÔNG `security_event`, KHÔNG `security_flag`; B20 gửi tin E0); còn lại (p < τ, lỗi hạ tầng, model chưa nạp) → B3.
- `category ≠ none` → E0 áp cả `shadow`/`active` (#3).
- `screening` ở mọi nhánh đã gọi L3: `ml_error`, `masks_replaced`; mọi nhánh đã gọi L4: `llm_is_attack`, `llm_category`,
  `llm_role`, `llm_model` (model thật đã trả lời — `LLMMeta.model`). Không có chữ người dùng.

E0: `security_events(injection_detected)` QUA `effects.once("security_event")` (chạy lại node không ghi hai lần);
`detail`/`screening` KHÔNG chứa câu người dùng. Tin trung tính cho người dùng do B20 gửi theo mẫu E0 sẵn có (không nêu
lớp/mẫu nào bắt). Lỗi khác (`ScriptExhausted`, `PromptContractError`, `MlContractError`…) là bug → boundary → E9.
"""

from typing import Any, Literal

from app.core.turn_budget import TurnBudgetExceeded
from app.domain.exit_codes import BlockReason, CloseReason, ExitCode
from app.domain.states import S_BLOCKED, S_CLASSIFYING, S_ESCALATED
from app.graph import effects
from app.graph.fakes import NodeDeps
from app.graph.goto import goto
from app.graph.tracing import NodeFn
from app.guard import injection
from app.guard.b2_review import after_judge, classifier_shortcut
from app.guard.mask_words import mask_regex, replace_masks
from app.guard.patterns import privacy_patterns
from app.guard.screen import hit_from_payload
from app.llm import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.llm.schemas import InjectionJudgeOut
from app.settings import get_settings

JUDGE_ROLE: Literal["fast"] = "fast"  # ghi vào `screening.llm_role`; đổi vai trò (gói 3) thì đổi cả lời gọi bên dưới
SUSPECTED = "injection_suspected"


def make(deps: NodeDeps) -> NodeFn:
    settings = get_settings()
    clf_mode = settings.b2_classifier_mode  # một lần khi dựng graph — mode lạ đã bị Settings từ chối
    tau = settings.b2_tau_review  # gói 1: `review` thiếu τ → Settings đã từ chối khởi động
    masks = privacy_patterns(settings.config_dir) if clf_mode == "review" else None
    if masks is not None:
        mask_regex(masks)  # gói 1: nhãn che không có từ thay → PatternFileError → không khởi động

    async def b02_screen(state: Any) -> dict[str, Any]:
        text = state["redacted_request"]
        if (hit := injection.match(text)) is not None:  # L2 (L0 bên trong)
            return await _block(state, layer_decided="regex", pattern_id=hit.id, group=hit.group)
        if (raw := hit_from_payload(state.get("raw_screen_hit"))) is not None:  # D-92: API khớp trên bản GỐC (che đã nuốt từ khoá)
            return await _block(state, layer_decided="regex", pattern_id=raw.id, group=raw.group, matched_on="raw")
        try:
            return await _screen(state, text)
        except TurnBudgetExceeded:  # 9.0: chưa sàng lọc xong mà lượt hết hạn — không cho qua
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B2", event="turn_budget_exceeded",
                audit_detail={"error": "TurnBudgetExceeded"}, exit_code=ExitCode.E2.value,
                security_flag=True, escalation_reason_detail="turn_budget_exceeded",
            )  # fmt: skip

    async def _screen(state: Any, text: str) -> dict[str, Any]:
        model_text, replaced = replace_masks(text, masks) if masks is not None else (text, 0)  # gói 1: chỉ `review`
        r = await deps.ml.classify(model_text)  # L3
        ok = r.error is None and r.data is not None
        p_mal = r.data.p_malicious if ok and r.data is not None else None
        clf_version = r.data.version if ok and r.data is not None else None  # E1 soát 12/11: lineage — model nào đã chấm
        base = {"p_mal": p_mal, "clf_mode": clf_mode, "ml_error": r.error, "masks_replaced": replaced, "clf_version": clf_version}
        if (quick := classifier_shortcut(clf_mode, p_mal)) is not None:  # chỉ `active`
            decide = _block if quick.outcome == "E0" else _pass
            return await decide(state, layer_decided=quick.layer, **base)
        try:  # L4: mọi câu ở `shadow`/`review`; vùng giữa HOẶC L3 lỗi ở `active` — L4 nhận bản CHƯA thay nhãn
            out, meta = await deps.llm.complete(  # vai trò là chuỗi literal: test AST d10 đối chiếu với file prompt
                "fast", "b02_injection_judge", {"text": text}, InjectionJudgeOut, cache_policy="bypass"
            )
        except (LLMUnavailable, LLMBudgetExceeded, LLMSchemaError) as exc:
            return await goto(
                state, S_ESCALATED, next_node="b20_audit", step="B2", event="guard_unavailable",
                audit_detail={
                    "ml_error": r.error, "llm_error": type(exc).__name__, "p_mal": p_mal, "clf_mode": clf_mode,
                    "clf_version": clf_version,
                },
                exit_code=ExitCode.E2.value, security_flag=True,
                escalation_reason_detail="screening_unavailable",
            )  # fmt: skip
        verdict = after_judge(
            clf_mode, p_mal=p_mal, ml_error=r.error, is_attack=out.is_attack, category=out.category, tau=tau
        )
        info = {
            "layer_decided": verdict.layer, **base, "llm_is_attack": out.is_attack, "llm_category": out.category,
            "llm_role": JUDGE_ROLE, "llm_model": meta.model,
        }  # fmt: skip
        if verdict.outcome == "E0":
            return await _block(state, **info)
        if verdict.outcome == "E1":
            return await _suspect(state, **info)
        return await _pass(state, **info)

    async def _block(state: Any, **info: Any) -> dict[str, Any]:
        # `info` chỉ có lớp, id/nhóm mẫu, p_mal, clf_mode, phiên bản L3, mã lỗi L3, số nhãn đã thay, phán quyết/vai trò/model của L4 — KHÔNG
        # có câu người dùng (8.5)
        await effects.once(
            state, "security_event", deps.security_events.record, "injection_detected",
            ticket_id=state["ticket_id"], detail=info, step="B2",
        )  # fmt: skip
        return await goto(
            state, S_BLOCKED, next_node="b20_audit", step="B2", event="injection_detected",
            exit_code=ExitCode.E0.value, block_reason=BlockReason.INJECTION_DETECTED.value,
            close_reason=CloseReason.BLOCKED_INJECTION_DETECTED.value, screening=info,
        )  # fmt: skip

    async def _suspect(state: Any, **info: Any) -> dict[str, Any]:
        # gói 1 (#4, #5): chuyển L2, KHÔNG security_event, KHÔNG security_flag; S_SCREENING → S_ESCALATED theo quy tắc 2 (D-29)
        return await goto(
            state, S_ESCALATED, next_node="b20_audit", step="B2", event=SUSPECTED, exit_code=ExitCode.E1.value,
            escalation_reason_detail=SUSPECTED, screening=info,
        )  # fmt: skip

    async def _pass(state: Any, **info: Any) -> dict[str, Any]:
        return await goto(
            state, S_CLASSIFYING, next_node="b03_classify", step="B2", event="screened", screening=info
        )

    return b02_screen
