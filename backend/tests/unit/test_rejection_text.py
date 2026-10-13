"""Tin từ chối B16 theo mẫu — Phase 4 chặng 4c P1 (phase4 6.1), PLAN-4c TQ-1, TQ-3, test d4.

Mẫu: "Yêu cầu {nhãn hành động} cho {máy X | máy của bạn} chưa được duyệt. Lý do: {nhãn mã | không nêu}. Ghi chú của người duyệt:
{ghi chú đã che}". Không LLM. Hành động không có nhãn (node giả gate2) → câu chung, KHÔNG ném (ticket phải về `S_REJECTED`).

T20a (phase5 5.1.1 P11, PLAN-T20a TQ-16): đối số thứ 2 của `rejection_text` đổi từ `device_id` sang CỤM ĐÍCH (`target_phrase(action,
requester_id)` — "máy LAP-0501", "máy của bạn"…). Đổi CHỮ KÝ GỌI ở `test_rejection_text_template`; chuỗi kỳ vọng của các ca VPN GIỮ
NGUYÊN. (Viết trước code ở DỪNG 1, chờ DỪNG 2 — đã gỡ chờ.)
"""

from typing import get_args

import pytest
from app.db.models import NOTICE_KINDS
from app.domain.action import Action
from app.domain.messages import (
    ACTION_LABELS,
    MSG_KINDS,
    REASON_LABELS,
    ReasonCode,
    rejection_msg,
    rejection_text,
    target_phrase,
)
from app.settings import get_action_metadata


def _vpn_action(action_type: str, target: str) -> Action:
    return Action(
        type=action_type, target=target, requested_for="nv003", scope="single_device", privilege_level="standard_user",
        reversible=True, reversibility="full", data_sensitivity="low", params={}, facts={},
    )  # fmt: skip


def test_d4_every_action_type_has_label() -> None:
    """d4: mọi `action_type` khai trong `config/action_metadata.yaml` có nhãn — hành động thật không bao giờ rơi vào câu chung."""
    declared = {t for metas in get_action_metadata().root.values() for t in metas}
    assert declared, "action_metadata.yaml rỗng?"
    assert declared <= set(ACTION_LABELS)


def test_d4_reason_labels_match_reason_codes_exactly() -> None:
    """d4: nhãn lý do ĐÚNG bằng tập mã cố định mà route nhận (một nguồn `ReasonCode`)."""
    assert set(REASON_LABELS) == set(get_args(ReasonCode.__value__))


def test_rejection_kind_matches_db_notice_kinds() -> None:
    assert "rejection" in MSG_KINDS and "rejection" in NOTICE_KINDS


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        pytest.param(
            ("renew_vpn_cert", "device:LAP-0501", "wrong_device", "máy không phải của bạn"),
            "Yêu cầu gia hạn chứng chỉ VPN cho máy LAP-0501 chưa được duyệt. Lý do: sai máy. "
            "Ghi chú của người duyệt: máy không phải của bạn",
            id="du-ba-phan",
        ),
        pytest.param(
            ("reissue_vpn_access", "device:PC-0977", None, "chưa đủ căn cứ"),
            "Yêu cầu cấp lại quyền truy cập VPN cho máy PC-0977 chưa được duyệt. Lý do: không nêu. "
            "Ghi chú của người duyệt: chưa đủ căn cứ",
            id="khong-ma-ly-do",
        ),
        pytest.param(
            ("renew_vpn_cert", "device:LAP-0501", "security_concern", None),
            "Yêu cầu gia hạn chứng chỉ VPN cho máy LAP-0501 chưa được duyệt. Lý do: lo ngại về bảo mật.",
            id="ghi-chu-bi-bo",
        ),
        pytest.param(
            ("renew_vpn_cert", "device:không phải mã máy", "other", "x"),
            "Yêu cầu gia hạn chứng chỉ VPN cho máy của bạn chưa được duyệt. Lý do: lý do khác. Ghi chú của người duyệt: x",
            id="ma-may-sai-mau",
        ),
        pytest.param(
            ("vpn_reset_session", "device:", "missing_info", "thiếu"),
            "Yêu cầu của bạn chưa được duyệt. Lý do: thiếu thông tin. Ghi chú của người duyệt: thiếu",
            id="hanh-dong-khong-nhan-cau-chung",
        ),
        pytest.param(
            ("renew_vpn_cert", "device:LAP-0501", "ma_la", "x"),
            "Yêu cầu gia hạn chứng chỉ VPN cho máy LAP-0501 chưa được duyệt. Lý do: không nêu. Ghi chú của người duyệt: x",
            id="ma-ly-do-la",
        ),
    ],
)
def test_rejection_text_template(args: tuple[str, str, str | None, str | None], expected: str) -> None:
    """Đổi ở T20a (P11): đối số 2 = `target_phrase(action, requester_id)` (cột 2 của bảng nay là `action.target`); chuỗi kỳ vọng
    VPN không đổi."""
    action_type, target, reason_code, note = args
    phrase = target_phrase(_vpn_action(action_type, target), "nv003")
    assert rejection_text(action_type, phrase, reason_code, note) == expected


def test_rejection_msg_shape() -> None:
    assert rejection_msg("t", "m1") == {"role": "assistant", "kind": "rejection", "text": "t", "ref": "m1", "needs": "none"}
