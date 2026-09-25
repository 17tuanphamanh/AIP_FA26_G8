"""Ma trận quyền — NGU-CANH 2.2 thành permission [Chốt 2.2, P6 mục 5.1].

Nằm trong code, không trong DB: ai sửa được bảng quyền thì tự cấp được mọi quyền. Đổi quyền phải
qua PR + review. Hai quy tắc gốc ép bằng test: `policy:edit` ∉ l1, `approval:decide` ∉ l2.
"""

from collections.abc import Mapping

from app.domain.context import Role

_BASE = frozenset({"ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"})

PERMS: Mapping[Role, frozenset[str]] = {
    "employee": _BASE,
    "l1": _BASE
    | {
        "ticket:read:any", "approval:decide", "decision:override",
        "escalation:handle", "dashboard:read:own", "audit:read:own",
    },
    "manager": _BASE
    | {
        "ticket:read:any", "approval:decide", "decision:override",
        "policy:read", "policy:edit", "dashboard:read:all", "audit:read:all",
        "kb:edit", "alert:read",
    },
    "l2": _BASE | {"ticket:read:any", "escalation:handle", "kb:edit"},
}  # fmt: skip

ALL_PERMISSIONS: frozenset[str] = frozenset().union(*PERMS.values())

# Thu hồi mọi phiên của người khác (POST /api/admin/users/{id}/revoke) — P6 mục 8: "manager + xác
# nhận lại". Không thêm permission mới vào PERMS [Chốt 2.2]; route dùng hằng này, không viết role cứng.
ADMIN_REVOKE_ROLES: frozenset[Role] = frozenset({"manager"})


def permissions_of(role: Role) -> frozenset[str]:
    return PERMS[role]


def has_perm(role: Role, perm: str) -> bool:
    return perm in PERMS[role]
