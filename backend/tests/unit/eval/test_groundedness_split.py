"""G11 — tách ý bằng code (`app.eval.groundedness.split`)."""

import pytest
from app.domain.answer import SOURCES_HEADER, render_answer
from app.domain.ticket_state import ChunkRef
from app.eval.groundedness.split import split_claims


def test_numbered_steps_lead_in_and_sources_block_removed() -> None:
    text = f"Bạn thử các bước sau:\n1. Mở Cisco AnyConnect.\n2) Chọn Connect.\n\n{SOURCES_HEADER}\n- VPN › Cài đặt\n- Bước 9."
    assert split_claims(text) == ["Mở Cisco AnyConnect.", "Chọn Connect."]


def test_sources_block_is_not_claims_even_without_lead_in() -> None:
    assert split_claims(f"VPN dùng cổng 443.\n\n{SOURCES_HEADER}\n- Tài liệu VPN › Cổng") == ["VPN dùng cổng 443."]


def test_prose_split_into_sentences() -> None:
    assert split_claims("VPN dùng cổng 443. Bạn cần mạng công ty! Đúng không? Vâng.") == [
        "VPN dùng cổng 443.", "Bạn cần mạng công ty!", "Đúng không?", "Vâng.",
    ]  # fmt: skip


def test_no_split_on_abbreviation_version_or_error_code() -> None:
    assert split_claims("Dùng bản 1.2.3, vd. Cisco AnyConnect. Sau đó khởi động lại.") == [
        "Dùng bản 1.2.3, vd. Cisco AnyConnect.", "Sau đó khởi động lại.",
    ]  # fmt: skip
    assert split_claims("Lỗi 0x8004010F xảy ra khi mở Outlook.") == ["Lỗi 0x8004010F xảy ra khi mở Outlook."]
    assert split_claims("Gặp TS. Nguyễn Văn A ở tầng 3.") == ["Gặp TS. Nguyễn Văn A ở tầng 3."]


def test_lowercase_after_period_is_not_a_boundary() -> None:
    assert split_claims("Chọn mục v.v. rồi bấm tiếp.") == ["Chọn mục v.v. rồi bấm tiếp."]


@pytest.mark.parametrize("marker", ["-", "*", "•"])
def test_bullets_are_one_claim_each(marker: str) -> None:
    assert split_claims(f"{marker} Ý thứ nhất. Có hai câu.\n{marker} Ý thứ hai") == ["Ý thứ nhất. Có hai câu.", "Ý thứ hai"]


def test_steps_param_and_rendered_answer_give_same_claims() -> None:
    steps = ["Mở ứng dụng", "Chọn Connect"]
    cited = [ChunkRef.model_construct(title="VPN", heading_path="Kết nối")]
    rendered = render_answer("Bạn làm như sau.", steps, cited)  # type: ignore[arg-type]
    assert split_claims(rendered, steps) == ["Bạn làm như sau.", "Mở ứng dụng", "Chọn Connect"]  # bản render đã chứa steps
    assert split_claims("Bạn làm như sau.", steps) == ["Bạn làm như sau.", "Mở ứng dụng", "Chọn Connect"]
    # `answer` đã chứa các bước đánh số + `steps` → mỗi bước một lần
    assert split_claims("Bạn làm như sau.\n1. Mở ứng dụng\n2.  Chọn   Connect", steps) == [
        "Bạn làm như sau.", "Mở ứng dụng", "Chọn Connect",
    ]  # fmt: skip


def test_rendered_answer_round_trip_drops_sources() -> None:
    cited = [ChunkRef.model_construct(title="Tài liệu VPN", heading_path="Cổng")]
    rendered = render_answer("VPN dùng cổng 443.", ["Mở ứng dụng"], cited)  # type: ignore[arg-type]
    assert split_claims(rendered) == ["VPN dùng cổng 443.", "Mở ứng dụng"]


@pytest.mark.parametrize("text", ["", "   \n \n", f"{SOURCES_HEADER}\n- x", "Làm như sau:"])
def test_nothing_to_claim(text: str) -> None:
    assert split_claims(text) == []


def test_whitespace_normalised_and_one_char_dropped() -> None:
    assert split_claims("  Mở   ứng\tdụng  \n.\n") == ["Mở ứng dụng"]
