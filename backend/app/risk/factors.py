"""Nhãn tiếng Việt của mã yếu tố rủi ro (phase6 5.1 P8) — `strategy.reason_text` nối nhãn bằng "; ". Mã ở
`domain/risk_factors.FactorCode` (llm/schemas cần import mà không được import risk)."""

from collections.abc import Mapping
from types import MappingProxyType

from app.domain.risk_factors import FactorCode

__all__ = ["FACTOR_LABELS", "FactorCode"]

FACTOR_LABELS: Mapping[FactorCode, str] = MappingProxyType({
    FactorCode.TARGET_IS_OTHER: "tác động lên người/máy khác",
    FactorCode.PRIVILEGED_TARGET: "tài khoản/quyền mức cao",
    FactorCode.SERVICE_ACCOUNT: "tài khoản dịch vụ",
    FactorCode.SENSITIVE_DATA: "dữ liệu nhạy cảm",
    FactorCode.CROSS_DEPARTMENT: "tài nguyên phòng ban khác",
    FactorCode.LONG_DURATION: "thời hạn dài",
    FactorCode.IRREVERSIBLE: "khó hoàn tác",
    FactorCode.OUTSIDE_BUSINESS_HOURS: "ngoài giờ hành chính",
    FactorCode.NEW_EMPLOYEE: "nhân viên mới/thử việc",
    FactorCode.ACCOUNT_STATUS_ABNORMAL: "tài khoản không ở trạng thái bình thường",
    FactorCode.NO_POLICY_EVIDENCE: "không có tài liệu quy định liên quan",
    FactorCode.MISSING_FACTS: "thiếu dữ kiện",
    FactorCode.ROUTINE_LOW_RISK: "việc thường ngày, rủi ro thấp",
})  # fmt: skip
