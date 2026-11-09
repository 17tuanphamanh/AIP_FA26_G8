"""M1 (ĐP 08/11): chuẩn hoá mã máy người dùng gõ lỏng → dạng chuẩn danh mục `LAP-0012` TRƯỚC khi so mẫu slot và tra mock.

- "lap-0012", "LAP0012", " lap 0012 ", "LAP-0012" → `LAP-0012` (hàm thuần + `sanitize_slots`, cả khi LLM đã tự chuẩn hoá mà câu người dùng
  vẫn ở dạng lỏng).
- Dạng không đúng dáng mã máy → GIỮ NGUYÊN → sai mẫu → bỏ (`bad_value`) → B11 hỏi lại như cũ (không đoán).
- Mã không có trong câu vẫn bị bỏ (`slot_not_in_text`), kể cả khi khác đúng một chữ số ở biên ("LAP-00123").
- Chuỗi đủ: mã máy của CHÍNH người gửi gõ lỏng → tra mock bằng mã chuẩn, `Action` dựng trên `device:LAP-0342`; audit ghi mã chuẩn, không
  ghi chữ người dùng. Mã máy của NGƯỜI KHÁC gõ lỏng → luật sai đối tượng (L-03, be-target-guard-2) vẫn chặn: E5, 0 phiếu, 0 lần thực hiện.

ScriptedLLM, không key, không Postgres. Seed: nv001 có đúng 1 máy LAP-0342; LAP-0610 của nv005.
"""

from typing import Any

import pytest
from app.domain.action import Action
from app.domain.slots import canonical_device_id, sanitize_slots
from app.domain.states import S_CLARIFYING, S_ESCALATED
from app.settings import get_slots
from tests.unit._t20b import classify, item, make_flow

SLOTS = get_slots()
VPN = SLOTS.intents["vpn"]
SOFT = SLOTS.intents["software"]
LOOSE = ["lap-0012", "LAP0012", " lap 0012 ", "LAP-0012", "Lap-0012", "lap0012"]
INVALID = ["lap_0012", "LAP-12", "LAP-001234", "LAPTOP-0012", "L-0012", "lap--0012", "lap  0012", "LAP-00a2", "nv0012", "0012"]


# ---- hàm thuần ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", LOOSE)
def test_canonical_loose_forms(raw: str) -> None:
    assert canonical_device_id(raw) == "LAP-0012"


@pytest.mark.parametrize("raw", ["LAP-0342", "PC-0977", "LAP-04171", "ABCD-123"])
def test_canonical_already_standard_unchanged(raw: str) -> None:
    assert canonical_device_id(raw) == raw


@pytest.mark.parametrize("raw", INVALID)
def test_canonical_invalid_kept_as_is(raw: str) -> None:
    """Không đúng dáng mã máy → trả nguyên chuỗi (không đoán). `nv0012` là mã nhân viên, không thành `NV-0012`."""
    assert canonical_device_id(raw) == raw


# ---- sanitize_slots (cửa duy nhất của B3 và câu trả lời B11) ------------------------------------------------------------------


@pytest.mark.parametrize("raw", LOOSE)
def test_sanitize_normalizes_device_id_user_form_in_text(raw: str) -> None:
    """Người dùng gõ `raw` trong câu, LLM chép nguyên `raw` → slot sạch là mã chuẩn."""
    clean, dropped = sanitize_slots(VPN, {"device_id": raw}, text=f"VPN lỗi chứng chỉ trên máy {raw} từ sáng")
    assert (clean, dropped) == ({"device_id": "LAP-0012"}, {})


@pytest.mark.parametrize("typed", LOOSE)
def test_sanitize_llm_canonical_but_user_typed_loose(typed: str) -> None:
    """LLM tự chuẩn hoá thành `LAP-0012` còn câu người dùng ở dạng lỏng → vẫn tính là có thật trong câu."""
    clean, dropped = sanitize_slots(VPN, {"device_id": "LAP-0012"}, text=f"máy {typed} không vào được VPN")
    assert (clean, dropped) == ({"device_id": "LAP-0012"}, {})


@pytest.mark.parametrize("raw", INVALID)
def test_sanitize_invalid_device_id_dropped_bad_value(raw: str) -> None:
    clean, dropped = sanitize_slots(VPN, {"device_id": raw}, text=f"VPN lỗi trên máy {raw}")
    assert "device_id" not in clean
    assert dropped == {"device_id": "bad_value"}


@pytest.mark.parametrize(
    ("value", "text"),
    [("lap0099", "VPN lỗi trên máy LAP-0012"), ("LAP0012", "VPN lỗi trên máy LAP-00123"), ("LAP-0012", "máy ALAP0012 lỗi"),
     ("lap 0012", "VPN lỗi trên máy PC-0012"), ("LAP-0012", "máy LAP0012x lỗi"), ("LAP-0012", "mã 9LAP0012 lỗi"),
     ("LAP-0012", "máy LAP-0012_b lỗi")],
)  # fmt: skip
def test_sanitize_device_not_in_text_still_dropped(value: str, text: str) -> None:
    clean, dropped = sanitize_slots(VPN, {"device_id": value}, text=text)
    assert "device_id" not in clean
    assert dropped == {"device_id": "slot_not_in_text"}


