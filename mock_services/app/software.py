"""Mock danh mục phần mềm: danh mục, license, phần mềm đã cài; ghi: cài, gỡ, cấp license trả phí
(P5 mục 7)."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.ad import get_user, mock_state
from app.security import require_read, require_write
from app.state import CatalogEntry, Installed, MockState

router = APIRouter(prefix="/software")


def normalize(name: str) -> str:
    """"Zoom", " zoom " → "zoom"; "Adobe Acrobat Pro" → "adobe-acrobat-pro"."""
    return "-".join(name.strip().lower().split())


def catalog_entry(state: MockState, name: str) -> CatalogEntry:
    entry = state.catalog.get(normalize(name))
    if entry is None:
        raise HTTPException(404, "not_found")
    return entry


def require_device(state: MockState, device_id: str) -> None:
    if device_id not in state.devices:
        raise HTTPException(404, "not_found")


@router.get("/catalog/{name}", dependencies=[Depends(require_read)])
async def catalog(name: str, request: Request) -> dict[str, Any]:
    e = catalog_entry(mock_state(request), name)
    return {
        "name": e.name,
        "display_name": e.display_name,
        "in_catalog": True,
        "license_type": e.license_type,
        "paid": e.license_type == "paid",
        "version": e.version,
        "requires_approval": e.requires_approval,
    }


@router.get("/licenses/{name}", dependencies=[Depends(require_read)])
async def licenses(name: str, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    e = catalog_entry(state, name)
    if e.license_type == "free":
        return {"name": e.name, "license_type": "free", "total": None, "used": None,
                "available": None}  # fmt: skip
    pool = state.licenses.get(e.name)
    total, used = (pool.total, pool.used) if pool else (0, 0)
    return {"name": e.name, "license_type": "paid", "total": total, "used": used,
            "available": total - used}  # fmt: skip


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
    if existing is None:
        existing = Installed(device_id, e.name, e.version, state.now())
        state.installed.append(existing)
    return {"device_id": device_id, "name": e.name, "version": existing.version,
            "installed_at": existing.installed_at}  # fmt: skip


@router.post("/installed/{device_id}/uninstall", dependencies=[Depends(require_write)])
async def uninstall(device_id: str, body: SoftwareBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    require_device(state, device_id)
    name = normalize(body.software_name)
    before = len(state.installed)
    state.installed = [i for i in state.installed if not (i.device_id == device_id and i.name == name)]
    return {"device_id": device_id, "name": name, "removed": before != len(state.installed)}


@router.post("/licenses/{name}/assign", dependencies=[Depends(require_write)])
async def assign(name: str, body: AssignBody, request: Request) -> dict[str, Any]:
    state = mock_state(request)
    get_user(state, body.user_id)
    e = catalog_entry(state, name)
    pool = state.licenses.get(e.name)
    if e.license_type != "paid" or pool is None:
        raise HTTPException(409, "not_a_paid_license")
    if pool.used >= pool.total:
        raise HTTPException(409, "no_license_available")
    pool.used += 1
    assignment = {"assignment_id": f"LIC-{e.name}-{pool.used:03d}", "user_id": body.user_id}
    pool.assignments.append(assignment)
    return {"name": e.name, **assignment, "available": pool.total - pool.used}
