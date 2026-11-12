"""PLAN — "làm gì" cho từng `action_type` (B17 §3, phase3 11.4; Phase 5 T24 bảng 7.2, D-48). Chỉ metadata: KHÔNG import adapter
ghi (hợp đồng import-linter 3) — node B17 và `graph/wiring` đọc được module này.

- `renew_vpn_cert` → 1 bước `renew_vpn_cert`, hoàn tác `revoke_vpn_cert(serial của bước cấp)`.
- `reissue_vpn_access` → 1 bước `reissue_vpn_access`, hoàn tác như trên.
- `check_vpn_status`, `view_permissions` → `()` (3-Q31: không ghi, không `transaction_log`).
- `reset_password` / `unlock_account` → 1 bước, hoàn tác `lock_account(reason="admin")` (reset: partial — mật khẩu cũ không về).
- `install_software` → ① `assign_paid_license` (CHỈ khi `license_paid is not False` — thiếu fact coi như CÓ phí: không bao giờ cài
  phần mềm có phí khi chưa cấp license; KHÔNG hoàn tác được) → ② `install_software` (hoàn tác `uninstall_software`). License trước:
  hết license → dừng khi chưa ghi gì; cài lỗi sau khi đã cấp license → không gọi hoàn tác (D-48, cổng 5).
- `grant_permission` → hoàn tác `revoke_permission`; `extend_permission` (KHÔNG gửi mức quyền — Q-T22a-8) → hoàn tác
  `restore_permission_expiry(previous_expires_at của bước gia hạn)`.

Tham số ghi CHỈ từ `Action` (P7): `user_id` luôn là `requested_for` (người bị tác động), không bao giờ người gửi.

`check_plans` (h23; T24 P2) — fail-closed lúc khởi động (`graph/wiring.open_runtime`, cả backend lẫn worker): mọi `action_type` của
intent đang bật trong `action_metadata.yaml` phải có PLAN + mẫu tin kết quả B18 (`domain.messages.RESULT_ACTIONS`); mỗi bước là tool
GHI đã khai báo (`tools/specs.py`), `undo` đúng `undo_tool` của tool đó; metadata `reversibility: none` ⇒ không bước nào có `undo`;
`reversible` ⇒ ít nhất MỘT bước hoàn tác được; PLAN rỗng ⇔ hành động chỉ đọc (`READ_ONLY_ACTIONS`). Thiếu PLAN phải là lỗi cấu
hình khi khởi động, không phải E9 lúc chạy (B17 §13).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from app.domain.action import Action, ActionMeta
from app.domain.messages import RESULT_ACTIONS
from app.tools.specs import REGISTRY, ToolSpec


@dataclass(frozen=True)
class Step:
    tool: str  # tool ghi (kind=write, allowed_steps {"B17"})
    undo: str | None = None  # tool hoàn tác (cũng là tool ghi) — None khi không hoàn tác được
    # T24 P2 (D-48): bước có điều kiện — "paid_license" chỉ giữ khi `action.facts.get("license_paid") is not False`
    when: Literal["always", "paid_license"] = "always"


PLAN: Mapping[str, tuple[Step, ...]] = {
    "renew_vpn_cert": (Step("renew_vpn_cert", undo="revoke_vpn_cert"),),
    "reissue_vpn_access": (Step("reissue_vpn_access", undo="revoke_vpn_cert"),),
    "check_vpn_status": (),
    "reset_password": (Step("reset_password", undo="lock_account"),),
    "unlock_account": (Step("unlock_account", undo="lock_account"),),
    "install_software": (
        Step("assign_paid_license", undo=None, when="paid_license"),
        Step("install_software", undo="uninstall_software"),
    ),
    "view_permissions": (),
    "grant_permission": (Step("grant_permission", undo="revoke_permission"),),
    "extend_permission": (Step("extend_permission", undo="restore_permission_expiry"),),
}


# T24 P2: hành động CHỈ ĐỌC — PLAN rỗng hợp lệ duy nhất (không ghi, không `transaction_log`).
READ_ONLY_ACTIONS: frozenset[str] = frozenset({"check_vpn_status", "view_permissions"})


def plan_for(action: Action, plans: Mapping[str, tuple[Step, ...]] | None = None) -> tuple[Step, ...]:
    """T24 P2: các bước của `action` sau khi lọc `when`. `action.type` không có trong PLAN → KeyError (E9)."""
    steps = (PLAN if plans is None else plans)[action.type]
    paid = action.facts.get("license_paid") is not False  # thiếu fact → coi như CÓ phí (D-48)
    # V10 (soát 12/11, agent 12 M4): máy ĐÃ có phần mềm → không cấp license (bước cài trả `already_installed`, tin "đã có sẵn")
    paid = paid and action.facts.get("software_installed_on_device") is not True
    return tuple(s for s in steps if s.when == "always" or (s.when == "paid_license" and paid))


def step_args(tool: str, action: Action) -> dict[str, Any]:
    """Tham số bước ghi — CHỈ từ `Action` (P7): `user_id` = `requested_for`; định danh/tham số từ `params` (đã qua `sanitize_slots`
    + `PARAMS_BY_ACTION`). `extend_permission` không gửi mức quyền. Tool lạ → KeyError (E9)."""
    p = action.params
    user = {"user_id": action.requested_for}
    builders: dict[str, Any] = {
        "renew_vpn_cert": lambda: {**user, "device_id": p["device_id"]},
        "reissue_vpn_access": lambda: {**user, "device_id": p["device_id"]},
        "reset_password": lambda: {**user, "account_type": p["account_type"]},
        "unlock_account": lambda: {**user, "account_type": p["account_type"]},
        "assign_paid_license": lambda: {**user, "software_name": p["software_name"]},
        "install_software": lambda: {"device_id": p["device_id"], "software_name": p["software_name"]},
        "grant_permission": lambda: {**user, "resource_path": p["resource_path"], "level": p["permission_level"],
                                     "duration_days": p["duration_days"]},
        "extend_permission": lambda: {**user, "resource_path": p["resource_path"], "duration_days": p["duration_days"]},
    }  # fmt: skip
    return dict(builders[tool]())


def _same_id(sent: object, got: object) -> bool:
    return str(sent).strip().upper() == str(got).strip().upper()


def _same_path(sent: object, got: object) -> bool:
    return str(sent).strip().strip("/") == str(got).strip().strip("/")  # = chuẩn hoá đường dẫn của file server


def unexpected_result(tool: str, args: Mapping[str, Any], data: Any) -> str | None:
    """V9 (soát 12/11, D-90): hậu điều kiện của bước GHI chính đã trả 2xx hợp schema — định danh trả về phải đúng định danh đã gửi,
    cờ ngữ nghĩa phải nói "đã làm". Trả TÊN điều kiện hỏng (tập đóng, không chứa giá trị) hoặc None. Tool hoàn tác không kiểm ở đây
    (`_rollback` đi đường riêng). `data` None ở bước ghi = hỏng (`empty_result`)."""
    checks: dict[str, Any] = {
        "renew_vpn_cert": lambda d: ("device_mismatch" if not _same_id(args["device_id"], d.device_id)
                                     else "cert_not_valid" if d.status != "valid" else None),
        "reset_password": lambda d: ("user_mismatch" if d.user_id != args["user_id"]
                                     else "account_type_mismatch" if d.account_type != args["account_type"]
                                     else "not_delivered" if d.delivered_via not in ("email", "sms") else None),
        "unlock_account": lambda d: ("user_mismatch" if d.user_id != args["user_id"]
                                     else "account_type_mismatch" if d.account_type != args["account_type"]
                                     else "still_locked" if d.locked is not False else None),
        "assign_paid_license": lambda d: "user_mismatch" if d.user_id != args["user_id"] else None,
        "install_software": lambda d: "device_mismatch" if not _same_id(args["device_id"], d.device_id) else None,
        "grant_permission": lambda d: ("path_mismatch" if not _same_path(args["resource_path"], d.path)
                                       else "permission_not_active" if d.status != "active"
                                       else "level_mismatch" if d.level != args["level"] else None),
        "extend_permission": lambda d: ("path_mismatch" if not _same_path(args["resource_path"], d.path)
                                        else "permission_not_active" if d.status != "active" else None),
    }  # fmt: skip
    checks["reissue_vpn_access"] = checks["renew_vpn_cert"]
    check = checks.get(tool)
    if check is None:
        return None
    if data is None:
        return "empty_result"
    return check(data)  # type: ignore[no-any-return]


def undo_args(undo: str, action: Action, result: Any) -> dict[str, Any]:
    """Tham số hoàn tác — từ `Action` + kết quả bước được hoàn tác (`tools.models`): `revoke_vpn_cert(user_id, serial)`,
    `lock_account(user_id, account_type, reason="admin")`, `uninstall_software(device_id, software_name)`,
    `revoke_permission(user_id, resource_path)`, `restore_permission_expiry(user_id, resource_path, expires_at=previous_expires_at)`."""
    p = action.params
    user = {"user_id": action.requested_for}
    builders: dict[str, Any] = {
        "revoke_vpn_cert": lambda: {**user, "serial": result.serial},
        "lock_account": lambda: {**user, "account_type": p["account_type"], "reason": "admin"},
        "uninstall_software": lambda: {"device_id": p["device_id"], "software_name": p["software_name"]},
        "revoke_permission": lambda: {**user, "resource_path": p["resource_path"]},
        "restore_permission_expiry": lambda: {**user, "resource_path": p["resource_path"],
                                              "expires_at": result.previous_expires_at},
    }  # fmt: skip
    return dict(builders[undo]())


def check_plans(
    metadata: Mapping[str, Mapping[str, ActionMeta]],
    enabled_intents: Iterable[str],
    *,
    plans: Mapping[str, tuple[Step, ...]] | None = None,
    specs: Mapping[str, ToolSpec] = REGISTRY,
) -> None:
    plans = PLAN if plans is None else plans  # đọc lúc gọi (test thay `PLAN` bằng monkeypatch)
    for intent in sorted(set(enabled_intents)):
        for action_type, meta in sorted(metadata.get(intent, {}).items()):
            if action_type not in plans:
                raise RuntimeError(f"PLAN thiếu action_type {action_type!r} (intent {intent!r}) — từ chối khởi động")
            if action_type not in RESULT_ACTIONS:  # soát S12 NGHI-6c: không để ghi xong rồi mới E9 vì thiếu mẫu tin B18
                raise RuntimeError(f"thiếu mẫu tin kết quả B18 cho {action_type!r} (domain/messages.py) — từ chối khởi động")
            steps = plans[action_type]
            if not steps:  # T24 P2: PLAN rỗng chỉ cho hành động chỉ đọc
                if action_type not in READ_ONLY_ACTIONS:
                    raise RuntimeError(f"PLAN[{action_type}] rỗng nhưng không phải hành động chỉ đọc — từ chối khởi động")
                continue
            if action_type in READ_ONLY_ACTIONS:
                raise RuntimeError(f"PLAN[{action_type}]: hành động chỉ đọc không được có bước ghi")
            for step in steps:
                spec = specs.get(step.tool)
                if spec is None or spec.kind != "write":
                    raise RuntimeError(f"PLAN[{action_type}]: {step.tool!r} không phải tool ghi đã khai báo")
                if step.undo != spec.undo_tool:
                    raise RuntimeError(f"PLAN[{action_type}]: undo {step.undo!r} ≠ undo_tool {spec.undo_tool!r} của {step.tool}")
            undoable = [s for s in steps if s.undo is not None]
            if meta.reversibility == "none" and undoable:
                raise RuntimeError(f"PLAN[{action_type}]: metadata reversibility none nhưng bước {undoable[0].tool} có undo")
            if meta.reversible and not undoable:
                raise RuntimeError(f"PLAN[{action_type}]: metadata reversible nhưng không bước nào hoàn tác được")
