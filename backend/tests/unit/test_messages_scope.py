"""P6 lời nói (ĐP 08/11), mục 1: tin chuyển người E1 / E3 nói trước trợ lý hỗ trợ được gì, rồi mới báo đã chuyển.
U3 (soát 12/11, agent 18 L2 — kế hoạch TA duyệt 12/11): E4 THÔI nêu phạm vi — E4 chỉ xảy ra sau khi B11 đã hỏi thêm cho một yêu cầu TRONG
phạm vi, nên câu phạm vi lạc nghĩa; E4 nói "chưa đủ thông tin… đã chuyển kỹ thuật viên" (`E4_MESSAGE`).

- Danh sách loại việc trong câu mở đầu lấy theo `enabled_intents` (mặc định của `Settings`, đối chiếu `slots.yaml`): bảng nhãn dưới
  đây phải trùng ĐÚNG tập intent đang bật — bật thêm intent mà quên nhãn/câu thì đỏ ở đây, không bịa thêm, không thiếu.
- D-98 (TA chốt 17/11, thay D-52): E0 và nhánh E1 `injection_suspected` NÊU LÝ DO chung (không nêu phạm vi, không lộ điểm hay lớp
  chặn). E1 nghi có câu riêng ở `user_message_by_reason` của E1 — B20 không còn mượn mẫu E0.
- Chỉ đổi chữ của `config/escalation_templates.yaml`: route, mã thoát, `next_for_l2` không thuộc test này.
"""

from collections.abc import Iterator

import pytest
from app.domain.states import S_CLARIFYING
from app.graph.late_event import deliver_event
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
E4_MESSAGE = (
    "Mình chưa có đủ thông tin để làm tiếp yêu cầu này, nên đã chuyển kỹ thuật viên hỗ trợ bạn trực tiếp. Kỹ thuật viên có thể "
    "liên hệ bạn để hỏi thêm."
)
# D-76 (ĐP chốt 09/11): cờ ENABLE_IT_HELP bật (mặc định) → tin E1 thật gửi đi dùng `user_message_it_help` — câu phạm vi thêm vế hướng dẫn
IT_HELP_CLAUSE = "; và hướng dẫn các sự cố IT thường gặp như máy in, Wi-Fi, Outlook."
# D-98 (17/11): câu nêu lý do — test vàng nguyên văn.
E0_REASON = (
    "Tin nhắn này có phần nội dung giống câu lệnh điều khiển trợ lý chứ không phải yêu cầu hỗ trợ, nên để an toàn mình không xử lý "
    "tự động. Mình đã chuyển bộ phận IT kiểm tra; nếu đây là yêu cầu bình thường, kỹ thuật viên sẽ liên hệ lại bạn."
)
E1_SUSPECTED = (
    "Bước kiểm tra an toàn tự động chưa xác nhận được tin nhắn này, nên mình chưa làm gì để tránh thao tác nhầm. Mình đã chuyển kỹ "
    "thuật viên xem trực tiếp và kết quả sẽ báo bạn tại đây; nếu cần nhanh, bạn có thể gửi lại từng việc thành từng tin ngắn."
)
# Từ không được xuất hiện trong câu báo cho người dùng: lộ cơ chế chặn (điểm, model, regex, LLM, mã).
# "quy tắc" / "bỏ qua": câu không nhắc lại mẫu chặn (nhóm override) — test_b02_screen TC13 canh cùng ý.
LEAK_WORDS = ("điểm", "xác suất", "model", "mô hình", "regex", "llm", "injection", "tấn công", "e0", "e1", "quy tắc", "bỏ qua")


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
@pytest.mark.parametrize(("code", "tail"), [("E1", E1_TAIL), ("E3", E3_TAIL)])
def test_handoff_messages_state_scope_then_transfer(code: str, tail: str) -> None:
    text = TEMPLATES.of(code).user_message
    assert text == f"{_scope_sentence()} {tail}"
    assert text.startswith(_scope_sentence())  # nói làm được gì trước
    assert "kỹ thuật viên" in text.split(_scope_sentence(), 1)[1]  # rồi mới báo đã chuyển


def test_e4_says_missing_information_not_scope() -> None:
    template = TEMPLATES.of("E4")
    assert template.user_message == E4_MESSAGE and not _says_scope(E4_MESSAGE)
    assert template.user_message_it_help is None  # biến thể ENABLE_IT_HELP chỉ thêm vế phạm vi → bỏ
    assert template.user_message_for(None, it_help=True) == E4_MESSAGE
    assert all(not _says_scope(t) for t in template.user_message_repeat)


def test_e3_keeps_the_no_information_idea() -> None:
    assert "chưa có thông tin về việc này" in TEMPLATES.of("E3").user_message


# ---- E0 và mọi mã không thuộc diện đổi: không nêu phạm vi ------------------------------------------------------------


