"""AD giả cho test người duyệt (Phase 4 chặng 4b) — ĐỌC `mock_services/seed.json` (không chép tay dữ liệu, khác
`tests/fakes/auth.seed_ad_users`) và trả JSON đúng như `GET /ad/users/{id}` của mock (`mock_services/app/ad.user_view`, tài khoản
`ad`). Ngày tương đối (`hired_days_ago`, `password_last_set_days_ago`) tính từ `now` lúc dựng.

- `seed_ad_records(now, ids)` → danh sách JSON (mặc định mọi người trong seed).
- `seed_ad(now, ids)` → `FakeAd` (registry THẬT qua `fake_directory`): 404 khi không có, `fail_ids` → HTTP 500 theo người,
  `calls_by` đếm theo người ở nơi nhận, `set_status` như `/_admin/users/{id}/status`.
- `ROSTER_CHAIN` = người trong `config/approvers.yaml` (vpn) + chuỗi quản lý của họ trong seed — harness gộp vào AD giả của test
  để B15 thật tìm được người duyệt.
"""

import json
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tests.fakes.identity import FakeAd

SEED = Path(__file__).resolve().parents[3] / "mock_services" / "seed.json"
ROSTER_CHAIN = ("l1_01", "l1_02", "it_mgr01", "l1_lead")


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def seed_ad_records(now: datetime, ids: Iterable[str] | None = None) -> list[dict[str, Any]]:
    users = json.loads(SEED.read_text(encoding="utf-8"))["users"]
    wanted = None if ids is None else set(ids)
    out: list[dict[str, Any]] = []
    for u in users:
        if wanted is not None and u["user_id"] not in wanted:
            continue
        acc = u["accounts"]["ad"]
        out.append({
            "user_id": u["user_id"], "username": u["username"], "full_name": u["full_name"], "title": u["title"],
            "department": u["department"], "groups": list(u["groups"]), "manager_id": u["manager_id"],
            "employment_status": u["employment_status"],
            "hired_at": (now - timedelta(days=u["hired_days_ago"])).date().isoformat(),
            "is_privileged_account": u.get("is_privileged_account", False),
            "account": {
                "account_type": "ad", "enabled": acc.get("enabled", True), "locked": acc.get("locked", False),
                "lock_reason": acc.get("lock_reason"),
                "password_last_set": _iso(now - timedelta(days=acc.get("password_last_set_days_ago", 30))),
            },
        })  # fmt: skip
    if wanted is not None and (missing := wanted - {r["user_id"] for r in out}):
        raise KeyError(f"seed.json không có {sorted(missing)}")
    return out


def seed_ad(now: datetime, ids: Iterable[str] | None = None) -> FakeAd:
    return FakeAd(*seed_ad_records(now, ids))
