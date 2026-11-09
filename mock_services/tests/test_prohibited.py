"""Q5 (ĐP 09/11) — danh sách phần mềm bị cấm do HỆ THỐNG NGOÀI giữ (G-01: fact chỉ từ tool). Viết TRƯỚC code (DỪNG 1).

`seed.json` mục `prohibited_software`: `names` (slug + tên hiển thị + alias, tra như danh mục) và `keywords` (từ khoá cấm trong tên —
so khớp chuỗi con trên tên đã chuẩn hoá `software.normalize`). `GET /software/catalog/{tên}`:
- trong danh mục → như cũ + `prohibited: false`;
- ngoài danh mục, khớp danh sách/từ khoá cấm → 200 `{in_catalog: false, prohibited: true}`, thuộc tính danh mục = null;
- ngoài danh mục, không cấm → 404 như cũ.
Seed bị TỪ CHỐI khi tên cấm trùng tên tra cứu của danh mục, hoặc từ khoá cấm là chuỗi con của slug/tên hiển thị/alias nào trong danh
mục (tránh chặn nhầm phần mềm đang được phép).
"""

import json
from typing import Any

import pytest
from app.seed_model import SeedData
from app.software import normalize
from app.state import SEED_PATH, load_seed
from fastapi.testclient import TestClient
from pydantic import ValidationError

CATALOG_KEYS = ("license_type", "paid", "version", "requires_approval", "requires_local_admin")


def _raw() -> dict[str, Any]:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _catalog_lookup_keys() -> set[str]:
    seed = load_seed()
    return {k for c in seed.catalog for k in (c.name, normalize(c.display_name), *map(normalize, c.aliases))}


# ---- seed -------------------------------------------------------------------------------------------------------------------


def test_seed_has_prohibited_names_and_specific_keywords() -> None:
    p = load_seed().prohibited_software
    names = {n.name for n in p.names}
    assert {"utorrent", "bittorrent", "qbittorrent", "kmspico", "kmsauto"} <= names  # kmspico, kmsauto: ĐP 09/11 10:05
    assert {"crack", "keygen", "torrent"} <= set(p.keywords)
    assert "patch" not in p.keywords  # từ chung đứng một mình — chặn nhầm (ĐP)


def test_keywords_never_match_any_catalog_name_or_alias() -> None:
    """Không chặn nhầm: không từ khoá cấm nào là chuỗi con của slug / tên hiển thị / alias đã chuẩn hoá của danh mục hiện có."""
    p = load_seed().prohibited_software
    keys = _catalog_lookup_keys()
    hits = sorted((kw, k) for kw in p.keywords for k in keys if normalize(kw) in k)
    assert hits == []
    names = {k for n in p.names for k in (n.name, normalize(n.display_name), *map(normalize, n.aliases))}
    assert not names & keys


@pytest.mark.parametrize(("where", "value"), [("keywords", "zoom"), ("keywords", "office"), ("names", "7zip")])
def test_seed_rejects_overlap_with_catalog(where: str, value: str) -> None:
    raw = _raw()
    if where == "keywords":
        raw["prohibited_software"]["keywords"].append(value)
    else:
        raw["prohibited_software"]["names"].append({"name": value, "display_name": value, "aliases": []})
    with pytest.raises(ValidationError):
        SeedData.model_validate(raw)


def test_seed_requires_prohibited_section() -> None:
    raw = _raw()
    del raw["prohibited_software"]
    with pytest.raises(ValidationError):
        SeedData.model_validate(raw)


@pytest.mark.parametrize("bad", ["", "  ", "Crack"])
def test_seed_rejects_bad_keyword(bad: str) -> None:
    """Từ khoá rỗng / chưa chuẩn hoá (chữ hoa) → seed hỏng (so khớp trên tên đã chuẩn hoá)."""
    raw = _raw()
    raw["prohibited_software"]["keywords"].append(bad)
    with pytest.raises(ValidationError):
        SeedData.model_validate(raw)


# ---- endpoint ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "slug"),
    [("utorrent", "utorrent"), ("uTorrent", "utorrent"), ("BitTorrent", "bittorrent"), ("qBittorrent", "qbittorrent"),
     ("KMSpico", "kmspico"), ("kms pico", "kmspico"), ("KMSAuto Net", "kmsauto"), ("kms auto", "kmsauto")],
)  # fmt: skip
def test_catalog_prohibited_by_list(client: TestClient, agent: dict[str, str], name: str, slug: str) -> None:
    r = client.get(f"/software/catalog/{name}", headers=agent)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["name"], body["in_catalog"], body["prohibited"]) == (slug, False, True)
    assert all(body[k] is None for k in CATALOG_KEYS), body


@pytest.mark.parametrize("name", ["Windows crack", "windows-crack", "keygen office", "Office 2024 keygen", "torrent client"])
def test_catalog_prohibited_by_keyword(client: TestClient, agent: dict[str, str], name: str) -> None:
    r = client.get(f"/software/catalog/{name}", headers=agent)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["name"], body["in_catalog"], body["prohibited"]) == (normalize(name), False, True)
    assert all(body[k] is None for k in CATALOG_KEYS), body


@pytest.mark.parametrize("name", ["photoshop", "Photoshop", "gimp", "Zoom Workplace Pro", "patch"])
def test_unknown_not_prohibited_still_404(client: TestClient, agent: dict[str, str], name: str) -> None:
    assert client.get(f"/software/catalog/{name}", headers=agent).status_code == 404


def test_in_catalog_unchanged_plus_prohibited_false(client: TestClient, agent: dict[str, str]) -> None:
    """Mọi phần mềm trong danh mục: đúng khoá/giá trị như trước Q5 + `prohibited: false`."""
    for c in load_seed().catalog:
        body = client.get(f"/software/catalog/{c.display_name}", headers=agent).json()
        assert body == {
            "name": c.name, "display_name": c.display_name, "in_catalog": True, "prohibited": False,
            "license_type": c.license_type, "paid": c.license_type == "paid", "version": c.version,
            "requires_approval": c.requires_approval, "requires_local_admin": c.requires_local_admin,
        }, c.name  # fmt: skip


def test_prohibited_has_no_license_and_cannot_install(
    client: TestClient, agent: dict[str, str], executor: dict[str, str]
) -> None:  # fmt: skip
    """Phòng thủ nhiều lớp: tên cấm không có license, tool ghi cài → 404 (không có trong danh mục)."""
    for name in ("utorrent", "Windows crack"):
        assert client.get(f"/software/licenses/{name}", headers=agent).status_code == 404
        r = client.post("/software/installed/LAP-0342/install", headers=executor, json={"software_name": name})
        assert r.status_code == 404, r.text
