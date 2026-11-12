"""K4 soát 12/11 (agent 11 V24): biến thể tên của phần mềm cấm phải ra `prohibited: true` (→ R21 cấm), không 404 (→ R13 duyệt).

Trước sửa: "KMSpico Portable", "kmspico.exe", "kmspico 11", "KMSAuto Lite", "kms-auto-net" → 404 vì chỉ tra đúng tên/alias và từ khoá
chung (crack/keygen/torrent). Nay: (1) từ khoá thêm `kmspico`, `kmsauto`; (2) so khớp trên dạng RÚT GỌN của cả hai vế (chữ thường, bỏ
khoảng trắng, '-', '.', '_'). Seed vẫn bảo đảm từ khoá/tên cấm không chạm danh mục — kiểm cả trên dạng rút gọn.
"""

from typing import Any

import pytest
from app.seed_model import SeedData
from app.software import compact, normalize
from app.state import load_seed
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.test_prohibited import CATALOG_KEYS, _raw

VARIANTS = [
    "KMSpico Portable", "kmspico.exe", "kmspico 11", "KMSAuto Lite", "kms-auto-net", "KMS_Pico", "K.M.S.Pico",
    "kmsauto net 2024", "KMSPico-v10.2", "Kmspico_setup", "kms auto lite portable", "kmsAUTO.exe",
]  # fmt: skip
STILL_OK = ["Zoom", "7-Zip", "Microsoft Project", "Adobe Acrobat Pro"]


def test_compact_bo_dau_noi() -> None:
    assert compact("K.M.S_Pico - Portable") == "kmspicoportable"
    assert compact(" kms-auto.net ") == "kmsautonet"


def test_seed_co_tu_khoa_kms() -> None:
    assert {"kmspico", "kmsauto"} <= set(load_seed().prohibited_software.keywords)


@pytest.mark.parametrize("name", VARIANTS)
def test_bien_the_kms_bi_cam(client: TestClient, agent: dict[str, str], name: str) -> None:
    r = client.get(f"/software/catalog/{name}", headers=agent)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["in_catalog"], body["prohibited"]) == (False, True), body
    assert all(body[k] is None for k in CATALOG_KEYS), body


@pytest.mark.parametrize("name", STILL_OK)
def test_danh_muc_khong_doi(client: TestClient, agent: dict[str, str], name: str) -> None:
    body = client.get(f"/software/catalog/{name}", headers=agent).json()
    assert (body["in_catalog"], body["prohibited"]) == (True, False), body


@pytest.mark.parametrize("name", ["Windows crack", "keygen office"])
def test_tu_khoa_cu_van_tra_ten_chuan_hoa(client: TestClient, agent: dict[str, str], name: str) -> None:
    body = client.get(f"/software/catalog/{name}", headers=agent).json()
    assert (body["name"], body["prohibited"]) == (normalize(name), True)


def test_seed_tu_choi_tu_khoa_cham_danh_muc_dang_rut_gon() -> None:
    """Từ khoá chỉ chạm danh mục khi bỏ dấu nối ("7zip" ⊂ compact("7-Zip")) → vẫn phải bị từ chối."""
    raw: dict[str, Any] = _raw()
    raw["prohibited_software"]["keywords"].append("7zip")
    with pytest.raises(ValidationError):
        SeedData.model_validate(raw)
