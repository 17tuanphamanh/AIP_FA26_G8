"""Mã yếu tố rủi ro (phase6 5.1 P8, Q-6-5 / D-40) — tập ĐÓNG mà LLM của B14 được chọn (`llm/schemas.RiskEstimateOut`,
`RiskVoteOut`). Nằm ở domain vì `app.llm` không được import `app.risk` (hợp đồng import-linter 8); nhãn tiếng Việt ở
`risk/factors.FACTOR_LABELS`. `reason` của M5 ghép từ nhãn của các mã — không bao giờ từ văn bản tự do của LLM.
"""

from enum import StrEnum


class FactorCode(StrEnum):
    TARGET_IS_OTHER = "target_is_other"
    PRIVILEGED_TARGET = "privileged_target"
    SERVICE_ACCOUNT = "service_account"
    SENSITIVE_DATA = "sensitive_data"
    CROSS_DEPARTMENT = "cross_department"
    LONG_DURATION = "long_duration"
    IRREVERSIBLE = "irreversible"
    OUTSIDE_BUSINESS_HOURS = "outside_business_hours"
    NEW_EMPLOYEE = "new_employee"
    ACCOUNT_STATUS_ABNORMAL = "account_status_abnormal"
    NO_POLICY_EVIDENCE = "no_policy_evidence"
    MISSING_FACTS = "missing_facts"
    ROUTINE_LOW_RISK = "routine_low_risk"