def test_e0_states_reason_byte_for_byte() -> None:
    text = TEMPLATES.of("E0").user_message
    assert text == E0_REASON
    assert not _says_scope(text)
    assert not any(w in text.casefold() for w in LEAK_WORDS)


@pytest.mark.parametrize("code", ["E0", "E2", "E4", "E5", "E6", "E7", "E8", "E9"])
def test_other_codes_do_not_state_scope(code: str) -> None:
    assert not _says_scope(TEMPLATES.of(code).user_message)


# ---- D-98: E1 injection_suspected có câu riêng nêu lý do; câu theo lý do thắng biến thể lặp và vế hướng dẫn -------------


def test_e1_suspected_has_own_reason_sentence() -> None:
    e1 = TEMPLATES.of("E1")
    for repeat in (0, 1, 2):
        for it_help in (False, True):
            text = e1.user_message_for("injection_suspected", it_help=it_help, repeat=repeat)
            assert text == E1_SUSPECTED
    assert E1_SUSPECTED != TEMPLATES.of("E0").user_message
    assert not _says_scope(E1_SUSPECTED)
    assert not any(w in E1_SUSPECTED.casefold() for w in LEAK_WORDS)
    assert "vì" in E1_SUSPECTED or "nên" in E1_SUSPECTED  # có lý do, không chỉ "đã chuyển"


# ---- đường chạy thật qua B20 (harness giả): người dùng nhận đúng tin -------------------------------------------------


async def _sent_text(h: GraphHarness, ticket: str) -> str:
    """Tin cuối gửi cho ticket = tin của B20 (ca E4 có thêm câu hỏi lại ở trước)."""
    return [s for s in h.notifier.sent if s[0] == ticket][-1][1]


@pytest.mark.asyncio
@pytest.mark.usefixtures("_default_intents")
async def test_b20_sends_scope_message_for_e1_e3_e4() -> None:
    # Q13c (11/11): mỗi ticket ở harness RIÊNG = ticket đầu phiên → câu đầy đủ có phạm vi (ticket sau cùng phiên dùng biến thể —
    # test_q13c_bot_lap.py). Ý định cũ giữ nguyên: E1/E3/E4 nêu phạm vi rồi mới báo đã chuyển.
    h1, h3, h4 = GraphHarness(), GraphHarness(), GraphHarness()
    await h1.submit("e1", b03_classify="out_of_scope")
    await h3.submit("e3", b08_retrieve="no_evidence")
    await h4.submit("e4", b11_slots="missing")
    await deliver_event(h4.runner, "e4", S_CLARIFYING, {"kind": "timeout"})
    # Q12 (ĐP 09/11): E1 có vế hướng dẫn khi cờ bật. Chấm thử 11/11 (đổi kỳ vọng có chủ đích): E3/E4 CŨNG có vế đó — câu hỏi phân loại
    # (D-75) hứa "hướng dẫn máy in, Wi-Fi, Outlook", E3 ngay sau mà chỉ kể 4 mảng là tự mâu thuẫn (ca D5 chấm thử). Đuôi giữ nguyên.
    assert await _sent_text(h1, "e1") == f"{_scope_sentence()[:-1]}{IT_HELP_CLAUSE} {E1_TAIL}"
    assert await _sent_text(h3, "e3") == f"{_scope_sentence()[:-1]}{IT_HELP_CLAUSE} {E3_TAIL}"
    assert await _sent_text(h4, "e4") == E4_MESSAGE  # U3: E4 không nêu phạm vi


@pytest.mark.asyncio
async def test_b20_sends_e0_reason_for_blocked_injection() -> None:
    h = GraphHarness()
    await h.submit("t1", b02_screen="injection")
    assert await _sent_text(h, "t1") == E0_REASON


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
async def test_real_b2_injection_suspected_sends_reason_sentence() -> None:
    """Model chặn tấn công chấm cao nhưng LLM không xác nhận → E1 `injection_suspected`; D-98: người dùng nhận câu nêu lý do riêng
    (chưa xác nhận an toàn được, đã chuyển kỹ thuật viên, gợi ý gửi từng việc) — không phạm vi, không lộ điểm hay lớp chặn."""
    h, _ = _env({JUDGE: [Reply(NOT_ATTACK)]}, ml=FakeMlService(classify_p=0.95))
    v = (await h.submit_as("t1", SESSION, text=NORMAL)).values
    assert (v["exit_code"], v["escalation_reason_detail"]) == ("E1", "injection_suspected")
    text = await _sent_text(h, "t1")
    assert text == E1_SUSPECTED
    assert text not in (TEMPLATES.of("E1").user_message, TEMPLATES.of("E0").user_message)
    assert not _says_scope(text)
    assert v["conversation"][-1]["text"] == text
