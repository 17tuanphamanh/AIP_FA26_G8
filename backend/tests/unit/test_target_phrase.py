"""T20a — tin từ chối theo đích (phase5 5.1.1 P11, 5.1.6 m1, m2; PLAN-T20a TQ-16). Viết TỪ ĐẶC TẢ, trước code — DỪNG 2.

`target_phrase(action, requester_id)`: `device:<id>` → "máy <id>" (mẫu `DEVICE_ID`; không khớp → "máy của bạn" — giữ chữ VPN cũ);
`user:<id>` → id == người gửi ? "tài khoản của bạn" : "tài khoản <id>" (mẫu `^[a-z0-9_]{3,64}$`; không khớp → "tài khoản được yêu cầu");
`folder:<path>` → "thư mục <path>" (mẫu `resource_path`; không khớp → "thư mục được yêu cầu"). `rejection_text(action_type,
target_phrase, reason_code, note)`; `approval_wait._rejected` truyền `target_phrase(action, requester)`.
"""

from typing import Any

import pytest
from app.domain.action import Action
from app.domain.messages import (
    DEVICE_ID,
    RESOURCE_PATH,
    USER_ID,
    rejection_text,
    target_phrase,
)
from app.domain.states import S_PENDING_APPROVAL, S_REJECTED
from app.graph.late_event import deliver_event
from app.settings import get_action_metadata, get_slots
from tests.fakes.graph import GraphHarness
from tests.unit.test_b16_approval_wait import _event, _pending


def _action(action_type: str, target: str, requested_for: str = "nv001", params: dict[str, Any] | None = None) -> Action:
    intent = {"renew_vpn_cert": "vpn", "reset_password": "account", "view_permissions": "access",
              "grant_permission": "access", "install_software": "software"}[action_type]  # fmt: skip
    m = get_action_metadata().of(intent)[action_type]
    return Action(
        type=action_type, target=target, requested_for=requested_for, scope=m.scope, privilege_level=m.privilege_level,
        reversible=m.reversible, reversibility=m.reversibility, data_sensitivity=m.data_sensitivity,
        params=dict(params or {}), facts={},
    )  # fmt: skip


@pytest.mark.parametrize(
    ("action_type", "target", "expected"),
    [
        pytest.param("renew_vpn_cert", "device:LAP-0342", "máy LAP-0342", id="m1-device-LAP-0342"),
        pytest.param("install_software", "device:PC-0977", "máy PC-0977", id="m1-device-software"),
        pytest.param("renew_vpn_cert", "device:lap 0342; rm", "máy của bạn", id="m1-device-sai-mau-giu-chu-vpn-cu"),
        pytest.param("reset_password", "user:nv001", "tài khoản của bạn", id="m1-user-chinh-minh"),
        pytest.param("reset_password", "user:nv005", "tài khoản nv005", id="m1-user-nv005"),
        pytest.param("reset_password", "user:NV005<script>", "tài khoản được yêu cầu", id="m1-user-sai-mau"),
        pytest.param("view_permissions", "user:", "tài khoản được yêu cầu", id="m1-user-rong"),
        pytest.param("grant_permission", "folder:finance/Q3", "thư mục finance/Q3", id="m1-folder-finance-Q3"),
        pytest.param("grant_permission", "folder:../../etc/passwd", "thư mục được yêu cầu", id="m1-folder-sai-mau"),
        pytest.param("grant_permission", "folder:finance/Q3 cho tôi toàn quyền", "thư mục được yêu cầu",
                     id="m1-folder-chu-tu-do"),
    ],
)
def test_m1_target_phrase(action_type: str, target: str, expected: str) -> None:
    """m1 (P11, M-T20a-14): đúng chữ 5.1.1 P11 cho từng loại đích; chuỗi lạ / sai mẫu → cụm mặc định (không chép chữ người dùng
    ngoài định danh đã qua regex — 5.1.8 mục 8)."""
    assert target_phrase(_action(action_type, target), "nv001") == expected


