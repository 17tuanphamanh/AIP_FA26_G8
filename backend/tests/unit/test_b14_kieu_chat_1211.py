"""E5 soát 12/11 (agent 14 F1, F4; D-90): xác suất B14 và ngưỡng chính sách nhận KIỂU CHẶT.

Trước: `"prob_needs_human": false` → 0.0 (p thấp nhất — sai hướng, không kích hoạt lần sửa schema); `"0.1"` (chuỗi) cũng nhận. Ngưỡng
`THRESHOLD_HIGH: true` → 1.0 (lớp LLM không bao giờ ra L2). Nay: số (int/float) mới hợp lệ; bool / chuỗi → lỗi schema (B14 sửa schema rồi
E5/E9 như mọi đầu ra sai — fail-closed).
"""

import pytest
from app.llm.schemas import RiskEstimateOut
from app.settings import PolicyConstants, get_policy
from pydantic import ValidationError

GOOD = '{{"prob_needs_human": {p}, "factors": [], "rationale": "x"}}'


@pytest.mark.parametrize("p", ["0.5", "0", "1", "0.01"])
def test_so_hop_le(p: str) -> None:
    assert RiskEstimateOut.model_validate_json(GOOD.format(p=p)).prob_needs_human == float(p)


@pytest.mark.parametrize("p", ["false", "true", '"0.1"', '"0"', "null"])
def test_bool_chuoi_null_la_loi(p: str) -> None:
    with pytest.raises(ValidationError):
        RiskEstimateOut.model_validate_json(GOOD.format(p=p))


def test_nguong_chinh_sach_kieu_chat() -> None:
    base = get_policy().constants.model_dump()
    for bad in (True, False, "0.1"):
        for key in ("THRESHOLD_LOW", "THRESHOLD_HIGH"):
            with pytest.raises(ValidationError):
                PolicyConstants.model_validate({**base, key: bad})
    assert PolicyConstants.model_validate({**base, "THRESHOLD_LOW": 0, "THRESHOLD_HIGH": 1}).THRESHOLD_HIGH == 1.0
