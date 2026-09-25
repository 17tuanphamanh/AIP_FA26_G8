"""E0–E9, block_reason, close_reason — đúng danh sách đã chốt, không thừa không thiếu."""

from app.domain.exit_codes import (
    BLOCK_TO_CLOSE,
    L2_PRIORITY,
    SECURITY_BLOCK_REASONS,
    BlockReason,
    CloseReason,
    ExitCode,
)


def test_exit_codes_e0_to_e9() -> None:
    assert [c.value for c in ExitCode] == [f"E{i}" for i in range(10)]
    assert set(L2_PRIORITY) == set(ExitCode)


def test_block_reasons() -> None:
    assert {r.value for r in BlockReason} == {
        "invalid_credentials",
        "repeated_auth_failure",
        "injection_detected",
    }
    # invalid_credentials không phải sự cố an ninh (NGU-CANH IV 1.3).
    assert BlockReason.INVALID_CREDENTIALS not in SECURITY_BLOCK_REASONS
    assert len(SECURITY_BLOCK_REASONS) == 2


def test_close_reasons_eight_values() -> None:
    assert {r.value for r in CloseReason} == {
        "resolved_user_confirmed",
        "resolved_auto_timeout_48h",
        "resolved_after_escalation",
        "resolved_after_deny_review",
        "rejected_by_approver",
        "blocked_invalid_credentials",
        "blocked_repeated_auth_failure",
        "blocked_injection_detected",
    }


def test_every_block_reason_maps_to_blocked_close_reason() -> None:
    assert set(BLOCK_TO_CLOSE) == set(BlockReason)
    for block, close in BLOCK_TO_CLOSE.items():
        assert close.value == f"blocked_{block.value}"


def test_values_are_plain_strings() -> None:
    # Ghi thẳng vào state/DB như chuỗi.
    assert ExitCode.E5 == "E5"
    assert CloseReason.REJECTED_BY_APPROVER == "rejected_by_approver"
