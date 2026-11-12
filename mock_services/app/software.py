"""Mock danh mục phần mềm: danh mục, license, phần mềm đã cài; ghi: cài, gỡ, cấp license trả phí
(P5 mục 7)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.ad import get_user, mock_state
from app.security import require_read, require_write
from app.seed_model import compact_key as compact
from app.state import CatalogEntry, Installed, MockState

router = APIRouter(prefix="/software")


def normalize(name: str) -> str:
    """"Zoom", " zoom " → "zoom"; "Adobe Acrobat Pro" → "adobe-acrobat-pro"."""
    return "-".join(name.strip().lower().split())


def find_entry(state: MockState, name: str) -> CatalogEntry | None:
    """Tra theo slug (`zoom`) trước, rồi theo tên hiển thị (`Zoom Workplace`, KB gọi phần mềm bằng tên này) hoặc alias.
    Seed đảm bảo slug / tên hiển thị / alias không trùng giữa các phần mềm (SeedData._references)."""
    key = normalize(name)
    entry = state.catalog.get(key)
    if entry is not None:
        return entry
    return next((e for e in state.catalog.values()
                 if key in {normalize(e.display_name), *map(normalize, e.aliases)}), None)  # fmt: skip


def prohibited_match(state: MockState, name: str) -> tuple[str, str] | None:
    """Q5: (slug, tên hiển thị) khi tên NGOÀI danh mục thuộc danh sách cấm (slug/tên/alias) hoặc chứa một từ khoá cấm; không thì None.
    Từ khoá khớp → slug = tên hiển thị = tên đã chuẩn hoá. Seed bảo đảm danh sách cấm không chạm danh mục (`SeedData._references`)."""
    key = normalize(name)
    if (hit := state.prohibited.names.get(key)) is not None:
        return hit
    short = compact(name)
    if (hit := state.prohibited.compact_names.get(short)) is not None:  # K4: "KMS_Pico", "kms-auto.net"
        return hit
    if any(compact(kw) in short for kw in state.prohibited.keywords):  # K4: chuỗi con trên dạng rút gọn ("kmspico.exe", "KMSAuto Lite")
        return key, key
    return None


def catalog_entry(state: MockState, name: str) -> CatalogEntry:
    entry = find_entry(state, name)
    if entry is None:
        raise HTTPException(404, "not_found")
    return entry


def holds_license(state: MockState, software: str, user_id: str) -> bool:
    pool = state.licenses.get(software)
    return pool is not None and any(a["user_id"] == user_id for a in pool.assignments)


def release_license(state: MockState, software: str, user_id: str) -> bool:
    """Trả license `software` của `user_id` về kho; False khi người này không giữ license nào."""
    pool = state.licenses.get(software)
    if pool is None:
        return False
    kept = [a for a in pool.assignments if a["user_id"] != user_id]
    if len(kept) == len(pool.assignments):
        return False
    pool.assignments = kept
    pool.used = max(0, pool.used - 1)
    return True


def require_device(state: MockState, device_id: str) -> None:
    if device_id not in state.devices:
        raise HTTPException(404, "not_found")


@router.get("/catalog/{name}", dependencies=[Depends(require_read)])
async def catalog(name: str, request: Request) -> dict[str, Any]:
    """Trong danh mục → thuộc tính + `prohibited: false`. Ngoài danh mục: bị cấm (Q5) → 200 `in_catalog: false, prohibited: true`,
    thuộc tính danh mục null; không cấm → 404 như cũ (dữ liệu "không có", không phải lỗi)."""
    state = mock_state(request)
    e = find_entry(state, name)
    if e is None:
        hit = prohibited_match(state, name)
        if hit is None:
            raise HTTPException(404, "not_found")
        return {"name": hit[0], "display_name": hit[1], "in_catalog": False, "prohibited": True, "license_type": None,
                "paid": None, "version": None, "requires_approval": None, "requires_local_admin": None}  # fmt: skip
    return {
        "name": e.name,
        "display_name": e.display_name,
        "in_catalog": True,
        "prohibited": False,
        "license_type": e.license_type,
        "paid": e.license_type == "paid",
        "version": e.version,
        "requires_approval": e.requires_approval,
        "requires_local_admin": e.requires_local_admin,  # Phase 5 T22a P7
    }


@router.get("/licenses/{name}", dependencies=[Depends(require_read)])
async def licenses(name: str, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    e = catalog_entry(state, name)
    if e.license_type == "free":
        return {"name": e.name, "license_type": "free", "total": None, "used": None,
                "available": None, "assignments": []}  # fmt: skip
    pool = state.licenses.get(e.name)
    total, used = (pool.total, pool.used) if pool else (0, 0)
    # assignments: chỉ các license cấp qua mock này; phần `used` dựng sẵn từ seed không có tên người giữ.
    return {"name": e.name, "license_type": "paid", "total": total, "used": used,
            "available": total - used,
            "assignments": [dict(a) for a in pool.assignments] if pool else []}  # fmt: skip


@router.get("/installed/{device_id}", dependencies=[Depends(require_read)])
async def installed(device_id: str, request: Request) -> list[dict[str, Any]]:
    state = mock_state(request)
    require_device(state, device_id)
    rows = sorted((i for i in state.installed if i.device_id == device_id), key=lambda i: i.name)
    return [{"name": i.name, "version": i.version, "installed_at": i.installed_at} for i in rows]


# ---- Ghi (chỉ svc_executor) -------------------------------------------------------------------


class SoftwareBody(BaseModel):
    software_name: str = Field(min_length=1)


class AssignBody(BaseModel):
    user_id: str = Field(min_length=1)


@router.post("/installed/{device_id}/install", dependencies=[Depends(require_write)])
async def install(device_id: str, body: SoftwareBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    require_device(state, device_id)
    e = catalog_entry(state, body.software_name)
    existing = next((i for i in state.installed if i.device_id == device_id and i.name == e.name),
                    None)  # fmt: skip
    if existing is not None:
        # Cài lại phần mềm đã có: không cài mới, không đổi phiên bản, không đòi license (cũng an toàn khi retry).
        return {"device_id": device_id, "name": e.name, "version": existing.version,
                "installed_at": existing.installed_at, "already_installed": True}  # fmt: skip
    owner_id = state.devices[device_id].owner_id
    if e.license_type == "paid" and not holds_license(state, e.name, owner_id):
        raise HTTPException(409, "license_not_assigned")
    installed = Installed(device_id, e.name, e.version, state.now())
    state.installed.append(installed)
    return {"device_id": device_id, "name": e.name, "version": installed.version,
            "installed_at": installed.installed_at, "already_installed": False}  # fmt: skip


@router.post("/installed/{device_id}/uninstall", dependencies=[Depends(require_write)])
async def uninstall(device_id: str, body: SoftwareBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    require_device(state, device_id)
    e = find_entry(state, body.software_name)
    name = e.name if e is not None else normalize(body.software_name)
    before = len(state.installed)
    state.installed = [i for i in state.installed if not (i.device_id == device_id and i.name == name)]
    removed = before != len(state.installed)
    released = False
    if removed and e is not None and e.license_type == "paid":
        owner_id = state.devices[device_id].owner_id
        mine = {d.device_id for d in state.devices.values() if d.owner_id == owner_id}
        still_used = any(i.name == name and i.device_id in mine for i in state.installed)
        # license theo người, không theo máy: còn cài trên máy khác của người này thì chưa trả
        released = not still_used and release_license(state, name, owner_id)
    return {"device_id": device_id, "name": name, "removed": removed, "license_released": released}


@router.post("/licenses/{name}/assign", dependencies=[Depends(require_write)])
async def assign(name: str, body: AssignBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    get_user(state, body.user_id)
    e = catalog_entry(state, name)
    pool = state.licenses.get(e.name)
    if e.license_type != "paid" or pool is None:
        raise HTTPException(409, "not_a_paid_license")
    if holds_license(state, e.name, body.user_id):
        raise HTTPException(409, "already_assigned")
    if pool.used >= pool.total:
        raise HTTPException(409, "no_license_available")
    # Số thứ tự không lấy từ `used` đơn thuần: sau khi có license được trả về, `used` lùi lại và sẽ trùng id đang giữ.
    seq = max([pool.used, *(int(a["assignment_id"].rsplit("-", 1)[1]) for a in pool.assignments)]) + 1
    pool.used += 1
    assignment = {"assignment_id": f"LIC-{e.name}-{seq:03d}", "user_id": body.user_id}
    pool.assignments.append(assignment)
    return {"name": e.name, **assignment, "available": pool.total - pool.used}
