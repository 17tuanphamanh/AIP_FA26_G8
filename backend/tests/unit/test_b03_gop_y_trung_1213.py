"""U1 (CLI-5, soát 12/11 agent 18 L1): LLM tách MỘT việc thành 2 ý cùng loại → 2 ticket con → thực thi 2 lần (mật khẩu tạm lần 1 mất
hiệu lực) hoặc vừa báo "đã làm" vừa hỏi lại cho cùng một việc.

Luật gộp (B3, TRƯỚC khi tách): hai ý CHẠY ĐƯỢC cùng `type` + cùng `action_hint` (khác None) mà slot sạch của một ý ⊆ ý kia → bỏ ý ít
thông tin hơn (bằng nhau → giữ ý trước). Còn một ý → đường đơn ý. Audit ghi `deduplicated_intents` (số ý đã gộp), không chữ.
Khác đích (slot lệch), không có `action_hint`, khác loại → giữ nguyên, tách như cũ.
"""

import pytest
from tests.unit.test_b03_classify import _run, item, out

pytestmark = pytest.mark.asyncio

TEXT = "Gia hạn VPN cho máy LAP-0342, gia hạn chứng chỉ VPN trên LAP-0342 giúp em"
A = "Gia hạn VPN cho máy LAP-0342"
B = "gia hạn chứng chỉ VPN trên LAP-0342 giúp em"
DEV = {"device_id": "LAP-0342"}


async def test_hai_y_giong_het_gop_thanh_mot() -> None:
    v, row, _, _ = await _run([out(item("vpn", 0.9, span=A, action="renew_vpn_cert", slots=DEV),
                                   item("vpn", 0.9, span=B, action="renew_vpn_cert", slots=DEV))], text=TEXT)  # fmt: skip
    assert (row["step"], row["event"]) == ("B3", "intent_classified")
    assert row["detail"]["deduplicated_intents"] == 1
    assert v["intent"] == "vpn" and not v.get("children")
    assert v["slots"].get("device_id") == "LAP-0342"
    assert TEXT not in str(row["detail"])


async def test_y_sau_it_thong_tin_hon_bi_bo() -> None:
    v, row, _, _ = await _run([out(item("vpn", 0.9, span=A, action="renew_vpn_cert", slots=DEV),
                                   item("vpn", 0.9, span=B, action="renew_vpn_cert"))], text=TEXT)  # fmt: skip
    assert row["event"] == "intent_classified" and row["detail"]["deduplicated_intents"] == 1
    assert v["slots"].get("device_id") == "LAP-0342"


async def test_y_truoc_it_thong_tin_hon_thi_giu_y_sau() -> None:
    v, row, _, _ = await _run([out(item("vpn", 0.9, span=A, action="renew_vpn_cert"),
                                   item("vpn", 0.9, span=B, action="renew_vpn_cert", slots=DEV))], text=TEXT)  # fmt: skip
    assert row["event"] == "intent_classified" and row["detail"]["deduplicated_intents"] == 1
    assert v["slots"].get("device_id") == "LAP-0342"


async def test_khac_may_van_tach() -> None:
    text = "Gia hạn VPN cho máy LAP-0342, gia hạn VPN cho máy LAP-0417 nữa"
    _, row, _, _ = await _run([out(item("vpn", 0.9, span="Gia hạn VPN cho máy LAP-0342", action="renew_vpn_cert", slots=DEV),
                                   item("vpn", 0.9, span="gia hạn VPN cho máy LAP-0417 nữa", action="renew_vpn_cert",
                                        slots={"device_id": "LAP-0417"}))], text=text)  # fmt: skip
    assert (row["step"], row["event"]) == ("B5", "split_into_2_children")
    assert "deduplicated_intents" not in row["detail"]


async def test_khong_co_action_hint_van_tach() -> None:
    _, row, _, _ = await _run([out(item("vpn", 0.9, span=A, slots=DEV), item("vpn", 0.9, span=B, slots=DEV))], text=TEXT)
    assert (row["step"], row["event"]) == ("B5", "split_into_2_children")


async def test_khac_hanh_dong_van_tach() -> None:
    _, row, _, _ = await _run([out(item("vpn", 0.9, span=A, action="renew_vpn_cert", slots=DEV),
                                   item("vpn", 0.9, span=B, action="check_vpn_status", slots=DEV))], text=TEXT)  # fmt: skip
    assert (row["step"], row["event"]) == ("B5", "split_into_2_children")
