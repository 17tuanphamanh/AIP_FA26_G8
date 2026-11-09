"""SSE tiến trình ticket (`GET /api/tickets/{id}/events`): quyền, danh sách trắng, Last-Event-ID, đóng stream, token chỉ từ tin đã
lưu, cờ ENABLE_SSE, ticket cha gộp con. Nguồn sự kiện giả = `MemFeed` đọc `MemoryAudit` của harness (log_id = số thứ tự dòng).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import Any

import pytest
from app.api import events
from app.api.events import FeedRow, chunk_text, message_kind, parse_last_event_id
from app.settings import Settings
from tests.fakes.desk import SECRET, DeskEnv, desk_env
from tests.fakes.graph import GraphHarness

CANARY = "CANARY-" + "91c4e7"  # ghép lúc chạy (gitleaks)
FAKE_EVENT_HEADERS = {"Accept": "text/event-stream"}


class MemFeed:
    """`AuditFeed` trên `MemoryAudit` của harness: `log_id` = vị trí dòng (từ 1); con = ticket có `parent_ticket_id` == gốc."""

    def __init__(self, h: GraphHarness) -> None:
        self._h = h

    async def rows_after(self, root_id: str, after: int, limit: int) -> list[FeedRow]:
        out: list[FeedRow] = []
        rows = self._h.audit.rows
        for log_id, r in enumerate(rows, start=1):
            tid = r["ticket_id"]
            child_of = self._h.tickets.rows.get(tid, {}).get("parent_ticket_id")
            if log_id <= after or (tid != root_id and child_of != root_id):
                continue
            ordinal = total = None
            if tid == root_id and message_kind(r["step"], r["event"], r.get("exit_code")) is not None:
                same = [
                    i for i, x in enumerate(rows, start=1)
                    if (x["ticket_id"], x["step"], x["event"]) == (tid, r["step"], r["event"])
                    and (r["step"] != "B20" or x.get("exit_code"))
                ]  # fmt: skip
                ordinal, total = same.index(log_id) + 1, len(same)
            detail = r.get("detail") or {}
            action = next((x["intended_action"] for x in reversed(rows[:log_id]) if x["ticket_id"] == tid and x.get("intended_action")), None)
            out.append(FeedRow(
                log_id=log_id, ticket_id=tid, step=r["step"], event=r["event"], to_status=r.get("to_status"),
                created_at=r["created_at"], intent=r.get("intent"), matched_rule_id=r.get("matched_rule_id"),
                exit_code=r.get("exit_code"), tools_called=tuple(detail.get("tools_called") or ()),
                tool_errors=tuple(str(e).split(":", 1)[0] for e in detail.get("tool_errors") or ()),
                success=detail.get("success"), action_type=(action or {}).get("type"), ordinal=ordinal, total=total,
            ))  # fmt: skip
            if len(out) >= limit:
                break
        return out


@asynccontextmanager
async def sse_env(monkeypatch: pytest.MonkeyPatch, **over: Any) -> AsyncIterator[DeskEnv]:
    monkeypatch.setattr(events, "TOKEN_INTERVAL_S", 0.0)
    over = {"enable_sse": True, "sse_poll_ms": 50, "sse_heartbeat_s": 15.0, **over}
    async with desk_env(**over) as env:
        env.app.state.events_feed = MemFeed(env.h)
        yield env


@dataclass(frozen=True)
class Frame:
    id: str | None
    event: str
    data: dict[str, Any]


def parse(body: str) -> tuple[list[Frame], int]:
    """(các khung sự kiện, số dòng comment)."""
    frames: list[Frame] = []
    comments = 0
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        if block.startswith(":"):
            comments += 1
            continue
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        frames.append(Frame(fields.get("id"), fields["event"], json.loads(fields["data"])))
    return frames, comments


async def get_stream(env: DeskEnv, ticket: str, headers: Mapping[str, str], last_id: str | None = None) -> tuple[Any, list[Frame]]:
    extra = {"Last-Event-ID": last_id} if last_id is not None else {}
    r = await asyncio.wait_for(env.client.get(f"/api/tickets/{ticket}/events", headers={**headers, **extra}), 10)
    return r, parse(r.text)[0] if r.status_code == 200 else []


async def save_message(env: DeskEnv, ticket: str, kind: str, text: str, ref: str = "m1") -> None:
    cfg = env.h.runner.config(ticket)
    msg = {"role": "assistant", "kind": kind, "text": text, "ref": ref, "needs": "confirm"}
    await env.h.runner.graph.aupdate_state(cfg, {"conversation": [msg]})


async def info_ticket(env: DeskEnv, headers: Mapping[str, str], text: str = "VPN không vào được") -> str:
    """Ticket dừng ở `confirm_wait` sau B10 `deflected_info_only` (đường chỉ hướng dẫn)."""
    env.h.scenario.plan_all(b10_route="info")
    ticket = await env.create(dict(headers), text=text)
    await env.drain()
    return ticket


# ---- Cờ ENABLE_SSE + quyền ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_by_default_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    assert Settings(_env_file=None).enable_sse is False  # type: ignore[call-arg]
    async with sse_env(monkeypatch, enable_sse=False) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        r, _ = await get_stream(env, ticket, an)
        assert r.status_code == 404
        r = await env.client.get(f"/api/tickets/{ticket}/events")  # cờ tắt: route như không tồn tại, cả khi chưa đăng nhập
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_settings_defaults() -> None:
    s = Settings(_env_file=None)  # type: ignore[call-arg]
    assert (s.enable_sse, s.sse_poll_ms, s.sse_heartbeat_s) == (False, 300, 15.0)


@pytest.mark.asyncio
async def test_owner_reads_other_employee_cannot(monkeypatch: pytest.MonkeyPatch) -> None:
    async with sse_env(monkeypatch) as env:
        an, binh, l1 = await env.token("an.nv"), await env.token("binh.tt"), await env.token("ha.lt")
        ticket = await env.create(an)
        await env.drain()
        r, frames = await get_stream(env, ticket, an)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        assert frames and frames[-1].event == "waiting"
        denied = env.denied()
        r, _ = await get_stream(env, ticket, binh)  # người khác: cùng 404 như ticket không tồn tại
        assert r.status_code == 404 and r.text == (await env.client.get("/api/tickets/nope/events", headers=binh)).text
        assert env.denied() == denied + 1
        r, _ = await get_stream(env, ticket, l1)  # có `ticket:read:any`
        assert r.status_code == 200
        assert (await env.client.get(f"/api/tickets/{ticket}/events")).status_code == 401
        assert (await env.client.get("/api/tickets/nope/events", headers=an)).status_code == 404


# ---- Nội dung: bảng trắng, thought, nhãn --------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_flow_for_pending_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        _, frames = await get_stream(env, ticket, an)
        labels = [(f.event, f.data["label"]) for f in frames]
        assert ("status", "Đang kiểm tra an toàn") in labels
        assert ("status", "Đã hiểu yêu cầu: VPN") in labels
        assert ("status", "Đang tra cứu hướng dẫn") in labels
        assert ("thought", "Hướng dẫn phù hợp được tìm thấy trong tài liệu nội bộ") in labels
        assert ("status", "Đang chờ IT duyệt") in labels
        assert frames[-1].event == "waiting" and frames[-1].data["data"] == {"waiting_for": "approval"}
        assert frames[-1].id is None
        for f in frames:  # hình dạng {type, step, label, at, data?}
            assert {"type", "step", "label", "at"} <= f.data.keys() and f.data["type"] == f.event
        keys = [(int(i.split(".")[0]), int(i.split(".")[1]) if "." in i else 10**9) for i in (f.id for f in frames if f.id)]
        assert keys == sorted(set(keys))  # id tăng ngặt: `N.k` (k tăng dần) rồi `N` ở sự kiện cuối của dòng


@pytest.mark.asyncio
async def test_unlisted_rows_and_internal_fields_never_appear(monkeypatch: pytest.MonkeyPatch) -> None:
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an, text=f"VPN lỗi {CANARY}")
        await env.drain()
        rows = env.h.audit.rows
        base = {"ticket_id": ticket, "created_at": rows[0]["created_at"], "from_status": "S_NEW", "to_status": "S_ESCALATED"}
        rows += [  # dòng ngoài bảng + mọi cột/`detail` mang canary
            {**base, "step": "B99", "event": f"unlisted_{CANARY}", "detail": {"note": CANARY}},
            {**base, "step": "B6", "event": "diagnosed", "reason": CANARY, "query": CANARY, "note": CANARY,
             "matched_rule_id": f"R-{CANARY}", "intent": "vpn",
             "detail": {"tools_called": ["check_vpn_cert_expiry", f"tool_{CANARY}"], "reason": CANARY,
                        "args": {"user_id": CANARY}, "tool_errors": [f"check_vpn_cert_expiry: {CANARY}"]}},
            {**base, "step": "B13/B14", "event": "risk_decided", "to_status": "S_ASSESSING", "matched_rule_id": "R18",
             "calibrated_prob": 0.77, "raw_prob": 0.61, "reason": CANARY, "detail": {"thresholds": [0.3, 0.9]}},
        ]  # fmt: skip
        _, frames = await get_stream(env, ticket, an)
        raw = json.dumps([f.data for f in frames], ensure_ascii=False)
        for forbidden in (CANARY, "R18", "R-", "0.77", "0.61", "0.3", "thresholds", "user_id", "nv001", "unlisted"):
            assert forbidden not in raw, forbidden
        tools = [f for f in frames if f.event == "tool_call"]
        assert [(t.data["label"], t.data["data"]) for t in tools] == [("Kiểm tra chứng chỉ VPN", {"ok": False})]
        assert any(f.event == "thought" and f.data["label"] == "Yêu cầu ngoài giờ hành chính nên cần IT duyệt" for f in frames)


@pytest.mark.asyncio
async def test_tool_call_has_no_params_and_b17_uses_action_label(monkeypatch: pytest.MonkeyPatch) -> None:
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        rows = env.h.audit.rows
        base = {"ticket_id": ticket, "created_at": rows[0]["created_at"], "from_status": "S_EXECUTING"}
        rows += [
            {**base, "step": "B11", "event": "action_built", "to_status": "S_ASSESSING",
             "intended_action": {"type": "renew_vpn_cert", "params": {"device_id": f"PC-{CANARY}"}}, "detail": {}},
            {**base, "step": "B18", "event": "executed_ok", "to_status": "S_CONFIRMING",
             "detail": {"success": True, "steps_done": ["renew"], "write_calls": 1}},
        ]  # fmt: skip
        _, frames = await get_stream(env, ticket, an)
        [call] = [f for f in frames if f.event == "tool_call" and f.data["step"] == "execute"]
        assert call.data == {"type": "tool_call", "step": "execute", "label": "Gia hạn chứng chỉ VPN", "at": call.data["at"], "data": {"ok": True}}
        assert CANARY not in json.dumps([f.data for f in frames])


@pytest.mark.parametrize("key", sorted(events.TABLE, key=str))
def test_every_table_entry_builds_clean_events(key: tuple[str, str, str | None]) -> None:
    step, event, to_status = key
    row = FeedRow(log_id=1, ticket_id="t", step=step, event=event, to_status=to_status, created_at=_epoch(), intent="vpn",
                  matched_rule_id="R18")  # fmt: skip
    out = events.status_events(row, "2026-01-01T00:00:00+00:00", None)
    assert out and all(e["type"] in ("status", "thought") for e in out)
    for e in out:
        assert e["label"] and "{" not in e["label"] and "S_" not in e["label"]
        assert "R18" not in json.dumps(e, ensure_ascii=False)


def _epoch() -> Any:
    from tests.fakes.auth import EPOCH

    return EPOCH


def test_intent_label_closed_set_and_unknown_intent_is_neutral() -> None:
    row = FeedRow(1, "t", "B3", "intent_classified", "S_DIAGNOSING", _epoch(), intent=f"x_{CANARY}")
    labels = [e["label"] for e in events.status_events(row, "t", None)]
    assert "Đã hiểu yêu cầu" in labels and all(CANARY not in label for label in labels)


# ---- Token / tin đã lưu -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "body", ["một hai ba bốn năm sáu bảy", "Chào bạn,\n\n1. Mở ứng dụng\n2. Bấm **Kết nối**", "  lead và trail  ", "a", "hai từ", "x " * 9]
)
def test_chunk_text_roundtrips_and_sizes(body: str) -> None:
    parts = chunk_text(body)
    assert "".join(parts) == body
    words = [len(p.split()) for p in parts]
    assert all(2 <= w <= 4 for w in words) or len(words) == 1


def test_chunk_text_empty() -> None:
    assert chunk_text("") == [] and chunk_text("   ") == []


@pytest.mark.asyncio
async def test_tokens_stream_saved_answer_and_end_with_message_end(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = "Bạn mở ứng dụng VPN rồi bấm kết nối lại nhé.\nNếu vẫn lỗi hãy báo lại."
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await info_ticket(env, an, text=f"VPN lỗi {CANARY}")
        await save_message(env, ticket, "answer", answer)
        before = len(env.h.audit.rows)
        # kết nối nối lại từ trước dòng B10 → dòng đó được phát cả token
        last_before_b10 = str(next(i for i, r in enumerate(env.h.audit.rows, 1) if r["event"] == "deflected_info_only") - 1)
        _, frames = await get_stream(env, ticket, an, last_id=last_before_b10)
        assert len(env.h.audit.rows) == before
        tokens = [f for f in frames if f.event == "token"]
        assert "".join(f.data["data"]["text"] for f in tokens) == answer
        assert {f.data["data"]["message_id"] for f in tokens} == {"answer:1"}
        ends = [f for f in frames if f.event == "message_end"]
        assert len(ends) == 1 and ends[0].data["data"] == {"message_id": "answer:1"}
        assert frames.index(ends[0]) > max(frames.index(t) for t in tokens)
        assert CANARY not in json.dumps([f.data for f in frames])
        assert frames[-1].event == "waiting" and frames[-1].data["data"] == {"waiting_for": "confirm"}


@pytest.mark.asyncio
async def test_no_tokens_before_message_is_saved(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = "Hướng dẫn đã lưu sau khi dòng audit được ghi."
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await info_ticket(env, an)
        first = str(next(i for i, r in enumerate(env.h.audit.rows, 1) if r["event"] == "deflected_info_only") - 1)

        async def late_save() -> None:
            await asyncio.sleep(0.3)
            await save_message(env, ticket, "answer", answer)

        saver = asyncio.create_task(late_save())
        _, frames = await get_stream(env, ticket, an, last_id=first)
        await saver
        # tin chưa lưu thì stream CHỜ (không đóng ở `waiting`, không bịa token); lưu xong mới phát đủ
        assert "".join(f.data["data"]["text"] for f in frames if f.event == "token") == answer
        assert frames[-1].event == "waiting"


@pytest.mark.asyncio
async def test_stalled_message_is_skipped_after_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "STALL_S", 0.2)
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await info_ticket(env, an)
        first = str(next(i for i, r in enumerate(env.h.audit.rows, 1) if r["event"] == "deflected_info_only") - 1)
        _, frames = await get_stream(env, ticket, an, last_id=first)  # không bao giờ lưu tin
        assert not [f for f in frames if f.event in ("token", "message_end")]
        assert frames[-1].event == "waiting"


@pytest.mark.asyncio
async def test_fresh_connection_does_not_retokenize_existing_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await info_ticket(env, an)
        await save_message(env, ticket, "answer", "Tin này đã hiện qua GET rồi.")
        _, frames = await get_stream(env, ticket, an)  # không Last-Event-ID
        assert not [f for f in frames if f.event in ("token", "message_end")]
        assert any(f.event == "status" for f in frames) and frames[-1].event == "waiting"


@pytest.mark.asyncio
async def test_user_messages_are_never_streamed(monkeypatch: pytest.MonkeyPatch) -> None:
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await info_ticket(env, an)
        cfg = env.h.runner.config(ticket)
        await env.h.runner.graph.aupdate_state(cfg, {"conversation": [{"role": "user", "text": f"tôi gõ {CANARY}"}]})
        await save_message(env, ticket, "answer", "Trả lời của hệ thống.")
        first = str(next(i for i, r in enumerate(env.h.audit.rows, 1) if r["event"] == "deflected_info_only") - 1)
        _, frames = await get_stream(env, ticket, an, last_id=first)
        assert CANARY not in json.dumps([f.data for f in frames])
        assert "".join(f.data["data"]["text"] for f in frames if f.event == "token") == "Trả lời của hệ thống."


# ---- Last-Event-ID ------------------------------------------------------------------------------------------------------


def test_parse_last_event_id() -> None:
    assert parse_last_event_id(None) == (0, 0)
    assert parse_last_event_id("7") == (7, 0)
    assert parse_last_event_id("7.3") == (6, 3)
    for bad in ("", "abc", "7.", "-1", "7.3.1", "7; DROP"):
        assert parse_last_event_id(bad) == (0, 0)


@pytest.mark.asyncio
async def test_resume_at_every_event_yields_exact_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    answer = "Bạn mở ứng dụng VPN rồi bấm kết nối lại nhé. Nếu vẫn lỗi hãy báo lại cho IT để được hỗ trợ thêm."
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await info_ticket(env, an)
        await save_message(env, ticket, "answer", answer)
        zero = str(next(i for i, r in enumerate(env.h.audit.rows, 1) if r["event"] == "deflected_info_only") - 1)
        _, full = await get_stream(env, ticket, an, last_id=zero)
        assert sum(f.event == "token" for f in full) >= 4
        with_ids = [i for i, f in enumerate(full) if f.id is not None]
        assert len(with_ids) == len(full) - 1  # mọi sự kiện có id trừ `waiting`
        for i in with_ids:
            _, rest = await get_stream(env, ticket, an, last_id=full[i].id)
            assert [(f.id, f.event, f.data) for f in rest] == [(f.id, f.event, f.data) for f in full[i + 1 :]], full[i].id
        _, all_from_start = await get_stream(env, ticket, an, last_id="0")
        assert [f.data for f in all_from_start if f.event != "waiting"][: len(full)] == [f.data for f in all_from_start][: len(full)]


@pytest.mark.asyncio
async def test_resume_from_last_row_returns_only_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        ticket = await env.create(an)
        await env.drain()
        _, frames = await get_stream(env, ticket, an, last_id=str(len(env.h.audit.rows)))
        assert [f.event for f in frames] == ["waiting"]


# ---- Đóng stream / heartbeat / giới hạn ---------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_closes_with_done_when_final_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "MAX_STREAM_S", 3.0)
    monkeypatch.setattr(events, "STALL_S", 0.1)  # node giả không lưu tin `result` của B18
    async with sse_env(monkeypatch) as env:
        an, l1 = await env.token("an.nv"), await env.token("ha.lt")
        ticket = await env.create(an)
        await env.drain()
        r = await env.client.post(f"/api/approvals/{env.approval_of(ticket)}/decision", json={"decision": "approved"}, headers=l1)
        assert r.status_code == 202
        await env.drain()
        r = await env.client.post(f"/api/tickets/{ticket}/confirm", json={"confirmed": True}, headers=an)
        assert r.status_code == 202
        await env.drain()
        assert env.h.tickets.final(ticket) is not None
        _, frames = await get_stream(env, ticket, an)
        assert frames[-1].event == "done" and frames[-1].data["label"] == "Hoàn tất"
        assert [f.event for f in frames].count("done") == 1


@pytest.mark.asyncio
async def test_heartbeat_and_time_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "MAX_STREAM_S", 0.6)
    async with sse_env(monkeypatch, sse_heartbeat_s=0.1) as env:
        an = await env.token("an.nv")
        env.h.tickets.register("tkt-idle", env.clock.now(), requester_id="nv001")  # chưa chạy graph: không chờ, không xong
        r = await asyncio.wait_for(env.client.get("/api/tickets/tkt-idle/events", headers=an), 5)
        frames, comments = parse(r.text)
        assert r.status_code == 200 and frames == [] and comments >= 2  # quá 10 phút (ở đây 0,6 s) → đóng, không `done`


# ---- Ticket cha ---------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_merges_child_events_with_child_id_and_no_child_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    async with sse_env(monkeypatch) as env:
        an = await env.token("an.nv")
        parent = await env.create(an)
        await env.drain()
        child = f"{parent}-1"
        env.h.tickets.register(child, env.clock.now(), requester_id="nv001", parent_ticket_id=parent)
        rows = env.h.audit.rows
        base = {"created_at": rows[0]["created_at"], "from_status": "S_CLASSIFYING"}
        rows += [
            {**base, "ticket_id": child, "step": "B6", "event": "diagnosed", "to_status": "S_RETRIEVING",
             "detail": {"tools_called": ["check_vpn_cert_expiry"]}},
            {**base, "ticket_id": child, "step": "B10", "event": "deflected_info_only", "to_status": "S_CONFIRMING", "detail": {}},
            {**base, "ticket_id": "tkt-other", "step": "B6", "event": "diagnosed", "to_status": "S_RETRIEVING", "detail": {}},
        ]  # fmt: skip
        _, frames = await get_stream(env, parent, an)
        mine = [f for f in frames if f.data.get("child_id") == child]
        assert {f.event for f in mine} >= {"status", "tool_call"} and all(f.data["child_id"] == child for f in mine)
        assert not [f for f in frames if f.event in ("token", "message_end") and f.data.get("child_id")]
        assert "tkt-other" not in json.dumps([f.data for f in frames])
        assert not any("child_id" in f.data for f in frames if f.id is not None and int(f.id.split(".")[0]) <= 6)
        ids = [int(f.id.split(".")[0]) for f in frames if f.id]
        assert ids == sorted(ids)  # gộp theo log_id tăng dần


@pytest.mark.asyncio
async def test_child_rows_never_tokenize_even_when_parent_has_same_kind_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ticket con không nhắn người dùng (D-31): dòng "có tin" của con không bao giờ được ghép với tin trong hội thoại của cha."""
    monkeypatch.setattr(events, "STALL_S", 0.1)

    class ChildOrdinalFeed(MemFeed):
        async def rows_after(self, root_id: str, after: int, limit: int) -> list[FeedRow]:
            rows = await super().rows_after(root_id, after, limit)
            return [replace(r, ordinal=1, total=1) if r.ticket_id != root_id else r for r in rows]

    async with sse_env(monkeypatch) as env:
        env.app.state.events_feed = ChildOrdinalFeed(env.h)
        an = await env.token("an.nv")
        parent = await env.create(an)
        await env.drain()
        await save_message(env, parent, "answer", "Tin của ticket cha, không phải của con.")
        child = f"{parent}-1"
        env.h.tickets.register(child, env.clock.now(), requester_id="nv001", parent_ticket_id=parent)
        env.h.audit.rows.append({
            "ticket_id": child, "created_at": env.h.audit.rows[0]["created_at"], "from_status": "S_RETRIEVING",
            "step": "B10", "event": "deflected_info_only", "to_status": "S_CONFIRMING", "detail": {},
        })  # fmt: skip
        _, frames = await get_stream(env, parent, an, last_id="0")  # có Last-Event-ID: tin đã lưu vẫn được tokenise nếu dòng là của cha
        assert [f for f in frames if f.event in ("token", "message_end")] == []
        assert any(f.data.get("child_id") == child for f in frames)


