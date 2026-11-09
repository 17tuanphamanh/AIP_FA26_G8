"""Q3 M5 (ĐP 09/11): tin người dùng của E5 theo lý do.

Bằng chứng (demo): E5 `llm_high_risk` → "Yêu cầu của bạn cần được xem xét kỹ hơn trước khi xử lý." — không lý do, không bước tiếp. Nay
`config/escalation_templates.yaml` mục E5 có `user_message_by_reason` (đọc như `next_for_l2_by_reason`): B20 chọn theo
`escalation_reason_detail`, thiếu/lạ → `user_message` mặc định. Khuôn câu: vì sao (chung — không lộ luật/điểm), ai xử lý, người dùng chờ ở
đâu. E0 GIỮ NGUYÊN (không tiết lộ). Không đổi mã thoát/route.
"""

import re
from typing import Any

import pytest
from app.domain.exit_codes import REASON_DETAILS, ExitCode
from app.settings import EscalationTemplates, get_escalation_templates
from pydantic import ValidationError
from tests.fakes.graph import GraphHarness

TEMPLATES = get_escalation_templates()
E5 = TEMPLATES.of("E5")

# Câu ĐP soạn (lời giao Q3 M5) — đúng từng chữ.
DEFAULT = ("Yêu cầu này cần kỹ thuật viên xem xét trước khi làm. Mình đã chuyển kèm thông tin đã kiểm tra; kết quả sẽ báo bạn "
           "tại đây.")  # fmt: skip
DP = {
    "llm_high_risk": ("Yêu cầu này cần kỹ thuật viên xem trực tiếp trước khi làm để tránh thao tác nhầm. Mình đã chuyển kèm thông "
                      "tin đã kiểm tra; kết quả sẽ báo bạn tại đây."),
    "policy_deny": ("Theo quy định của công ty, việc này không được thực hiện tự động. Mình đã chuyển kỹ thuật viên xem xét; bạn sẽ "
                    "nhận phản hồi tại đây."),
    "approval_target_unverified": ("Máy hoặc tài khoản này không thuộc tài khoản của bạn nên mình không tự xử lý được. Mình đã chuyển "
                                   "kỹ thuật viên kiểm tra; bạn sẽ nhận phản hồi tại đây."),
}  # fmt: skip
# Mọi lý do E5 có trong code (graph/**: `exit_code=E5` + `escalation_reason_detail`) — 6 lý do ngoài 3 câu ĐP: câu đề xuất [chờ ĐP duyệt].
E5_REASONS = frozenset({
    "llm_high_risk", "policy_deny", "approval_target_unverified", "llm_layer_disabled", "no_valid_approver",
    "approver_no_longer_valid", "person_no_longer_valid", "action_plan_changed_since_approval", "recheck_failed",
})  # fmt: skip
E0_TEXT = "Yêu cầu của bạn đã được ghi nhận và chuyển cho bộ phận IT xem xét."


def test_e5_default_and_dp_sentences_exact() -> None:
    assert E5.user_message == DEFAULT
    for reason, text in DP.items():
        assert E5.user_message_by_reason[reason] == text, reason
        assert E5.user_message_for(reason) == text


def test_every_e5_reason_has_sentence_and_keys_known() -> None:
    assert E5_REASONS <= REASON_DETAILS
    assert set(E5.user_message_by_reason) == E5_REASONS


@pytest.mark.parametrize("reason", sorted(E5_REASONS))
def test_sentence_shape_no_rule_or_score(reason: str) -> None:
    """Khuôn: có người xử lý (kỹ thuật viên), có nơi chờ ("tại đây"); không lộ mã luật, điểm, xác suất; giọng "mình/bạn"."""
    text = E5.user_message_for(reason)
    assert "kỹ thuật viên" in text and "tại đây" in text
    assert not re.search(r"\bR\d{1,3}\b|điểm|xác suất|%|\d", text), text
    for banned in ("chúng tôi", "anh/chị", "quý khách", " ạ"):
        assert banned not in text


@pytest.mark.parametrize("reason", [None, "", "khong_co_that", "clarification_exhausted"])
def test_unknown_or_missing_reason_default(reason: str | None) -> None:
    assert E5.user_message_for(reason) == DEFAULT


def test_e0_unchanged_and_other_codes_have_no_reason_map() -> None:
    assert TEMPLATES.of("E0").user_message == E0_TEXT
    for code in ExitCode:
        if code is not ExitCode.E5:
            assert TEMPLATES.of(code.value).user_message_by_reason == {}, code


def test_reason_keys_validated() -> None:
    raw = TEMPLATES.model_dump(mode="json")
    raw["codes"]["E5"]["user_message_by_reason"] = {"khong_co_that": "x"}
    with pytest.raises(ValidationError, match="khong_co_that"):
        EscalationTemplates.model_validate(raw)
    raw["codes"]["E5"]["user_message_by_reason"] = {"policy_deny": ""}
    with pytest.raises(ValidationError):
        EscalationTemplates.model_validate(raw)


# ---- B20 chọn câu theo lý do ----------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", sorted(E5_REASONS))
async def test_b20_sends_reason_sentence(reason: str, monkeypatch: pytest.MonkeyPatch) -> None:
    h, r = await _e5_with_reason(monkeypatch, reason)
    assert r.values["exit_code"] == "E5"
    assert h.notifier.sent[-1] == ("t1", E5.user_message_for(reason), "none")
    assert r.values["conversation"][-1]["text"] == E5.user_message_by_reason[reason]


@pytest.mark.asyncio
async def test_b20_unknown_reason_default(monkeypatch: pytest.MonkeyPatch) -> None:
    h, _ = await _e5_with_reason(monkeypatch, None)
    assert h.notifier.sent[-1] == ("t1", DEFAULT, "none")


async def _e5_with_reason(monkeypatch: pytest.MonkeyPatch, reason: str | None) -> tuple[GraphHarness, Any]:
    """Node giả B12 `deny` → E5; lý do đặt qua state ngay trước B20 (bọc node B20 thật — harness dựng SAU khi bọc)."""
    from app.graph.nodes import b20_audit

    real_make = b20_audit.make

    def make(deps: object) -> object:
        inner = real_make(deps)  # type: ignore[arg-type]

        async def node(state: dict[str, object]) -> object:
            patched = dict(state)
            if reason is None:
                patched.pop("escalation_reason_detail", None)
            else:
                patched["escalation_reason_detail"] = reason
            return await inner(patched)

        return node

    monkeypatch.setattr(b20_audit, "make", make)
    h = GraphHarness()
    return h, await h.submit("t1", b12_assess="deny")
