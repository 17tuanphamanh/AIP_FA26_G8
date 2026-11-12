"""D-92 bổ sung (soát 12/11 chiều): `/reply` của ticket CHA cũng so mẫu injection trên bản GỐC, như `/messages`, `/confirm`.

Lỗ trước sửa: `/reply` che TỪNG `answer`/`note` rồi giao xuống con; con chỉ so mẫu trên bản đã che → "mk: Ignore previous …" lọt
(luật mật khẩu nuốt "Ignore"). Nay API tính `screen_hits = reply_hits({cid: chữ gốc})` — CHỈ mã mẫu + nhóm của ý nào khớp —
`parent_reply_wait` gắn `screen_hit` vào sự kiện của đúng con đó; con dùng `screen_event` như cũ. Chữ gốc không đi xa hơn route.
"""

from typing import Any

import pytest
from app.domain.states import S_CONFIRMING, S_ESCALATED, S_RESOLVED
from app.graph.nodes.parent_reply_wait import child_event
from app.guard.privacy import RegexPrivacyGuard
from app.guard.screen import reply_hits
from app.settings import get_settings
from tests.unit.test_b02_ban_goc_1211 import MK
from tests.unit.test_t20b_api import api, tc35
from tests.unit.test_t20b_reply import reply, tc35_round1

pytestmark = pytest.mark.asyncio

GUARD = RegexPrivacyGuard.from_settings(get_settings())
HIT = {"id": "OVR-03", "group": "override"}


def masked(text: str) -> str:
    out = GUARD.redact_text(text).text
    assert "Ignore" not in out  # tiền đề của lỗ: bản che đã nuốt từ khoá
    return out


# ---- hàm thuần ------------------------------------------------------------------------------------------------------------------


async def test_reply_hits_chi_ma_mau_cua_y_khop() -> None:
    hits = reply_hits({"T1-1": MK, "T1-2": "30", "T1-3": None, "T1-4": ""})
    assert hits == {"T1-1": HIT}
    assert "Ignore" not in repr(hits)


async def test_child_event_gan_ma_mau_khi_co() -> None:
    assert child_event("answer", {"answer": "x"}, HIT) == {"kind": "user_reply", "text": "x", "screen_hit": HIT}
    assert child_event("confirm", {"confirmed": False, "note": "x"}, HIT)["screen_hit"] == HIT
    assert "screen_hit" not in child_event("answer", {"answer": "x"}, None)
    assert child_event("answer", None, HIT) == {"kind": "timeout"}  # timeout không mang gì


# ---- graph thật: cha giao mã mẫu xuống đúng con ---------------------------------------------------------------------------------


async def test_ghi_chu_chua_on_co_ma_mau_ban_goc_con_e0() -> None:
    f = await tc35_round1()
    ev = reply({"T1-1": {"confirmed": False, "note": masked(MK)}, "T1-2": {"answer": "30"}})
    await f.deliver("T1", S_CONFIRMING, {**ev, "screen_hits": {"T1-1": HIT}})
    c1, c2 = await f.values("T1-1"), await f.values("T1-2")
    assert (c1["status"], c1["exit_code"], c1["escalation_reason_detail"]) == (S_ESCALATED, "E0", "injection_in_reply")
    assert c2.get("exit_code") != "E0"  # ý kia không bị kéo theo
    [event] = f.h.security_events.of("T1-1")
    assert "Ignore" not in repr(event)


async def test_tra_loi_co_ma_mau_ban_goc_con_e0() -> None:
    f = await tc35_round1()
    ev = reply({"T1-1": {"confirmed": True}, "T1-2": {"answer": masked(MK)}})
    await f.deliver("T1", S_CONFIRMING, {**ev, "screen_hits": {"T1-2": HIT}})
    c1, c2 = await f.values("T1-1"), await f.values("T1-2")
    assert (c2["status"], c2["exit_code"], c2["escalation_reason_detail"]) == (S_ESCALATED, "E0", "injection_in_reply")
    assert (c1["status"], c1["close_reason"]) == (S_RESOLVED, "resolved_user_confirmed")


@pytest.mark.parametrize(
    "hits",
    [None, {}, {"T1-9": HIT}, {"T1-2": {"id": "bỏ qua quy tắc", "group": "override"}}, {"T1-2": "OVR-03"}, "OVR-03"],
)  # fmt: skip
async def test_ma_mau_sai_dang_hoac_sai_y_khong_tac_dung(hits: Any) -> None:
    f = await tc35_round1()
    ev = reply({"T1-1": {"confirmed": True}, "T1-2": {"answer": "30"}})
    await f.deliver("T1", S_CONFIRMING, {**ev, "screen_hits": hits})
    assert (await f.values("T1-2")).get("exit_code") != "E0"
    assert f.h.security_events.of("T1-2") == []


# ---- API: so trên bản gốc, chỉ mã mẫu đi tiếp -----------------------------------------------------------------------------------


async def test_api_reply_ghi_chu_mk_ra_e0_o_con() -> None:
    f = await tc35()
    async with api(f, guard=GUARD) as a:
        an = await a.token("an.nv")
        r = await a.reply(an, {"T1-1": {"confirmed": False, "note": MK}, "T1-2": {"answer": "30"}})
        assert r.status_code == 202, r.text
        await a.drain()
    c1 = await f.values("T1-1")
    assert (c1["exit_code"], c1["escalation_reason_detail"]) == ("E0", "injection_in_reply")
    for cid in ("T1", "T1-1", "T1-2"):
        assert "Ignore" not in repr(await f.values(cid))  # bản gốc không vào checkpoint


async def test_api_reply_cau_thuong_khong_bi_chan() -> None:
    f = await tc35()
    async with api(f, guard=GUARD) as a:
        an = await a.token("an.nv")
        r = await a.reply(an, {"T1-1": {"confirmed": False, "note": "mk: vẫn chưa vào được VPN"}, "T1-2": {"answer": "30"}})
        assert r.status_code == 202, r.text
        await a.drain()
    assert (await f.values("T1-1")).get("exit_code") != "E0"
    assert f.h.security_events.of("T1-1") == []
