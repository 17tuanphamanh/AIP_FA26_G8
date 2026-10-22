"""Policy GIẢ + cô lập `CONFIG_DIR` cho test `/api/policy*` (F7).

Chép `config/` ra thư mục tạm rồi THAY `policy.json` bằng bản giả (mã luật R81–R92, `description` bắt đầu "[GIẢ]", ngưỡng
giả) — test không đọc, không phụ thuộc luật hay ngưỡng thật. `CONFIG_DIR` trỏ sang thư mục tạm và mọi `lru_cache` đọc config
bị xoá trước + sau test (kể cả cache mốc `updated_at` của `api/policy.py`), để app dựng trong test (`create_app` →
`get_policy()`) cũng đọc bản giả mà không rò sang test khác.

- `fake_policy()`           — dict MỚI mỗi lần gọi (test sửa tự do).
- `fake_config` (fixture)   — `Path` của `policy.json` trong thư mục tạm; dùng trước `auth_env()`.
- `reference_accepts(c)`    — bản gốc chạy CẢ FILE: `parse_policy` + `check_policy_config`; True = không ném. Dùng để so khớp
                              với kết quả của `/api/policy/validate` (T21).
"""

import copy
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from app.settings import (
    _policy_bytes,  # cache cần xoá giữa test (như `get_settings`)
    action_intents,
    check_policy_config,
    get_action_metadata,
    get_policy,
    get_settings,
    get_slots,
    parse_policy,
)

REAL_CONFIG = Path(__file__).resolve().parents[3] / "config"


def _cond(fact: str, op: str, value: Any = None) -> dict[str, Any]:
    c: dict[str, Any] = {"fact": fact, "op": op}
    if value is not None:
        c["value"] = value
    return c


def _rule(rid: str, type_: str, intent: str, action: str | list[str], *conds: dict[str, Any], any_: bool = False) -> dict[str, Any]:
    return {
        "id": rid, "type": type_, "intent": intent, "action": action,
        "conditions": {"any" if any_ else "all": list(conds)},
        "description": f"[GIẢ] luật thử {rid}",
    }  # fmt: skip


def fake_policy() -> dict[str, Any]:
    """Policy giả hợp lệ với `config/slots.yaml` + `config/action_metadata.yaml` thật: 12 luật R81–R92, luật cuối (R92) thuộc
    intent `vpn`. Ngưỡng giả — KHÔNG phải ngưỡng thật."""
    not_other = _cond("ctx.target_is_other", "is_false")
    in_hours = _cond("time.within_business_hours", "is_true")
    reversible = _cond("action.reversible", "is_true")
    return {
        "constants": {
            "MAX_LOOPS": 4, "MAX_CLARIFICATION_TURNS": 2, "TOOL_RETRY": 1, "BACKOFF_BASE_SECONDS": 1,
            "MAX_AUTH_FAILURES": 5, "AUTH_FAILURE_WINDOW_MINUTES": 10, "SLA_MINUTES": 45,
            "THRESHOLD_LOW": 0.3, "THRESHOLD_HIGH": 0.7, "RETRIEVAL_THRESHOLD": 0.5, "TAU_INTENT": 0.5,
            "CLARIFY_TIMEOUT_HOURS": 12, "CONFIRM_TIMEOUT_HOURS": 36,
        },
        "business_hours": {"tz": "Asia/Ho_Chi_Minh", "weekdays": [1, 2, 3, 4, 5], "start": "09:00", "end": "17:00"},
        "m5": {"p_method": "self_report", "calibrator_version": None},
        "rules": [
            _rule("R81", "allow", "vpn", "check_vpn_status", reversible),
            _rule("R82", "allow", "vpn", "renew_vpn_cert", not_other, in_hours),
            _rule("R83", "approval_required", "vpn", "reissue_vpn_access", not_other),
            _rule("R84", "allow", "account", "unlock_account", not_other, reversible),
            _rule("R85", "approval_required", "account", ["reset_password", "unlock_account"], not_other),
            _rule("R86", "deny", "account", "reset_password", _cond("ctx.target_is_other", "is_true")),
            _rule("R87", "allow", "software", "install_software", not_other, in_hours),
            _rule("R88", "approval_required", "software", "install_software", _cond("requester.role", "eq", "l1")),
            _rule("R89", "allow", "access", "view_permissions", reversible),
            _rule("R90", "approval_required", "access", ["grant_permission", "extend_permission"], not_other, any_=True),
            _rule("R91", "deny", "access", "grant_permission", _cond("ctx.target_is_other", "is_true")),
            _rule("R92", "approval_required", "vpn", ["renew_vpn_cert", "reissue_vpn_access"], in_hours),
        ],
    }  # fmt: skip


def policy_bytes(content: dict[str, Any]) -> bytes:
    return (json.dumps(content, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def clear_config_caches() -> None:
    from app.api import policy as policy_api

    for cached in (get_settings, _policy_bytes, get_policy, get_slots, get_action_metadata, action_intents):
        cached.cache_clear()
    policy_api.loaded_at.cache_clear()


@pytest.fixture
def fake_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Trả đường dẫn `policy.json` giả trong thư mục tạm; `CONFIG_DIR` trỏ tới đó cho tới hết test."""
    config = tmp_path / "config"
    shutil.copytree(REAL_CONFIG, config)
    path = config / "policy.json"
    path.write_bytes(policy_bytes(fake_policy()))
    monkeypatch.setenv("CONFIG_DIR", str(config))
    clear_config_caches()
    yield path
    monkeypatch.undo()  # trả CONFIG_DIR trước khi xoá cache — test sau nạp lại từ config thật
    clear_config_caches()


def reference_accepts(content: dict[str, Any]) -> bool:
    """Kiểm GỐC chạy cả file (không tách từng luật): True ⇔ `parse_policy` rồi `check_policy_config` đều không ném."""
    try:
        policy = parse_policy(json.dumps(content).encode("utf-8"))
        check_policy_config(policy, get_slots(), get_action_metadata())
    except Exception:  # noqa: BLE001 — mọi lỗi nạp/kiểm = từ chối
        return False
    return True


def variant(mutate: Any) -> dict[str, Any]:
    """Bản sao sâu của policy giả đã qua `mutate(dict) -> None`."""
    content = copy.deepcopy(fake_policy())
    mutate(content)
    return content
