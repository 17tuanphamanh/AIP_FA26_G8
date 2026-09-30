"""Giới hạn phục hồi lượt dở dang (2b-Q6, Q-B; migration 0005 `turns.recover_attempts`).

Worker tăng `recover_attempts` TRƯỚC khi chạy lại. Tối đa `max_recover_attempts` = 3 lần worker chạy
lại (cộng lượt gốc = 4 lần chạy node); lần quét kế tiếp ngừng thử:
- kẹt ở B20 → audit `finalize_failed_permanent` (1 dòng) + đóng lượt;
- kẹt ở node khác → E9 `recover_exhausted` qua B20 — TRỪ KHI ticket đã có `transaction_log` `begun` (theo ticket, mọi lượt — chốt
  FAIL mục 7 d, soát DỪNG 3b 3h): E7 `execution_interrupted` + câu "có thể đã gửi lệnh ghi…", không mẫu E9 "xử lý thủ công".
Không dựa vào span lỗi: process bị giết (OOM/SIGKILL) không kịp ghi span.
"""

from datetime import timedelta

import pytest
from app.domain.states import S_ESCALATED
from app.graph.runner import FINALIZE_FAILED, RECOVER_EXHAUSTED
from app.graph.worker_jobs import WorkerJobs
from app.settings import get_escalation_templates
from tests.fakes.graph import Crash, GraphHarness

# Chép chữ (không import hằng của code): hằng đổi thì test phải đỏ
MAY_HAVE_WRITTEN = "có thể đã gửi lệnh ghi — L2 kiểm trên hệ thống đích trước khi làm tay"


def jobs(h: GraphHarness) -> WorkerJobs:
    return WorkerJobs(h.runner, h.deadlines, h.turns)


def _turn(h: GraphHarness, ticket: str) -> dict[str, object]:
    [row] = [{"turn_id": t, **r} for t, r in h.turns.rows.items() if r["ticket_id"] == ticket]
    return row


async def _scan(h: GraphHarness) -> int:
    h.clock.advance(timedelta(minutes=3))  # lượt mở quá 2 phút → "dở dang"
    return await jobs(h).scan_stale_turns()


@pytest.mark.asyncio
async def test_permanent_bug_in_b20_stops_after_three_recovers() -> None:
    h = GraphHarness()
    h.tickets.fail = RuntimeError("bug cố định ở B20")
    with pytest.raises(RuntimeError):
        await h.submit("t1", b12_assess="deny")
    for _ in range(3):
        assert await _scan(h) == 0  # recover lỗi — worker log, không sập
    assert h.tickets.finalize_calls["t1"] == 4  # lượt gốc + 3 lần worker
    assert h.audit.of("t1", FINALIZE_FAILED) == []

    assert await _scan(h) == 1  # lần thứ 4: ngừng thử
    assert h.tickets.finalize_calls["t1"] == 4  # không chạy B20 nữa
    [row] = h.audit.of("t1", FINALIZE_FAILED)
    assert row["step"] == "B20" and row["detail"]["recover_attempts"] == 3
    assert row["detail"]["node"] == "b20_audit" and row["exit_code"] == "E5"
    turn = _turn(h, "t1")
    assert turn["ended_at"] is not None and turn["recover_attempts"] == 4
    assert [r["step"] for r in h.audit.of("t1", "unhandled_exception")] == ["b20_audit"]  # theo lượt

    assert await _scan(h) == 0  # lượt đã đóng: không đụng tới nữa
    assert len(h.audit.of("t1", FINALIZE_FAILED)) == 1 and h.tickets.finalize_calls["t1"] == 4


@pytest.mark.asyncio
async def test_process_killed_in_b20_without_error_span_still_stops() -> None:
    """Q-B: process chết (không kịp ghi span lỗi) — bộ đếm tăng TRƯỚC khi chạy nên vẫn dừng."""
    h = GraphHarness()
    h.tickets.fail = Crash("SIGKILL giữa B20")
    with pytest.raises(Crash):
        await h.submit("t1", b12_assess="deny")
    for _ in range(3):
        h.spans.spans.clear()  # process bị giết: không có span nào sống sót
        with pytest.raises(Crash):
            await _scan(h)
    h.spans.spans.clear()
    assert await _scan(h) == 1
    assert len(h.audit.of("t1", FINALIZE_FAILED)) == 1
    assert h.tickets.finalize_calls["t1"] == 4 and _turn(h, "t1")["ended_at"] is not None


