"""T20b — phán từng ý ở B3 → B5 tách ticket con (phase5 5.2.2, 5.2.8 v1–v9; P2, P3; Q-T20b-2 = B). Viết TỪ ĐẶC TẢ trước code.

Graph THẬT trên harness (`_t20b.make_flow`: node thật + `InMemorySaver` + ScriptedLLM qua gateway thật + registry đọc seed), 4 intent
bật (tiêm qua `IntentsHarness`). Cha = `T1`, con = `T1-<i>`. Mọi ca thuộc DỪNG 1.
"""

from typing import Any

import pytest
from app.domain.exit_codes import REASON_DETAILS
from app.domain.slots import sanitize_slots
from app.domain.states import S_CLASSIFYING, S_DIAGNOSING, S_ESCALATED
from app.settings import get_slots
from tests.unit._t20b import (
    ADOBE,
    EXTEND,
    PRINTER,
    RESET,
    TC32,
    TC34,
    Flow,
    adobe_item,
    classify,
    extend_item,
    item,
    make_flow,
    oos_item,
    reset_item,
)

pytestmark = pytest.mark.asyncio





VERDICTS = {"runnable", "out_of_scope", "split_span_invalid", "intent_low_confidence", "intent_not_enabled"}


def split_row(f: Flow, n: int) -> dict[str, Any]:
    [row] = [r for r in f.h.audit.rows if r["ticket_id"] == f.parent and r["event"] == f"split_into_{n}_children"]
    return row


def events(f: Flow, ticket_id: str) -> list[tuple[str, str]]:
    return f.h.audit.events(ticket_id)


async def seeds(f: Flow) -> dict[str, dict[str, Any]]:
    return dict((await f.values(f.parent))["child_seeds"])


def assert_started(f: Flow, cid: str) -> None:
    [row] = f.h.audit.of(cid, "child_started")
    assert (row["step"], row["from_status"], row["to_status"]) == ("B5", S_CLASSIFYING, S_DIAGNOSING)
    assert ("B6", "diagnosed") in events(f, cid)


def assert_not_runnable(f: Flow, cid: str, reason: str) -> None:
    [row] = f.h.audit.of(cid, "child_not_runnable")
    assert (row["step"], row["from_status"], row["to_status"], row["exit_code"]) == ("B5", S_CLASSIFYING, S_ESCALATED, "E1")
    assert not any(step == "B6" for step, _ in events(f, cid)), events(f, cid)  # E1 ngay — không chạy B6
    [esc] = f.h.escalations.of(cid)
    assert (esc["exit_code"], esc["reason_detail"]) == ("E1", reason)


async def test_reason_details_has_split_span_invalid() -> None:
    """P2 + 5.2.0 "Mã thoát": `REASON_DETAILS` thêm `split_span_invalid`; `multi_intent_not_enabled` VẪN còn (Q-T20b-2 = B: chỉ code
    mới không ra nữa)."""
    assert {"split_span_invalid", "multi_intent_not_enabled", "out_of_scope", "intent_low_confidence",
            "intent_not_enabled"} <= set(REASON_DETAILS)  # fmt: skip


# ---- v1: 2 ý chạy được --------------------------------------------------------------------------------------------------------