def test_sanitize_software_intent_also_normalizes() -> None:
    clean, dropped = sanitize_slots(SOFT, {"software_name": "Zoom", "device_id": "lap0342"}, text="cài Zoom lên máy lap0342")
    assert (clean, dropped) == ({"software_name": "Zoom", "device_id": "LAP-0342"}, {})


# ---- chuỗi đủ: máy của chính người gửi --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("typed", ["lap-0342", "LAP0342", "lap 0342"])
async def test_chain_own_device_loose_looks_up_canonical(typed: str) -> None:
    """B3 nhận slot dạng lỏng → B6/B11 tra mock bằng `LAP-0342` (máy có thật của nv001) → không hỏi, `Action` đúng máy, chủ máy = người
    gửi. Audit: mã chuẩn trong cột `intended_action`, không dòng nào chép dạng người dùng gõ."""
    text = f"Cấp lại chứng chỉ VPN cho máy {typed}"
    f = make_flow(classify(item("vpn", text, action="renew_vpn_cert", slots={"device_id": typed})))
    await f.submit(text)
    v = await f.values("T1")
    assert not (v.get("ctx_flags") or {}).get("target_is_other"), f.h.audit.events("T1")
    assert "asked" not in {e for _, e in f.h.audit.events("T1")}
    assert v["slots"]["device_id"] == "LAP-0342"
    action = Action.model_validate(v["intended_action"])
    assert action.target == "device:LAP-0342" and action.params["device_id"] == "LAP-0342"
    assert action.facts["device_registered"] is True and action.facts["device_owner_is_requester"] is True
    rows = [r for r in f.h.audit.rows if r["ticket_id"] == "T1"]
    built = [r for r in rows if r.get("intended_action")]
    assert built and all(r["intended_action"]["params"]["device_id"] == "LAP-0342" for r in built)
    # M1 không THÊM chữ người dùng vào audit. Ngoại lệ có sẵn từ trước, ngoài phạm vi slot: `detail.query` của B8 = câu truy hồi RAG
    # (câu đã che của người dùng, B08).
    scrubbed = [{**r, "detail": {k: v for k, v in r["detail"].items() if not (r["step"] == "B8" and k == "query")}} for r in rows]
    assert all(typed not in repr(r) for r in scrubbed)


# ---- chuỗi đủ: máy người khác (L-03 vẫn chặn) / dạng sai → hỏi lại ----------------------------------------------------------

DA_A = "Chị Hoa bên Sales lỗi VPN, nhờ IT cấp lại chứng chỉ cho máy chị ấy"


def _device_reply(variables: Any) -> dict[str, str]:
    """`b11_extract_slots` chép nguyên chữ người dùng gõ vào `device_id`."""
    return {"device_id": str(variables["text"]).strip()}


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["lap-0610", "LAP0610", " lap 0610 "])
async def test_chain_other_device_loose_answer_still_e5(answer: str) -> None:
    f = make_flow(classify(item("vpn", DA_A, action="renew_vpn_cert")), extract=_device_reply)
    r = await f.submit(DA_A)
    assert (r.status, r.waiting_at) == (S_CLARIFYING, "clarify_wait"), f.h.audit.events("T1")
    r = await f.deliver("T1", S_CLARIFYING, {"kind": "user_reply", "text": answer})  # máy của nv005
    v = await f.values("T1")
    assert (r.status, v["exit_code"]) == (S_ESCALATED, "E5"), (v.get("escalation_reason_detail"), f.h.audit.events("T1"))
    assert v["slots"]["device_id"] == "LAP-0610"
    action = Action.model_validate(v["intended_action"])
    assert action.target == "device:LAP-0610" and action.facts["device_owner_is_requester"] is False
    assert f.h.approvals.count("T1") == 0
    assert f.h.executor.calls["T1"] == 0
    assert not {s for s, _ in f.h.audit.events("T1")} & {"B17", "B18"}


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", ["lap_0610", "LAP-06", "máy chị Hoa"])
async def test_chain_invalid_answer_asks_again(answer: str) -> None:
    f = make_flow(classify(item("vpn", DA_A, action="renew_vpn_cert")), extract=_device_reply)
    await f.submit(DA_A)
    r = await f.deliver("T1", S_CLARIFYING, {"kind": "user_reply", "text": answer})
    v = await f.values("T1")
    assert (r.status, r.waiting_at) == (S_CLARIFYING, "clarify_wait"), f.h.audit.events("T1")
    assert "device_id" not in v["slots"] and "device_id" in v["missing_slots"]
    assert v["clarification_turns"] == 2
    assert v.get("intended_action") is None
