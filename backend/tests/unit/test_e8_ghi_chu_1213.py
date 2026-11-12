"""U2 (CLI-5, soát 12/11 agent 18 V3): "Chưa ổn" + ghi chú trên ticket ĐÃ THỰC THI → E8 như cũ, nhưng ghi chú (bản ĐÃ CHE) không còn bị
vứt: vào `conversation` (tin của người dùng) và ghi chú bàn giao L2 (phần "lý do chuyển": "Người dùng báo: …"). Audit chỉ ghi số ký tự
(`note_chars`), không chữ người dùng — như vòng hỏi tiếp D-78. Ghi chú rỗng → như cũ (không dòng nào thêm).
"""

import json
from typing import Any, cast

import pytest
from app.domain.states import S_CONFIRMING, S_ESCALATED
from app.graph.late_event import deliver_event
from tests.fakes.graph import GraphHarness

pytestmark = pytest.mark.asyncio

NOTE = "vẫn báo lỗi 809, em đang ở khách sạn"


async def _unresolved(note: str | None) -> tuple[GraphHarness, dict[str, Any]]:
    h = GraphHarness()
    r = await h.submit("t1", b12_assess="auto")
    assert r.status == S_CONFIRMING
    v = cast(dict[str, Any], (await deliver_event(h.runner, "t1", S_CONFIRMING, {"kind": "unresolved", "note": note})).values)
    assert (v["status"], v["exit_code"]) == (S_ESCALATED, "E8")
    return h, v


def _handoff(h: GraphHarness) -> dict[str, Any]:
    [esc] = h.escalations.of("t1")
    note = esc["handoff_note"]
    return note if isinstance(note, dict) else json.loads(note)


async def test_ghi_chu_vao_hoi_thoai_va_ban_giao() -> None:
    h, v = await _unresolved(NOTE)
    assert {"role": "user", "text": NOTE} in v["conversation"]
    assert f"Người dùng báo: {NOTE}" in _handoff(h)["why_escalated"]
    [e8] = h.audit.of("t1", "user_reported_unresolved")
    assert e8["detail"]["note_chars"] == len(NOTE)
    assert NOTE not in json.dumps(h.audit.rows, ensure_ascii=False, default=str)  # audit không chứa chữ người dùng


async def test_ghi_chu_co_bi_mat_chi_ban_da_che_di_tiep() -> None:
    secret = "Matkhau@2026"
    h, v = await _unresolved(f"vẫn không vào được, mật khẩu {secret}")
    dumped = json.dumps([v["conversation"], _handoff(h), h.audit.rows], ensure_ascii=False, default=str)
    assert secret not in dumped
    assert "Người dùng báo:" in _handoff(h)["why_escalated"]


@pytest.mark.parametrize("note", [None, "", "   "])
async def test_ghi_chu_rong_nhu_cu(note: str | None) -> None:
    h, v = await _unresolved(note)
    assert not any(m.get("role") == "user" and not m.get("text", "").strip() for m in v["conversation"])
    assert "Người dùng báo:" not in _handoff(h)["why_escalated"]
    [e8] = h.audit.of("t1", "user_reported_unresolved")
    assert "note_chars" not in e8["detail"]