async def test_v1_two_runnable_intents_two_children_both_b6() -> None:
    """v1: 2 con, cả hai `child_started` → B6; `children == [cha-1, cha-2]`; điểm log 1 của cha (B5) có `is_multi`, `children` (số),
    `verdicts` theo `index`; dòng `tickets` con có `parent_ticket_id`, `redacted_request` = span; `child_create` 1 dòng/con."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    row = split_row(f, 2)
    assert (row["step"], row["from_status"], row["to_status"]) == ("B5", S_CLASSIFYING, S_CLASSIFYING)
    d = row["detail"]
    assert (d["is_multi"], d["children"], d["verdicts"]) == (True, 2, ["runnable", "runnable"])
    v = await f.values(f.parent)
    assert (v["is_parent"], v["children"]) == (True, ["T1-1", "T1-2"])
    assert set(v["child_seeds"]) == {"T1-1", "T1-2"}
    assert f.h.tickets.rows["T1"]["is_parent"] is True
    for cid, span in (("T1-1", RESET), ("T1-2", ADOBE)):
        row_c = f.h.tickets.rows[cid]
        assert (row_c["parent_ticket_id"], row_c["redacted_request"]) == ("T1", span)
        assert_started(f, cid)
    assert f.h.tickets.created_children == ["T1-1", "T1-2"]
    assert f.h.effects.count("T1", "child_create") == 2
    subs = sorted(r["step"] for r in f.h.effects.rows.values() if r["ticket_id"] == "T1" and r["kind"] == "child_create")
    assert subs == ["B5", "B5"]
    assert f.b03_calls() == 1  # một lần LLM B3 cho cả câu; con không chạy B1/B2/B3 (P1)
    for cid in ("T1-1", "T1-2"):
        assert not any(step in ("B1", "B2", "B3", "B4") for step, _ in events(f, cid)), events(f, cid)


async def test_v1_point1_no_user_text_no_slot_values() -> None:
    """Điểm log 1 của cha (5.2.2): không câu, không giá trị slot — chỉ mã."""
    f = make_flow(classify(reset_item(), adobe_item()))
    await f.submit(TC34)
    d = split_row(f, 2)["detail"]
    assert set(d["verdicts"]) <= VERDICTS
    for word in (RESET, ADOBE, "Adobe Acrobat Pro", TC34):
        assert word.lower() not in repr(d).lower()


# ---- v2, v3: ý ngoài phạm vi ---------------------------------------------------------------------------------------------------


async def test_v2_one_runnable_one_out_of_scope_splits() -> None:
    """v2: tách; con 2 E1 `out_of_scope` NGAY (không B6, có `escalations` — M-T20b-1); con 1 chạy."""
    f = make_flow(classify(reset_item(), oos_item()))
    await f.submit(TC32)
    assert split_row(f, 2)["detail"]["verdicts"] == ["runnable", "out_of_scope"]
    assert_started(f, "T1-1")
    assert_not_runnable(f, "T1-2", "out_of_scope")
    v2 = await f.values("T1-2")
    assert (v2["status"], v2["exit_code"], v2["escalation_reason_detail"]) == (S_ESCALATED, "E1", "out_of_scope")
    assert f.h.tickets.rows["T1-2"]["redacted_request"] == PRINTER


@pytest.mark.parametrize(
    ("items", "reason", "intent", "confidence"),
    [
        pytest.param([oos_item(), oos_item(span="tiện sửa luôn máy chiếu")], "out_of_scope", None, None,
                     id="hai-y-ngoai-pham-vi"),
        pytest.param([reset_item(confidence=0.3), adobe_item(confidence=0.4)], "intent_low_confidence", "account", 0.3,
                     id="hai-y-trong-pham-vi-deu-thap"),
        pytest.param([oos_item(), reset_item(confidence=0.3)], "intent_low_confidence", "account", 0.3,
                     id="ngoai-pham-vi-va-thap"),
        pytest.param([adobe_item(span="cài Photoshop"), reset_item(confidence=0.2)], "split_span_invalid", "software",
                     0.92, id="span-sai-dau-tien"),
    ],
)  # fmt: skip
async def test_v3_no_runnable_intent_whole_sentence_e1(
    items: list[dict[str, Any]], reason: str, intent: str | None, confidence: float | None
) -> None:
    """v3 + Q-T20b-2 = B: ≥ 2 ý mà 0 ý chạy được → KHÔNG tách, cả câu E1 (step `B4`). Không ý nào trong phạm vi → `out_of_scope`
    (event `intent_out_of_scope`); còn lại → `reason_detail` của Ý ĐẦU TIÊN TRONG PHẠM VI theo bảng 5.2.2, event = đúng chuỗi đó,
    `detail.intent`/`confidence` của ý đó. Không bao giờ `multi_intent_not_enabled`."""
    f = make_flow(classify(*items))
    text = f"{RESET}, tiện {PRINTER}, tiện sửa luôn máy chiếu, {ADOBE}"
    r = await f.submit(text)
    v = dict(r.values)
    assert (r.status, v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E1", reason)
    event = "intent_out_of_scope" if reason == "out_of_scope" else reason
    [row] = [x for x in f.h.audit.rows if x["ticket_id"] == "T1" and x["step"] in ("B3", "B4", "B5")]
    assert (row["step"], row["event"]) == ("B4", event)
    if intent is not None:
        assert (row["detail"]["intent"], row["detail"]["confidence"]) == (intent, confidence)
    assert v.get("is_parent") is not True and not v.get("children")
    assert f.h.tickets.created_children == [] and f.h.effects.count("T1", "child_create") == 0
    assert all(x["event"] != "multi_intent_not_enabled" for x in f.h.audit.rows)


async def test_v3_two_in_scope_not_enabled_whole_sentence_intent_not_enabled() -> None:
    """v3 (Q-T20b-2 = B): 2 ý trong phạm vi đều chưa bật → `intent_not_enabled` của ý đầu."""
    f = make_flow(classify(reset_item(), adobe_item()), intents=frozenset({"vpn"}))
    r = await f.submit(TC34)
    assert (r.values["exit_code"], r.values["escalation_reason_detail"]) == ("E1", "intent_not_enabled")
    assert f.h.tickets.created_children == []


# ---- v4, v5: ý không chạy được thành con E1 ------------------------------------------------------------------------------------


async def test_v4_low_confidence_child_e1_other_runs() -> None:
    """v4: ý `confidence < TAU_INTENT` → con đó E1 `intent_low_confidence`; con kia chạy."""
    f = make_flow(classify(reset_item(), adobe_item(confidence=0.4)))
    await f.submit(TC34)
    assert split_row(f, 2)["detail"]["verdicts"] == ["runnable", "intent_low_confidence"]
    assert_started(f, "T1-1")
    assert_not_runnable(f, "T1-2", "intent_low_confidence")


async def test_v4_not_enabled_child_e1_other_runs() -> None:
    """v4: intent chưa bật (tiêm `enabled_intents` không có `software`) → con đó E1 `intent_not_enabled`; con kia chạy."""
    f = make_flow(classify(reset_item(), adobe_item()), intents=frozenset({"vpn", "account", "access"}))
    await f.submit(TC34)
    assert split_row(f, 2)["detail"]["verdicts"] == ["runnable", "intent_not_enabled"]
    assert_started(f, "T1-1")
    assert_not_runnable(f, "T1-2", "intent_not_enabled")


@pytest.mark.parametrize("span", ["cài Photoshop cho mình", "", "   "], ids=["khong-co-trong-cau", "rong", "khoang-trang"])
async def test_v5_span_not_in_text_child_e1_whole_sentence(span: str) -> None:
    """v5 (bảng 5.2.2 #2): `span` rỗng hoặc không phải đoạn con của câu → con E1 `split_span_invalid`; `redacted_request` của con
    (dòng `tickets` + seed) = CẢ CÂU (L2 đọc được)."""
    f = make_flow(classify(reset_item(), adobe_item(span=span)))
    await f.submit(TC34)
    assert split_row(f, 2)["detail"]["verdicts"] == ["runnable", "split_span_invalid"]
    assert_not_runnable(f, "T1-2", "split_span_invalid")
    assert f.h.tickets.rows["T1-2"]["redacted_request"] == TC34
    assert (await seeds(f))["T1-2"]["redacted_request"] == TC34


# ---- v6, v7: slot / cờ theo từng ý ---------------------------------------------------------------------------------------------


async def test_v6_slot_only_in_other_span_dropped() -> None:
    """v6 (M-T20b-2): `device_id` chỉ có trong span của ý 1 → ý 2 KHÔNG nhận (`sanitize_slots(text=span)`), ý 1 nhận. Đối chứng:
    với CẢ CÂU thì `sanitize_slots` giữ — chính `text=span` là nguyên nhân."""
    zoom, adobe = "cài Zoom cho máy LAP-0342", ADOBE
    text = f"{zoom}, tiện {adobe}"
    i1 = item("software", zoom, action="install_software", slots={"software_name": "Zoom", "device_id": "LAP-0342"})
    i2 = item("software", adobe, action="install_software",
              slots={"software_name": "Adobe Acrobat Pro", "device_id": "LAP-0342"})  # fmt: skip
    f = make_flow(classify(i1, i2))
    await f.submit(text)
    s = await seeds(f)
    assert s["T1-1"]["slots"].get("device_id") == "LAP-0342"
    assert "device_id" not in s["T1-2"]["slots"] and s["T1-2"]["slots"]["software_name"] == "Adobe Acrobat Pro"
    spec = get_slots().intents["software"]
    kept, _ = sanitize_slots(spec, {**i2["slots"], "action": "install_software"}, text=text)
    assert kept.get("device_id") == "LAP-0342"  # đối chứng: cả câu thì giữ


async def test_v7_target_user_dropped_flag_only_on_that_child() -> None:
    """v7 (Q-T20a-4 áp từng con, M-T20b-14): ý account có `target_user` sai mẫu → `ctx_flags.target_is_other=True` ở CON ĐÓ (seed +
    checkpoint con); con kia không có cờ."""
    reset_other = f"{RESET} cho Nguyễn Văn A"
    i1 = item("account", reset_other, action="reset_password", slots={"account_type": "ad", "target_user": "Nguyễn Văn A"})
    f = make_flow(classify(i1, adobe_item()))
    await f.submit(f"{reset_other}, tiện {ADOBE}")
    s = await seeds(f)
    assert s["T1-1"]["ctx_flags"] == {"target_is_other": True}
    assert "target_user" not in s["T1-1"]["slots"]
    assert s["T1-2"].get("ctx_flags") in (None, {})
    assert (await f.values("T1-1"))["ctx_flags"] == {"target_is_other": True}
    assert not ((await f.values("T1-2")).get("ctx_flags") or {}).get("target_is_other")


# ---- v8: đơn ý y nguyên ---------------------------------------------------------------------------------------------------------


async def test_v8_single_intent_unchanged() -> None:
    """v8: 1 ý → đường đơn ý hiện có (B3 `intent_classified` → B6), không B5, không con, `is_parent` False."""
    f = make_flow(classify(reset_item()))
    r = await f.submit(RESET)
    assert ("B3", "intent_classified") in events(f, "T1")
    assert not any(step == "B5" for step, _ in events(f, "T1"))
    assert r.values.get("is_parent") is False and r.values.get("children") == []
    assert f.h.tickets.created_children == [] and f.h.tickets.rows["T1"]["is_parent"] is False


# ---- v9: 3 / 4 ý ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", [3, 4])
async def test_v9_three_four_intents_index_in_llm_order(n: int) -> None:
    """v9: 3 / 4 con, `index` theo thứ tự LLM trả (tối đa 4 ý — `ClassifyOut.intents` max 4)."""
    pool = [reset_item(), adobe_item(), extend_item(), oos_item()][:n]
    text = f"{RESET}, {ADOBE}, {EXTEND}, tiện {PRINTER}"
    f = make_flow(classify(*pool))
    await f.submit(text)
    cids = [f"T1-{i}" for i in range(1, n + 1)]
    row = split_row(f, n)
    assert row["detail"]["children"] == n and len(row["detail"]["verdicts"]) == n
    v = await f.values("T1")
    assert v["children"] == cids and f.h.tickets.created_children == cids
    s = v["child_seeds"]
    assert [s[c]["span"] for c in cids] == [p["span"] for p in pool]
    assert [s[c].get("intent") for c in cids] == [p["type"] if p["type"] != "out_of_scope" else None for p in pool]
