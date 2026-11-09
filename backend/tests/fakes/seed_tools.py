"""AD (đọc) / phần mềm / file server giả cho test T20a (phase5 5.1.6, PLAN-T20a TQ-12) — khuôn `tests/fakes/vpn.py`: ĐỌC
`mock_services/seed.json` (không chép tay dữ liệu) và trả JSON đúng như mock thật:

- AD (`mock_services/app/ad.py`): `check_account_status` = `user_view` (có `is_service_account`, `disable_reason`, khối `account`
  theo `account_type`) — 404 khi người lạ HOẶC người đó không có tài khoản `account_type`; `check_privilege_level` (404 như trên);
  `check_lockout_history` (mới nhất trước); `check_manager_chain` (dừng khi hết sếp / vòng / sếp không có trong seed).
  Mặc định tài khoản như `seed_model.SeedAccount`: enabled true, locked false, lock_reason null, đặt mật khẩu 30 ngày trước,
  privilege `standard_user`.
- Phần mềm (`software.py`): tên chuẩn hoá `"-".join(name.strip().lower().split())`, tra theo slug rồi tên hiển thị / alias (như
  `find_entry` — Q5 D6: bản cũ chỉ tra slug nên "7-Zip" ra 404); catalog / license tên lạ → 404; Q5: catalog tên NGOÀI danh mục mà bị cấm
  (`prohibited_software`: slug/tên/alias của `names`, hoặc chứa từ khoá) → 200 `in_catalog=False, prohibited=True`, thuộc tính null
  (như `prohibited_match`); `installed` máy lạ (không có trong `devices`) → 404, sắp theo tên.
- File (`fileserver.py`): `permissions/{user}` 404 CHỈ khi người lạ, lọc `p.path == resource_path.strip().strip("/")`, trả cả dòng hết
  hạn (`status: expired`), sắp theo path; `resources/{path}` không có → 404.
- `check_device_registered` KHÔNG ở đây — lấy từ `tests/fakes/vpn.SeedVpn` (cùng seed).

Đếm lời gọi ở NƠI NHẬN: `calls[tool]` và `seen` = danh sách `(tool, args)` (args = input đã validate, `model_dump`). `fail(tool,
status, times)` → lỗi HTTP (500 → registry retry → E2). "Seed tạm" (chỉ trong bản giả, mock thật không cho): `add_permission`
(thêm dòng quyền — nhiều dòng cùng path, c4), `set_lock` (khoá với `lock_reason` lạ / null, i3).
"""

import copy
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from app.core.clock import Clock
from app.tools.models import (
    DeviceIn,
    ResourceIn,
    SoftwareIn,
    UserAccountIn,
    UserIn,
    UserResourceIn,
)

SEED = Path(__file__).resolve().parents[3] / "mock_services" / "seed.json"
ACCOUNT_DEFAULTS: dict[str, Any] = {
    "enabled": True, "locked": False, "lock_reason": None, "password_last_set_days_ago": 30,
    "privilege": "standard_user",
}  # fmt: skip  # = mock_services/app/seed_model.SeedAccount


def _status(code: int, path: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"http://mock.test{path}")
    return httpx.HTTPStatusError(str(code), request=request, response=httpx.Response(code, request=request))


def _iso(at: datetime) -> str:
    return at.isoformat()


def normalize_name(name: str) -> str:
    """= `mock_services/app/software.normalize`."""
    return "-".join(name.strip().lower().split())


def normalize_path(path: str) -> str:
    """= `mock_services/app/fileserver.normalize_path`."""
    return path.strip().strip("/")