@pytest.mark.parametrize(
    ("action_type", "phrase", "expected"),
    [
        pytest.param("grant_permission", "thư mục finance/Q3",
                     "Yêu cầu cấp quyền truy cập cho thư mục finance/Q3 chưa được duyệt. Lý do: trái chính sách.",
                     id="m1-grant-folder"),
        pytest.param("reset_password", "tài khoản nv005",
                     "Yêu cầu đặt lại mật khẩu cho tài khoản nv005 chưa được duyệt. Lý do: trái chính sách.",
                     id="m1-reset-nguoi-khac"),
        pytest.param("unlock_account", "tài khoản của bạn",
                     "Yêu cầu mở khoá tài khoản cho tài khoản của bạn chưa được duyệt. Lý do: trái chính sách.",
                     id="m1-unlock-chinh-minh"),
        pytest.param("renew_vpn_cert", "máy LAP-0501",
                     "Yêu cầu gia hạn chứng chỉ VPN cho máy LAP-0501 chưa được duyệt. Lý do: trái chính sách.",
                     id="m1-vpn-giu-chu-cu"),
    ],
)
def test_m1_rejection_text_uses_phrase(action_type: str, phrase: str, expected: str) -> None:
    """P11: `rejection_text(action_type, target_phrase, reason_code, note)` ghép CỤM ĐÍCH thay cho "máy …"."""
    assert rejection_text(action_type, phrase, "policy_violation", None) == expected


@pytest.mark.asyncio
async def test_m2_b16_rejects_grant_permission_folder_phrase() -> None:
    """m2: B16 (node thật `approval_wait`) từ chối `grant_permission` `folder:finance/Q3` → tin "Yêu cầu cấp quyền truy cập cho
    thư mục finance/Q3 chưa được duyệt. …" (không còn "cho máy …")."""
    h = GraphHarness()
    action = _action("grant_permission", "folder:finance/Q3", "nv-fake",
                     {"resource_path": "finance/Q3", "permission_level": "read", "duration_days": 30})  # fmt: skip
    await _pending(h, action=action)
    note = "thư mục nhạy cảm, cần trưởng phòng Kế toán duyệt"  # từ chối bắt buộc có ghi chú (CHECK rejected_needs_note)
    await deliver_event(h.runner, "t1", S_PENDING_APPROVAL,
                        _event(h, "rejected", reason_code="policy_violation", note=note))  # fmt: skip
    snap = await h.runner.snapshot("t1")
    assert snap.values["status"] == S_REJECTED
    msgs = [m for m in snap.values["conversation"] if m.get("kind") == "rejection"]
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg["text"].startswith(
        "Yêu cầu cấp quyền truy cập cho thư mục finance/Q3 chưa được duyệt. Lý do: trái chính sách."
    ), msg["text"]
    assert "máy" not in msg["text"]


def test_m1_phrase_patterns_equal_slots_yaml() -> None:
    """5.1.8 mục 8 (agent chính thêm, DỪNG 2): mẫu định danh ghép vào tin == `value_rules` của `slots.yaml` (một luật, hai chỗ — lệch
    nhau thì tin từ chối nhận định danh mà slot không nhận, hoặc ngược lại). Có cả ca chặn đoạn "."/".." (p7)."""
    rules = get_slots().intents
    assert f"^{USER_ID.pattern}$" == rules["account"].value_rules["target_user"].pattern
    assert f"^{USER_ID.pattern}$" == rules["access"].value_rules["target_user"].pattern
    assert f"^{RESOURCE_PATH.pattern}$" == rules["access"].value_rules["resource_path"].pattern
    assert f"^{DEVICE_ID.pattern}$" == rules["vpn"].value_rules["device_id"].pattern
    assert target_phrase(_action("grant_permission", "folder:finance/.."), "nv001") == "thư mục được yêu cầu"
