"""P6 test 2: ma trận NGU-CANH 2.2 (10 chức năng × 4 vai trò = 40 ô) + 2 quy tắc cứng; role cho
thu hồi phiên (ADMIN_REVOKE_ROLES) gom ở permissions.py."""

import pytest
from app.auth.permissions import ADMIN_REVOKE_ROLES, ALL_PERMISSIONS, PERMS, has_perm

ROLES = ("employee", "l1", "manager", "l2")

# Chép nguyên văn bảng NGU-CANH-DAY-DU.md mục 2.2: ✓ = True, ✗ = False, "Phần của mình" = "own",
# "Toàn bộ" = "all". Mỗi chức năng → permission tương ứng ở P6 mục 5.1.
MATRIX: dict[str, tuple[dict[str, bool | str], tuple[str, ...]]] = {
    "Gửi yêu cầu IT": (
        {"employee": True, "l1": True, "manager": True, "l2": True}, ("ticket:create",)),
    "Xem ticket của mình": (
        {"employee": True, "l1": True, "manager": True, "l2": True}, ("ticket:read:own",)),
    "Xem ticket người khác": (
        {"employee": False, "l1": True, "manager": True, "l2": True}, ("ticket:read:any",)),
    "Phê duyệt hành động nhạy cảm": (
        {"employee": False, "l1": True, "manager": True, "l2": False}, ("approval:decide",)),
    "Ghi đè quyết định agent": (
        {"employee": False, "l1": True, "manager": True, "l2": False}, ("decision:override",)),
    "Tiếp nhận ticket escalate": (
        {"employee": False, "l1": True, "manager": False, "l2": True}, ("escalation:handle",)),
    "Cấu hình policy và ngưỡng": (
        {"employee": False, "l1": False, "manager": True, "l2": False}, ("policy:edit",)),
    "Xem dashboard thống kê": (
        {"employee": False, "l1": "own", "manager": "all", "l2": False},
        ("dashboard:read:own", "dashboard:read:all")),
    "Tra cứu audit log": (
        {"employee": False, "l1": "own", "manager": "all", "l2": False},
        ("audit:read:own", "audit:read:all")),
    "Cập nhật Knowledge Base": (
        {"employee": False, "l1": False, "manager": True, "l2": True}, ("kb:edit",)),
}  # fmt: skip

CELLS = [(fn, role) for fn in MATRIX for role in ROLES]


def test_matrix_has_40_cells() -> None:
    assert len(MATRIX) == 10
    assert len(CELLS) == 40


@pytest.mark.parametrize(("function", "role"), CELLS)
def test_matrix_cell(function: str, role: str) -> None:
    expected, perms = MATRIX[function]
    cell = expected[role]
    granted = {p for p in perms if has_perm(role, p)}  # type: ignore[arg-type]
    if cell is True:
        assert granted == set(perms), f"{role} phải có {perms}"
    elif cell is False:
        assert granted == set(), f"{role} KHÔNG được có {perms}"
    else:  # "own" / "all": đúng một phạm vi
        scope = {p.rsplit(":", 1)[1] for p in granted}
        assert scope == {cell}, f"{role} phải chỉ có phạm vi {cell}, đang có {granted}"


def test_hard_rule_l1_cannot_edit_policy() -> None:
    assert "policy:edit" not in PERMS["l1"]


def test_hard_rule_l2_cannot_approve() -> None:
    assert "approval:decide" not in PERMS["l2"]


def test_only_manager_can_revoke_other_sessions() -> None:
    assert ADMIN_REVOKE_ROLES == frozenset({"manager"})
    assert "l1" not in ADMIN_REVOKE_ROLES and "l2" not in ADMIN_REVOKE_ROLES


def test_every_permission_belongs_to_the_matrix_or_p6() -> None:
    # Không ai lặng lẽ thêm quyền mới: danh sách đầy đủ = P6 mục 5.1.
    assert ALL_PERMISSIONS == {
        "ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm", "ticket:read:any",
        "approval:decide", "decision:override", "escalation:handle", "dashboard:read:own",
        "dashboard:read:all", "audit:read:own", "audit:read:all", "policy:read", "policy:edit",
        "kb:edit", "alert:read", "llm_status:read",
        "escalation:handle:l3",  # D-99 (TA chốt 17/11): Trưởng bộ phận IT nhận ca L2 chuyển lên
    }  # fmt: skip


def test_d99_only_manager_handles_tier3_and_manager_not_tier2() -> None:
    assert {r for r, perms in PERMS.items() if "escalation:handle:l3" in perms} == {"manager"}
    assert "escalation:handle" not in PERMS["manager"]  # Trưởng IT không xử lý ca cấp 2 (giữ ma trận P6)


def test_llm_status_read_is_manager_only() -> None:
    # I1: trang Trạng thái LLM chỉ đọc — chỉ Trưởng BP IT.
    assert [r for r in PERMS if "llm_status:read" in PERMS[r]] == ["manager"]