@pytest.mark.asyncio
async def test_transient_b20_error_recovers_without_giving_up() -> None:
    h = GraphHarness()
    h.tickets.fail, h.tickets.fail_times = RuntimeError("DB chập chờn"), 2
    with pytest.raises(RuntimeError):
        await h.submit("t1", b12_assess="deny")
    assert await _scan(h) == 0  # lần 2 vẫn lỗi
    assert await _scan(h) == 1  # lần 3 xong
    final = h.tickets.final("t1")
    assert final is not None and final.exit_code == "E5"
    assert len(h.escalations.of("t1")) == 1
    assert h.audit.of("t1", FINALIZE_FAILED) == []
    assert _turn(h, "t1")["recover_attempts"] == 2


@pytest.mark.asyncio
async def test_stuck_at_other_node_goes_e9_via_b20() -> None:
    """Process chết mãi ở B15 (sau khi tạo phiếu) → sau 3 lần: E9 `recover_exhausted`, qua B20."""
    h = GraphHarness()

    def die(_: object) -> None:
        raise Crash("OOM ở B15")

    h.scenario.on("t1", "after_approval_create", die)
    with pytest.raises(Crash):
        await h.submit("t1")
    for _ in range(3):
        with pytest.raises(Crash):
            await _scan(h)
    assert await _scan(h) == 1
    snap = await h.runner.snapshot("t1")
    assert (snap.values["status"], snap.values["exit_code"], snap.next) == (S_ESCALATED, "E9", ())
    assert snap.values["escalation_reason_detail"] == RECOVER_EXHAUSTED
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["reason_detail"]) == ("E9", RECOVER_EXHAUSTED)
    [row] = h.audit.of("t1", RECOVER_EXHAUSTED)
    assert row["step"] == "runner" and row["detail"]["node"] == "b15_prepare_approval"
    assert h.approvals.count("t1") == 1  # effects.once: 4 lần chạy B15 vẫn 1 phiếu
    assert _turn(h, "t1")["ended_at"] is not None
    assert h.tickets.final("t1") is not None


async def _exhaust_at_b15(h: GraphHarness) -> None:
    def die(_: object) -> None:
        raise Crash("OOM ở B15")

    h.scenario.on("t1", "after_approval_create", die)
    with pytest.raises(Crash):
        await h.submit("t1")
    for _ in range(3):
        with pytest.raises(Crash):
            await _scan(h)
    assert await _scan(h) == 1


@pytest.mark.asyncio
async def test_fail7_recover_exhausted_with_begun_of_earlier_turn_is_e7_warning() -> None:
    """(d)+(e): `begun` nằm ở LƯỢT TRƯỚC (T0), lượt đang kẹt là lượt sau → xét theo ticket → E7 + câu cảnh báo; handoff không có
    mẫu E9 "xử lý thủ công"."""
    h = GraphHarness()
    await h.txlog.begin("t1", "T0", "renew_vpn_cert")
    await _exhaust_at_b15(h)
    snap = await h.runner.snapshot("t1")
    assert (snap.values["exit_code"], snap.values["escalation_reason_detail"]) == ("E7", "execution_interrupted")
    assert MAY_HAVE_WRITTEN in snap.values["escalation_note"]
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["reason_detail"]) == ("E7", "execution_interrupted")
    assert MAY_HAVE_WRITTEN in esc["handoff_note"]["why_escalated"]
    assert get_escalation_templates().of("E9").next_for_l2 not in str(esc["handoff_note"])
    [row] = h.audit.of("t1", RECOVER_EXHAUSTED)
    assert row["detail"]["begun"] is True and row["detail"]["node"] == "b15_prepare_approval"


@pytest.mark.asyncio
async def test_fail7_recover_exhausted_begun_of_other_ticket_stays_e9() -> None:
    h = GraphHarness()
    await h.txlog.begin("t0", "T0", "renew_vpn_cert")  # ticket KHÁC
    await _exhaust_at_b15(h)
    [esc] = h.escalations.of("t1")
    assert (esc["exit_code"], esc["reason_detail"]) == ("E9", RECOVER_EXHAUSTED)
