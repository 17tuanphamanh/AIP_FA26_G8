"""O3 (soát 12/11, agent 10 V18 + agent 19): `/api/health` thêm `warnings` — danh sách MÃ CỐ ĐỊNH (không chữ tự do), CHỈ báo như `kb`,
`llm`, `monitor`: không bao giờ đổi mã 200/503 (mã do `checks` quyết như cũ).

- `llm_spend_cap_reached`: `llm == "spend_cap_reached"` (đã có probe).
- `mock_faults_active`: `GET {mock}/_admin/faults` khác rỗng — CHỈ khi `APP_ENV` là dev/test (mock admin chỉ có ở đó).
- `ml_models_missing`: `/health` của ml-service báo model nhóm (`injection`/`intent`) `"missing"` — ml-service vẫn 200 khi thiếu model
  nhóm nên `checks.ml` không thấy (B2 lặng lẽ chạy như shadow).
`worker_heartbeat_stale`: KHÔNG làm — heartbeat là file trong container worker, backend không đọc được (đề xuất, không thêm bảng).
Probe lỗi → `[]` (log tên lớp), không làm hỏng /api/health. Mã lạ từ probe bị lọc.
"""

from typing import Any

import httpx
import pytest
import respx
from app.main import _default_warnings_probe, create_app
from app.ml.startup import missing_models
from fastapi.testclient import TestClient
from tests.fakes.runtime import no_runtime
from tests.unit.test_health import _settings, broken, kb_missing, ok


def _get(checks: dict[str, Any], *, warnings: Any = None, llm: Any = None, **over: object) -> Any:
    app = create_app(_settings(**over), health_checks=checks, runtime=no_runtime, kb_probe=kb_missing)  # type: ignore[arg-type]
    if warnings is not None:
        app.state.warnings_probe = warnings
    if llm is not None:
        app.state.llm_probe = llm
    with TestClient(app) as client:
        return client.get("/api/health")


def _const(value: Any) -> Any:
    async def probe() -> Any:
        return value

    return probe


async def _boom() -> list[str]:
    raise httpx.ConnectError("mock chết")


def test_sach_thi_warnings_rong() -> None:
    r = _get({"db": ok}, warnings=_const([]))
    assert (r.status_code, r.json()["warnings"]) == (200, [])


def test_tran_chi_llm() -> None:
    r = _get({"db": ok}, warnings=_const([]), llm=_const("spend_cap_reached"))
    assert (r.status_code, r.json()["warnings"]) == (200, ["llm_spend_cap_reached"])


def test_ma_tu_probe_loc_ma_la_va_sap_xep() -> None:
    r = _get({"db": ok}, warnings=_const(["ml_models_missing", "chu tu do", "mock_faults_active", "mock_faults_active"]))
    assert r.json()["warnings"] == ["ml_models_missing", "mock_faults_active"]


def test_probe_loi_thi_rong_khong_hong_health() -> None:
    r = _get({"db": ok}, warnings=_boom)
    assert (r.status_code, r.json()["warnings"]) == (200, [])


def test_warnings_khong_doi_ma_503() -> None:
    r = _get({"db": broken}, warnings=_const(["mock_faults_active"]))
    assert r.status_code == 503 and r.json()["warnings"] == ["mock_faults_active"]


ML_OK = {"status": "ok", "models": {"embed": {}, "rerank": {}, "injection": {"model": "x", "version": "v1"}, "intent": {"model": "y", "version": "v2"}}}
ML_MISSING = {"status": "ok", "models": {"embed": {}, "rerank": {}, "injection": "missing", "intent": {"model": "y", "version": "v2"}}}


@pytest.mark.asyncio
@respx.mock
async def test_probe_mac_dinh_doc_mock_va_ml() -> None:
    settings = _settings(app_env="dev", mock_url="http://mock.test:8100", ml_service_url="http://ml.test:8200")
    faults = respx.get("http://mock.test:8100/_admin/faults").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    respx.get("http://ml.test:8200/health").mock(return_value=httpx.Response(200, json=ML_MISSING))
    assert sorted(await _default_warnings_probe(settings)()) == ["ml_models_missing", "mock_faults_active"]
    faults.mock(return_value=httpx.Response(200, json=[]))
    respx.get("http://ml.test:8200/health").mock(return_value=httpx.Response(200, json=ML_OK))
    assert await _default_warnings_probe(settings)() == []


@pytest.mark.asyncio
@respx.mock
async def test_probe_mac_dinh_ngoai_dev_khong_hoi_mock() -> None:
    settings = _settings(app_env="prod", mock_url="http://mock.test:8100", ml_service_url="http://ml.test:8200")
    faults = respx.get("http://mock.test:8100/_admin/faults").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    respx.get("http://ml.test:8200/health").mock(return_value=httpx.Response(200, json=ML_OK))
    assert await _default_warnings_probe(settings)() == []
    assert not faults.called


@pytest.mark.asyncio
@respx.mock
async def test_missing_models() -> None:
    respx.get("http://ml.test:8200/health").mock(return_value=httpx.Response(200, json=ML_MISSING))
    async with httpx.AsyncClient() as http:
        assert await missing_models(http, "http://ml.test:8200") == ["injection"]
    respx.get("http://ml.test:8200/health").mock(return_value=httpx.Response(503, json={"status": "loading"}))
    async with httpx.AsyncClient() as http:
        assert await missing_models(http, "http://ml.test:8200") is None  # không đọc được ≠ thiếu


def test_compose_tu_khoi_dong_lai() -> None:
    """O3 (agent 10): service lõi có `restart: unless-stopped` — ml-service/worker bị kill (OOM) không nằm luôn giữa buổi demo."""
    from pathlib import Path

    import yaml

    compose = yaml.safe_load((Path(__file__).resolve().parents[3] / "docker-compose.yml").read_text(encoding="utf-8"))
    for name in ("postgres", "qdrant", "backend", "worker", "mock", "ml-service"):
        assert compose["services"][name].get("restart") == "unless-stopped", name
