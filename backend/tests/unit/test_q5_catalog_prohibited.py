"""Q5 (ĐP 09/11) — hợp đồng tool `check_catalog_entry` có `prohibited` (commit 1 "mock: danh sach phan mem bi cam"). Viết TRƯỚC code.

Mock (hệ thống ngoài) giữ danh sách cấm (`mock_services/seed.json` mục `prohibited_software`); `GET /software/catalog/{tên}`:
trong danh mục → như cũ + `prohibited: false`; ngoài danh mục mà cấm → 200 `{in_catalog: false, prohibited: true}`, thuộc tính danh mục
null; ngoài danh mục, không cấm → 404 như cũ. `CatalogEntry.prohibited` BẮT BUỘC (như `requires_local_admin`, P7): thiếu trường → lỗi
hợp đồng rõ, không âm thầm coi là "không cấm". Bản giả `tests/fakes/seed_tools.SeedTools` đọc cùng seed.json, cùng luật so khớp.
"""

from typing import Any

import pytest
from app.tools.models import CatalogEntry
from pydantic import ValidationError
from tests.unit._t20a import Env

IN_CATALOG = {"name": "zoom", "display_name": "Zoom Workplace", "in_catalog": True, "prohibited": False, "license_type": "free",
              "paid": False, "version": "6.2", "requires_approval": False, "requires_local_admin": False}  # fmt: skip
PROHIBITED = {"name": "utorrent", "display_name": "uTorrent", "in_catalog": False, "prohibited": True, "license_type": None,
              "paid": None, "version": None, "requires_approval": None, "requires_local_admin": None}  # fmt: skip
CATALOG_KEYS = ("license_type", "paid", "version", "requires_approval", "requires_local_admin")


def test_catalog_entry_prohibited_required_no_default() -> None:
    assert CatalogEntry.model_validate(IN_CATALOG).prohibited is False
    with pytest.raises(ValidationError):
        CatalogEntry.model_validate({k: v for k, v in IN_CATALOG.items() if k != "prohibited"})
    with pytest.raises(ValidationError):
        CatalogEntry.model_validate({k: v for k, v in PROHIBITED.items() if k != "prohibited"})


def test_catalog_entry_out_of_catalog_prohibited_shape() -> None:
    """Ngoài danh mục + cấm: không có thuộc tính danh mục; trong danh mục: đủ thuộc tính như cũ (thiếu một → lỗi hợp đồng)."""
    e = CatalogEntry.model_validate(PROHIBITED)
    assert (e.in_catalog, e.prohibited, e.paid, e.requires_local_admin) == (False, True, None, None)
    e2 = CatalogEntry.model_validate({k: v for k, v in PROHIBITED.items() if k not in CATALOG_KEYS})  # thiếu khoá = null
    assert (e2.in_catalog, e2.prohibited, e2.license_type) == (False, True, None)
    for key in CATALOG_KEYS:
        with pytest.raises(ValidationError):
            CatalogEntry.model_validate({**IN_CATALOG, key: None})


# ---- bản giả SeedTools (unit) cùng hành vi mock --------------------------------------------------------------------------------


async def _catalog(name: str) -> Any:
    [r] = await Env().run_calls([("check_catalog_entry", {"software_name": name})])
    assert r.error is None, r.error
    return r


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "slug"), [("utorrent", "utorrent"), ("windows-crack", "windows-crack"),
                                            ("keygen-office", "keygen-office"), ("qbittorrent", "qbittorrent")])  # fmt: skip
async def test_fake_prohibited(name: str, slug: str) -> None:
    r = await _catalog(name)
    assert isinstance(r.data, CatalogEntry) and not r.empty
    assert (r.data.name, r.data.in_catalog, r.data.prohibited) == (slug, False, True)


@pytest.mark.asyncio
async def test_fake_unknown_404_and_catalog_unchanged() -> None:
    r = await _catalog("photoshop")
    assert (r.data, r.empty) == (None, True)
    z = await _catalog("zoom")
    assert isinstance(z.data, CatalogEntry)
    assert z.data.model_dump() == {**IN_CATALOG}
