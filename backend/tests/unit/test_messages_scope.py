"""P6 lời nói (ĐP 08/11), mục 1: tin chuyển người E1 / E3 / E4 nói trước trợ lý hỗ trợ được gì, rồi mới báo đã chuyển.

- Danh sách loại việc trong câu mở đầu lấy theo `enabled_intents` (mặc định của `Settings`, đối chiếu `slots.yaml`): bảng nhãn dưới
  đây phải trùng ĐÚNG tập intent đang bật — bật thêm intent mà quên nhãn/câu thì đỏ ở đây, không bịa thêm, không thiếu.
- E0 và nhánh E1 `injection_suspected` (B20 dùng mẫu E0) giữ NGUYÊN câu trung tính: không nêu phạm vi, không lộ lý do, để kẻ dò
  không biết mình bị nhận ra (D-52).
- Chỉ đổi chữ của `config/escalation_templates.yaml`: route, mã thoát, `next_for_l2` không thuộc test này.
"""

from collections.abc import Iterator

import pytest
from app.domain.states import S_CLARIFYING
from app.graph.late_event import deliver_event
from app.graph.nodes.b20_audit import SUSPECTED_MESSAGE_CODE, _message_code
from app.llm.providers.scripted import Reply
from app.settings import Settings, get_escalation_templates, get_settings, get_slots
from tests.fakes.fake_ml import FakeMlService
from tests.fakes.graph import GraphHarness
from tests.fakes.identity import SESSION
from tests.unit.test_b02_review import JUDGE, NORMAL, NOT_ATTACK, _env

TEMPLATES = get_escalation_templates()

# Nhãn người dùng thấy cho từng intent — đúng thứ tự `Settings.enabled_intents` (vpn, account, software, access).
INTENT_LABEL = {
    "vpn": "VPN",
    "account": "tài khoản và mật khẩu",
    "software": "cài phần mềm",
    "access": "quyền truy cập thư mục",
}
SCOPE_LABELS = ("VPN", "tài khoản và mật khẩu", "cài phần mềm", "quyền truy cập thư mục")

# Test vàng câu chữ (phần sau câu phạm vi). E1 / E3 / E4 = SCOPE + đuôi.
E1_TAIL = "Yêu cầu này mình đã chuyển kỹ thuật viên hỗ trợ bạn."
E3_TAIL = "Mình chưa có thông tin về việc này nên đã chuyển cho kỹ thuật viên."  # giữ ý "chưa có thông tin về việc này" (TC16)
E4_TAIL = "Yêu cầu này mình đã chuyển kỹ thuật viên để hỗ trợ bạn trực tiếp."
# D-57 (ĐP chốt 09/11): cờ ENABLE_IT_HELP bật (mặc định) → tin E1 thật gửi đi dùng `user_message_it_help` — câu phạm vi thêm vế hướng dẫn
IT_HELP_CLAUSE = "; và hướng dẫn các sự cố IT thường gặp như máy in, Wi-Fi, Outlook."
E0_NEUTRAL = "Yêu cầu của bạn đã được ghi nhận và chuyển cho bộ phận IT xem xét."  # nguyên văn trước P6


