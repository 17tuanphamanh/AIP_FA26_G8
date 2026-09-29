"""PLAN — "làm gì" cho từng `action_type` (B17 §3, phase3 11.4). Chỉ metadata: KHÔNG import adapter ghi (hợp đồng
import-linter 3) — node B17 và `graph/wiring` đọc được module này.

- `renew_vpn_cert` → 1 bước `renew_vpn_cert`, hoàn tác `revoke_vpn_cert(serial của bước cấp)`.
- `reissue_vpn_access` → 1 bước `reissue_vpn_access`, hoàn tác như trên.
- `check_vpn_status` → `()` (3-Q31: không ghi, không `transaction_log`).

`check_plans` (h23) — fail-closed lúc khởi động (`graph/wiring.open_runtime`, cả backend lẫn worker): mọi `action_type` của
intent đang bật trong `action_metadata.yaml` phải có PLAN; mỗi bước là tool GHI đã khai báo (`tools/specs.py`), `undo` đúng
`undo_tool` của tool đó; hành động `reversible` mà bước có tool hoàn tác được thì phải khai báo `undo`; có mẫu tin kết quả
B18 (`domain.messages.RESULT_ACTIONS`). Thiếu PLAN phải là lỗi
cấu hình khi khởi động, không phải E9 lúc chạy (B17 §13).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.domain.action import Action, ActionMeta
from app.domain.messages import RESULT_ACTIONS
from app.tools.specs import REGISTRY, ToolSpec


@dataclass(frozen=True)
class Step:
    tool: str  # tool ghi (kind=write, allowed_steps {"B17"})
    undo: str | None = None  # tool hoàn tác (cũng là tool ghi) — None khi không hoàn tác được


PLAN: Mapping[str, tuple[Step, ...]] = {
    "renew_vpn_cert": (Step("renew_vpn_cert", undo="revoke_vpn_cert"),),
    "reissue_vpn_access": (Step("reissue_vpn_access", undo="revoke_vpn_cert"),),
    "check_vpn_status": (),
}


def step_args(tool: str, action: Action) -> dict[str, Any]:
    """Tham số bước ghi — CHỈ từ `Action` (người hưởng lợi + định danh máy đã qua `sanitize_slots`). Tool lạ → KeyError (E9)."""
    builders = {
        "renew_vpn_cert": lambda a: {"user_id": a.requested_for, "device_id": a.params["device_id"]},
        "reissue_vpn_access": lambda a: {"user_id": a.requested_for, "device_id": a.params["device_id"]},
    }
    return builders[tool](action)


def undo_args(undo: str, action: Action, result: Any) -> dict[str, Any]:
    """Tham số hoàn tác: `revoke_vpn_cert(user_id, serial)` — serial lấy từ kết quả bước cấp (`tools.models.Cert`)."""
    builders = {"revoke_vpn_cert": lambda a, r: {"user_id": a.requested_for, "serial": r.serial}}
    return builders[undo](action, result)


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
            for step in plans[action_type]:
                spec = specs.get(step.tool)
                if spec is None or spec.kind != "write":
                    raise RuntimeError(f"PLAN[{action_type}]: {step.tool!r} không phải tool ghi đã khai báo")
                if step.undo != spec.undo_tool:
                    raise RuntimeError(f"PLAN[{action_type}]: undo {step.undo!r} ≠ undo_tool {spec.undo_tool!r} của {step.tool}")
                if meta.reversible != (spec.reversible in ("full", "partial")):
                    raise RuntimeError(f"PLAN[{action_type}]: reversible của metadata lệch tool {step.tool}")