# ---- Bảo vệ hằng số -----------------------------------------------------------------------------------------------------


def test_secret_never_in_labels() -> None:
    blob = json.dumps([TABLE_TEXT for TABLE_TEXT in _all_text()], ensure_ascii=False)
    assert SECRET not in blob


def _all_text() -> list[str]:
    out = list(events.TOOL_LABEL.values()) + list(events.ACTION_LABEL.values()) + list(events.DONE_LABEL.values())
    for entry in events.TABLE.values():
        out += [s.label for s in entry.statuses] + ([entry.thought] if entry.thought else [])
    return out


# ---- Q1 (D-56): câu hỏi phân loại của B3 không làm lệch câu hỏi B11 ------------------------------------------------------------


def test_q1_triage_question_and_b11_question_picked_by_source() -> None:
    from datetime import UTC, datetime

    from app.domain.messages import question_msg, triage_msg, user_msg

    convo = [triage_msg("Câu hỏi phân loại", "m0"), user_msg("VPN báo lỗi"), question_msg("Câu B11 thứ nhất", "m1")]
    at = datetime(2026, 11, 9, tzinfo=UTC)
    b3 = FeedRow(log_id=1, ticket_id="t1", step="B3", event="triage_asked", to_status="S_CLARIFYING", created_at=at, ordinal=1, total=1)
    b11 = FeedRow(log_id=2, ticket_id="t1", step="B11", event="asked", to_status="S_CLARIFYING", created_at=at, ordinal=1, total=1)
    assert message_kind("B3", "triage_asked", None) == "question"
    picked_b3, picked_b11 = events.pick_message(convo, b3), events.pick_message(convo, b11)
    assert picked_b3 is not None and picked_b3["text"] == "Câu hỏi phân loại"
    assert picked_b11 is not None and picked_b11["text"] == "Câu B11 thứ nhất"