@pytest.fixture
def _default_intents(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLED_INTENTS", raising=False)


def _enabled() -> list[str]:
    return Settings(_env_file=None).enabled_intents  # type: ignore[call-arg]


def _scope_sentence() -> str:
    return "Mình là trợ lý IT, hiện hỗ trợ: " + ", ".join(INTENT_LABEL[i] for i in _enabled()) + "."


def _says_scope(text: str) -> bool:
    return "trợ lý IT" in text or any(label in text for label in SCOPE_LABELS)


# ---- danh sách phạm vi bám intent đang bật ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_default_intents")
def test_scope_labels_cover_exactly_the_enabled_intents() -> None:
    enabled = _enabled()
    assert set(INTENT_LABEL) == set(enabled), "intent bật ≠ bảng nhãn: sửa bảng nhãn VÀ câu mở đầu của E1/E3/E4 cho khớp"
    assert set(enabled) <= set(get_slots().intents)  # intent bật phải có khai báo slot (không bịa loại việc)
    assert list(INTENT_LABEL) == enabled  # cùng thứ tự với cấu hình


@pytest.mark.usefixtures("_default_intents")
def test_scope_sentence_is_the_one_in_the_task() -> None:
    assert _scope_sentence() == (
        "Mình là trợ lý IT, hiện hỗ trợ: VPN, tài khoản và mật khẩu, cài phần mềm, quyền truy cập thư mục."
    )


# ---- E1 / E3 / E4: câu phạm vi TRƯỚC, rồi mới báo đã chuyển ----------------------------------------------------------


@pytest.mark.usefixtures("_default_intents")
@pytest.mark.parametrize(("code", "tail"), [("E1", E1_TAIL), ("E3", E3_TAIL), ("E4", E4_TAIL)])
def test_handoff_messages_state_scope_then_transfer(code: str, tail: str) -> None:
    text = TEMPLATES.of(code).user_message
    assert text == f"{_scope_sentence()} {tail}"
    assert text.startswith(_scope_sentence())  # nói làm được gì trước
    assert "kỹ thuật viên" in text.split(_scope_sentence(), 1)[1]  # rồi mới báo đã chuyển


def test_e3_keeps_the_no_information_idea() -> None:
    assert "chưa có thông tin về việc này" in TEMPLATES.of("E3").user_message


# ---- E0 và mọi mã không thuộc diện đổi: không nêu phạm vi ------------------------------------------------------------


def test_e0_stays_the_neutral_sentence_byte_for_byte() -> None:
    text = TEMPLATES.of("E0").user_message
    assert text == E0_NEUTRAL
    assert not _says_scope(text)


@pytest.mark.parametrize("code", ["E0", "E2", "E5", "E6", "E7", "E8", "E9"])
def test_other_codes_do_not_state_scope(code: str) -> None:
    assert not _says_scope(TEMPLATES.of(code).user_message)


# ---- B20 chọn tin: injection_suspected dùng mẫu E0 (câu trung tính), mọi lý do E1 khác dùng mẫu E1 ----------------------


def test_b20_message_code_suspected_uses_e0_template() -> None:
    assert SUSPECTED_MESSAGE_CODE == {"injection_suspected": "E0"}
    assert _message_code({"escalation_reason_detail": "injection_suspected"}, "E1") == "E0"
    for reason in ("out_of_scope", "intent_low_confidence", "intent_not_enabled", None):
        assert _message_code({"escalation_reason_detail": reason}, "E1") == "E1"
    text = TEMPLATES.of(_message_code({"escalation_reason_detail": "injection_suspected"}, "E1")).user_message
    assert text == E0_NEUTRAL and not _says_scope(text)


# ---- đường chạy thật qua B20 (harness giả): người dùng nhận đúng tin -------------------------------------------------


async def _sent_text(h: GraphHarness, ticket: str) -> str:
    """Tin cuối gửi cho ticket = tin của B20 (ca E4 có thêm câu hỏi lại ở trước)."""
    return [s for s in h.notifier.sent if s[0] == ticket][-1][1]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_default_intents")
async def test_b20_sends_scope_message_for_e1_e3_e4() -> None:
    h = GraphHarness()
    await h.submit("e1", b03_classify="out_of_scope")
    await h.submit("e3", b08_retrieve="no_evidence")
    await h.submit("e4", b11_slots="missing")
    await deliver_event(h.runner, "e4", S_CLARIFYING, {"kind": "timeout"})
    # Q12 (ĐP 09/11, đổi kỳ vọng đã duyệt): E1 có vế hướng dẫn khi cờ bật; E3/E4 giữ nguyên
    assert await _sent_text(h, "e1") == f"{_scope_sentence()[:-1]}{IT_HELP_CLAUSE} {E1_TAIL}"
    assert await _sent_text(h, "e3") == f"{_scope_sentence()} {E3_TAIL}"
    assert await _sent_text(h, "e4") == f"{_scope_sentence()} {E4_TAIL}"


@pytest.mark.asyncio
async def test_b20_sends_neutral_e0_for_blocked_injection() -> None:
    h = GraphHarness()
    await h.submit("t1", b02_screen="injection")
    assert await _sent_text(h, "t1") == E0_NEUTRAL


@pytest.fixture
def _b2_review_mode(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "review")
    monkeypatch.setenv("B2_TAU_REVIEW", "0.8")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
@pytest.mark.usefixtures("_b2_review_mode")
async def test_real_b2_injection_suspected_sends_e0_sentence_not_e1() -> None:
    """Model chặn tấn công chấm cao nhưng LLM không xác nhận → E1 `injection_suspected` (mã E1 ở escalation) NHƯNG người dùng nhận
    đúng câu E0: không phạm vi, không "kỹ thuật viên hỗ trợ bạn" — E1 riêng sẽ cho kẻ dò biết đã lừa được LLM chấm."""
    h, _ = _env({JUDGE: [Reply(NOT_ATTACK)]}, ml=FakeMlService(classify_p=0.95))
    v = (await h.submit_as("t1", SESSION, text=NORMAL)).values
    assert (v["exit_code"], v["escalation_reason_detail"]) == ("E1", "injection_suspected")
    text = await _sent_text(h, "t1")
    assert text == E0_NEUTRAL
    assert text != TEMPLATES.of("E1").user_message
    assert not _says_scope(text) and "kỹ thuật viên" not in text
    assert v["conversation"][-1]["text"] == text
