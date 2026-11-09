"""be-api8-cau-dau (nợ API #8 / Q-fe-18) — `GET /api/tickets/{id}` trả `request_text` = câu yêu cầu đầu ĐÃ CHE (`tickets.redacted_request`,
cắt 500 ký tự), để mở lại /chat/<id> thấy câu đầu. Không bao giờ bản thô. Ticket con trùng nguyên câu cha → None.

Ai đọc được route: chủ ticket (mọi vai) + vai có `ticket:read:any` (l1, l2, manager) — đều chỉ nhận bản đã che.
"""

import pytest
from app.api.tickets import REQUEST_TEXT_MAX, TicketView, request_text_of
from app.db.tickets import TicketRow
from app.guard.privacy import RegexPrivacyGuard
from app.settings import Settings
from tests.fakes.auth import EPOCH
from tests.fakes.desk import MASK, SECRET, desk_env

pytestmark = pytest.mark.asyncio


async def test_request_text_is_redacted_row_for_owner_and_readers() -> None:
    async with desk_env() as env:
        an, l1, l2 = await env.token("an.nv"), await env.token("ha.lt"), await env.token("long.nh")
        ticket = await env.create(an, text=f"VPN lỗi 809, mật khẩu của tôi là {SECRET}")
        await env.drain()
        stored = env.h.tickets.rows[ticket]["redacted_request"]
        assert SECRET not in stored and MASK in stored
        for who in (an, l1, l2):
            body = await env.ticket(ticket, who)
            assert body["request_text"] == stored and SECRET not in str(body)


async def test_request_text_never_leaks_pii_with_real_guard() -> None:
    real = RegexPrivacyGuard.from_settings(Settings(_env_file=None))  # type: ignore[call-arg]
    async with desk_env(guard=real) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an, text="Máy không vào được VPN, gọi mình số 0901234567 nhé")
        await env.drain()
        text = (await env.ticket(ticket, an))["request_text"]
        assert "0901234567" not in text and "<SĐT_1>" in text


async def test_request_text_cut_to_500() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        ticket = await env.create(an, text="VPN " + "a" * 900)
        await env.drain()
        assert len((await env.ticket(ticket, an))["request_text"]) == REQUEST_TEXT_MAX


def _row(text: str, parent: str | None = None) -> TicketRow:
    return TicketRow(ticket_id="c1", requester_id="nv001", session_id=None, redacted_request=text, parent_ticket_id=parent,
                     is_parent=False, final_state=None, exit_code=None, close_reason=None, created_at=EPOCH, closed_at=None)  # fmt: skip


def test_child_with_full_parent_sentence_gets_none_span_kept() -> None:
    """Ticket con (B5): `redacted_request` = span của ý; span không hợp lệ thì = nguyên câu cha → None (không lặp câu cha)."""
    whole = "đặt lại mật khẩu AD, tiện cài Zoom"
    assert request_text_of(_row(whole, parent="p1"), whole) is None
    assert request_text_of(_row(f"  {whole} ", parent="p1"), whole) is None
    assert request_text_of(_row("cài Zoom", parent="p1"), whole) == "cài Zoom"
    assert request_text_of(_row(whole), None) == whole  # ticket thường


async def test_child_ticket_via_route() -> None:
    async with desk_env() as env:
        an = await env.token("an.nv")
        parent, child = await env.create(an, text="đặt lại mật khẩu AD, tiện cài Zoom"), await env.create(an, text="cài Zoom")
        await env.drain()
        rows = env.h.tickets.rows
        rows[parent]["is_parent"] = True
        rows[child]["parent_ticket_id"] = parent
        assert (await env.ticket(child, an))["request_text"] == "cài Zoom"
        rows[child]["redacted_request"] = rows[parent]["redacted_request"]
        assert (await env.ticket(child, an))["request_text"] is None


def test_request_text_field_declared_once() -> None:
    assert "request_text" in TicketView.model_fields and TicketView.model_fields["request_text"].default is None