class SeedTools:
    def __init__(self, clock: Clock, seed: Path = SEED) -> None:
        data = json.loads(seed.read_text(encoding="utf-8"))
        now = clock.now()
        self.clock = clock
        self.users: dict[str, dict[str, Any]] = {}
        for u in data["users"]:
            user = copy.deepcopy(u)
            user["hired_at"] = (now - timedelta(days=u["hired_days_ago"])).date().isoformat()
            user["accounts"] = {
                kind: {**ACCOUNT_DEFAULTS, **acc} for kind, acc in u["accounts"].items()
            }
            for acc in user["accounts"].values():
                acc["password_last_set"] = _iso(now - timedelta(days=acc.pop("password_last_set_days_ago")))
            user["lockouts"] = [
                {"account_type": x["account_type"], "at": now - timedelta(days=x["days_ago"]), "reason": x["reason"],
                 "source": x["source"]}
                for x in u.get("lockouts", [])
            ]  # fmt: skip
            self.users[u["user_id"]] = user
        self.devices = {d["device_id"] for d in data["devices"]}
        self.catalog = {c["name"]: dict(c) for c in data["catalog"]}
        self.catalog_keys = {k: c["name"] for c in data["catalog"]
                             for k in (c["name"], normalize_name(c["display_name"]), *map(normalize_name, c.get("aliases", [])))}  # fmt: skip
        banned = data["prohibited_software"]
        self.prohibited_names = {k: (n["name"], n["display_name"]) for n in banned["names"]
                                 for k in (n["name"], normalize_name(n["display_name"]), *map(normalize_name, n.get("aliases", [])))}  # fmt: skip
        self.prohibited_keywords: tuple[str, ...] = tuple(banned["keywords"])
        self.licenses = {p["name"]: dict(p) for p in data["licenses"]}
        self.installed = [
            {"device_id": i["device_id"], "name": i["name"], "version": i["version"],
             "installed_at": now - timedelta(days=i["installed_days_ago"])}
            for i in data["installed"]
        ]  # fmt: skip
        self.resources = {r["path"]: dict(r) for r in data["resources"]}
        self.permissions: list[dict[str, Any]] = []
        for p in data["permissions"]:
            self.add_permission(p["user_id"], p["path"], p["level"], granted_days_ago=p["granted_days_ago"],
                                expires_in_days=p["expires_in_days"])  # fmt: skip
        self.calls: Counter[str] = Counter()
        self.seen: list[tuple[str, dict[str, Any]]] = []
        self._fail: dict[str, list[int]] = {}

    # ---- cấu hình test -------------------------------------------------------------------------------------------------

    def fail(self, tool: str, status: int = 500, times: int = 99) -> "SeedTools":
        self._fail.setdefault(tool, []).extend([status] * times)
        return self

    def add_permission(
        self, user_id: str, path: str, level: str, *, granted_days_ago: int = 10, expires_in_days: int | None = None,
    ) -> None:  # fmt: skip
        """Seed tạm: thêm MỘT dòng quyền (mock thật giữ ≤ 1 dòng/(user, path) — bản giả cho phép nhiều để kiểm c4)."""
        now = self.clock.now()
        self.permissions.append({
            "user_id": user_id, "path": path, "level": level, "granted_at": now - timedelta(days=granted_days_ago),
            "expires_at": None if expires_in_days is None else now + timedelta(days=expires_in_days),
        })  # fmt: skip

    def set_lock(self, user_id: str, account_type: str, *, locked: bool, lock_reason: str | None) -> None:
        """Seed tạm: đặt trạng thái khoá tuỳ ý (kể cả `lock_reason` ngoài 3 giá trị của mock, hay khoá mà lý do null — i3)."""
        acc = self.users[user_id]["accounts"][account_type]
        acc["locked"], acc["lock_reason"] = locked, lock_reason

    def user_ids(self, tool: str | None = None) -> list[str]:
        """`user_id` trong các lời gọi đã nhận (theo tool nếu nêu) — kiểm "tra đúng người" (i7, c8)."""
        return [a["user_id"] for t, a in self.seen if (tool is None or t == tool) and "user_id" in a]

    # ---- nơi nhận ------------------------------------------------------------------------------------------------------

    async def _enter(self, tool: str, args: Any, path: str) -> None:
        self.calls[tool] += 1
        self.seen.append((tool, args.model_dump()))
        faults = self._fail.get(tool)
        if faults:
            raise _status(faults.pop(0), path)

    def _user(self, user_id: str, path: str) -> dict[str, Any]:
        user = self.users.get(user_id)
        if user is None:
            raise _status(404, path)
        return user

    def _account(self, user: dict[str, Any], account_type: str, path: str) -> dict[str, Any]:
        acc = user["accounts"].get(account_type)
        if acc is None:
            raise _status(404, path)
        return acc

    # ---- AD ------------------------------------------------------------------------------------------------------------

    async def check_account_status(self, a: UserAccountIn, timeout: float) -> object:
        path = f"/ad/users/{a.user_id}?account_type={a.account_type}"
        await self._enter("check_account_status", a, path)
        u = self._user(a.user_id, path)
        acc = self._account(u, a.account_type, path)
        return {
            "user_id": u["user_id"], "username": u["username"], "full_name": u["full_name"], "title": u["title"],
            "department": u["department"], "groups": list(u["groups"]), "manager_id": u["manager_id"],
            "employment_status": u["employment_status"], "hired_at": u["hired_at"],
            "is_privileged_account": u.get("is_privileged_account", False),
            "is_service_account": u["is_service_account"], "disable_reason": u["disable_reason"],
            "account": {"account_type": a.account_type, "enabled": acc["enabled"], "locked": acc["locked"],
                        "lock_reason": acc["lock_reason"], "password_last_set": acc["password_last_set"]},
        }  # fmt: skip

    async def check_privilege_level(self, a: UserAccountIn, timeout: float) -> object:
        path = f"/ad/users/{a.user_id}/privilege?account_type={a.account_type}"
        await self._enter("check_privilege_level", a, path)
        u = self._user(a.user_id, path)
        acc = self._account(u, a.account_type, path)
        return {"user_id": u["user_id"], "account_type": a.account_type, "level": acc["privilege"],
                "is_privileged_account": u.get("is_privileged_account", False)}  # fmt: skip

    async def check_lockout_history(self, a: UserIn, timeout: float) -> object:
        path = f"/ad/users/{a.user_id}/lockouts"
        await self._enter("check_lockout_history", a, path)
        u = self._user(a.user_id, path)
        rows = sorted(u["lockouts"], key=lambda x: x["at"], reverse=True)
        return [{"account_type": x["account_type"], "at": _iso(x["at"]), "reason": x["reason"], "source": x["source"]}
                for x in rows]  # fmt: skip

    async def check_manager_chain(self, a: UserIn, timeout: float) -> object:
        path = f"/ad/users/{a.user_id}/manager-chain"
        await self._enter("check_manager_chain", a, path)
        u = self._user(a.user_id, path)
        chain: list[dict[str, Any]] = []
        seen = {u["user_id"]}
        current = u["manager_id"]
        while current is not None and current not in seen and current in self.users:
            seen.add(current)
            boss = self.users[current]
            chain.append({"user_id": boss["user_id"], "full_name": boss["full_name"], "title": boss["title"],
                          "department": boss["department"], "employment_status": boss["employment_status"]})  # fmt: skip
            current = boss["manager_id"]
        return chain

    # ---- phần mềm --------------------------------------------------------------------------------------------------------

    def _catalog(self, name: str, path: str) -> dict[str, Any]:
        slug = self.catalog_keys.get(normalize_name(name))
        if slug is None:
            raise _status(404, path)
        return self.catalog[slug]

    def _prohibited(self, name: str) -> tuple[str, str] | None:
        key = normalize_name(name)
        if (hit := self.prohibited_names.get(key)) is not None:
            return hit
        return (key, key) if any(kw in key for kw in self.prohibited_keywords) else None

    async def check_catalog_entry(self, a: SoftwareIn, timeout: float) -> object:
        path = f"/software/catalog/{a.software_name}"
        await self._enter("check_catalog_entry", a, path)
        if normalize_name(a.software_name) not in self.catalog_keys and (hit := self._prohibited(a.software_name)) is not None:
            return {"name": hit[0], "display_name": hit[1], "in_catalog": False, "prohibited": True, "license_type": None,
                    "paid": None, "version": None, "requires_approval": None, "requires_local_admin": None}  # fmt: skip
        e = self._catalog(a.software_name, path)
        return {
            "name": e["name"], "display_name": e["display_name"], "in_catalog": True, "prohibited": False,
            "license_type": e["license_type"],
            "paid": e["license_type"] == "paid", "version": e["version"], "requires_approval": e["requires_approval"],
            "requires_local_admin": e["requires_local_admin"],
        }  # fmt: skip

    async def check_license_available(self, a: SoftwareIn, timeout: float) -> object:
        path = f"/software/licenses/{a.software_name}"
        await self._enter("check_license_available", a, path)
        e = self._catalog(a.software_name, path)
        if e["license_type"] == "free":
            return {"name": e["name"], "license_type": "free", "total": None, "used": None, "available": None}
        pool = self.licenses.get(e["name"])
        total, used = (pool["total"], pool["used"]) if pool else (0, 0)
        return {"name": e["name"], "license_type": "paid", "total": total, "used": used, "available": total - used}

    async def check_installed_list(self, a: DeviceIn, timeout: float) -> object:
        path = f"/software/installed/{a.device_id}"
        await self._enter("check_installed_list", a, path)
        if a.device_id not in self.devices:
            raise _status(404, path)
        rows = sorted((i for i in self.installed if i["device_id"] == a.device_id), key=lambda i: i["name"])
        return [{"name": i["name"], "version": i["version"], "installed_at": _iso(i["installed_at"])} for i in rows]

    # ---- file server -----------------------------------------------------------------------------------------------------

    async def check_current_permissions(self, a: UserResourceIn, timeout: float) -> object:
        path = f"/files/permissions/{a.user_id}"
        await self._enter("check_current_permissions", a, path)
        self._user(a.user_id, path)
        wanted = None if a.resource_path is None else normalize_path(a.resource_path)
        now = self.clock.now()
        rows = sorted((p for p in self.permissions if p["user_id"] == a.user_id
                       and (wanted is None or p["path"] == wanted)), key=lambda p: p["path"])  # fmt: skip
        return [
            {"path": p["path"], "level": p["level"], "granted_at": _iso(p["granted_at"]),
             "expires_at": None if p["expires_at"] is None else _iso(p["expires_at"]),
             "status": "expired" if p["expires_at"] is not None and p["expires_at"] <= now else "active"}
            for p in rows
        ]  # fmt: skip

    async def check_resource_sensitivity(self, a: ResourceIn, timeout: float) -> object:
        path = f"/files/resources/{a.resource_path}"
        await self._enter("check_resource_sensitivity", a, path)
        r = self.resources.get(normalize_path(a.resource_path))
        if r is None:
            raise _status(404, path)
        return {"path": r["path"], "sensitivity": r["sensitivity"], "owner_department": r["owner_department"],
                "owner_id": r["owner_id"]}  # fmt: skip

    def handlers(self) -> dict[str, Any]:
        return {
            "check_account_status": self.check_account_status,
            "check_privilege_level": self.check_privilege_level,
            "check_lockout_history": self.check_lockout_history,
            "check_manager_chain": self.check_manager_chain,
            "check_catalog_entry": self.check_catalog_entry,
            "check_license_available": self.check_license_available,
            "check_installed_list": self.check_installed_list,
            "check_current_permissions": self.check_current_permissions,
            "check_resource_sensitivity": self.check_resource_sensitivity,
        }
