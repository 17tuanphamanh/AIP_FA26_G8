"""B1 (12/11): tab Nghiệp vụ và AI mặc định chỉ tính ticket thật (`source='real'`); `?source=all` gồm cả sim/eval.

- Lọc nằm trong `queries/common.py` (`LEAF_SOURCE` + `only_sources`); route đặt nguồn quanh `business_metrics`/`ai_metrics`.
- Không đặt `only_sources` (luật cảnh báo, tab So sánh) → đủ 3 nguồn = hành vi cũ. Chữ ký `(conn, frm, to)` không đổi.
- Không đổi định nghĩa chỉ số: chỉ thêm điều kiện nguồn vào câu đọc `v_leaf`.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from app.db.models import TICKET_SOURCES
from app.monitor.queries import ai, business
from app.monitor.queries.ai import AiMetrics
from app.monitor.queries.business import BusinessMetrics
from app.monitor.queries.common import (
    LEAF_SOURCE,
    current_sources,
    leaf_params,
    only_sources,
)
from tests.unit.auth_helpers import AuthEnv, auth_env

FRM = datetime(2030, 1, 1, tzinfo=UTC)
TO = datetime(2030, 1, 2, tzinfo=UTC)


class _Stop(Exception):
    pass


class _RecordConn:
    """Ghi câu SQL + tham số của lời gọi đầu tiên rồi dừng hàm (không cần dựng hàng trả về cho từng chỉ số)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, clause: Any, params: dict[str, Any]) -> Any:
        self.calls.append((clause.text, params))
        raise _Stop


def _queries() -> list[tuple[str, Any]]:
    out = [(f"business.{k}", fn) for k, fn in business.QUERIES.items() if fn is not None]
    out += [(f"ai.{k}", fn) for k, fn in ai.QUERIES.items() if fn is not None]
    out.append(("business.ratio_counts", business.ratio_counts))
    return out


async def _first_call(fn: Any) -> tuple[str, dict[str, Any]]:
    conn = _RecordConn()
    with pytest.raises(_Stop):
        await fn(conn, FRM, TO)
    return conn.calls[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "fn"), _queries(), ids=[n for n, _ in _queries()])
async def test_moi_cau_doc_v_leaf_loc_nguon(name: str, fn: Any) -> None:
    with only_sources(("real",)):
        sql, params = await _first_call(fn)
    assert "v_leaf" in sql, name
    assert LEAF_SOURCE in sql, name
    assert params["sources"] == ["real"], name


@pytest.mark.asyncio
@pytest.mark.parametrize(("name", "fn"), _queries(), ids=[n for n, _ in _queries()])
async def test_khong_dat_nguon_thi_du_ba_nguon(name: str, fn: Any) -> None:
    """Luật cảnh báo (vd luật 1 gọi `escalation_rate_weighted`) không đặt nguồn → như trước B1."""
    _, params = await _first_call(fn)
    assert params["sources"] == list(TICKET_SOURCES), name


@pytest.mark.asyncio
async def test_own_cung_loc_nguon() -> None:
    conn = _RecordConn()
    with only_sources(("real",)), pytest.raises(_Stop):
        await business.own_sample(conn, FRM, TO, approver_id="u-l1")  # type: ignore[arg-type]
    sql, params = conn.calls[0]
    assert LEAF_SOURCE in sql and params["sources"] == ["real"] and params["approver_id"] == "u-l1"


def test_only_sources_tra_lai_sau_khoi() -> None:
    assert current_sources() == TICKET_SOURCES
    with only_sources(("real",)):
        assert current_sources() == ("real",)
        assert leaf_params(FRM, TO) == {"frm": FRM, "to": TO, "sources": ["real"]}
    assert current_sources() == TICKET_SOURCES
    with pytest.raises(RuntimeError), only_sources(("real", "sim")):
        raise RuntimeError("lỗi giữa chừng")
    assert current_sources() == TICKET_SOURCES  # lỗi giữa chừng vẫn trả lại


@pytest.mark.parametrize("bad", [(), ("real", "khac"), ("REAL",)])
def test_only_sources_tu_choi_nguon_la(bad: tuple[str, ...]) -> None:
    with pytest.raises(ValueError), only_sources(bad):
        pass


# ---- API ------------------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _no_monitor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONITOR_DATABASE_URL", raising=False)


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env() as e:
        yield e


BUSINESS_VALUES: dict[str, Any] = {
    "automation_rate": None, "escalation_rate_raw": None, "escalation_rate_weighted": None, "deflection_rate": None,
    "approval_expired_count": 0, "decided_by_distribution": {}, "top_matched_rules": [], "override_count": 0,
    "e1_split": None, "e3_cases": None,
}  # fmt: skip


def _fake(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[str, ...]]]:
    """Thay snapshot + 2 hàm gom: ghi nguồn ĐANG đặt lúc route gọi truy vấn."""
    seen: list[tuple[str, tuple[str, ...]]] = []

    @asynccontextmanager
    async def snapshot(engines: Any) -> AsyncIterator[None]:
        yield None

    async def fake_business(conn: Any, frm: datetime, to: datetime, *, approver_id: str | None = None) -> BusinessMetrics:
        seen.append(("business", current_sources()))
        return BusinessMetrics(values=BUSINESS_VALUES, unavailable=())

    async def fake_ai(conn: Any, frm: datetime, to: datetime) -> AiMetrics:
        seen.append(("ai", current_sources()))
        return AiMetrics(values=dict.fromkeys(ai.AI_METRICS), unavailable=())

    monkeypatch.setattr("app.api.dashboard.read_snapshot", snapshot)
    monkeypatch.setattr("app.api.dashboard.business_metrics", fake_business)
    monkeypatch.setattr("app.api.dashboard.ai_metrics", fake_ai)
    return seen


@pytest.mark.parametrize("kind", ["business", "ai"])
def test_api_mac_dinh_chi_ticket_that(env: AuthEnv, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    seen = _fake(monkeypatch)
    r = env.client.get(f"/api/dashboard/{kind}", headers=env.bearer(env.manager_token()))
    assert r.status_code == 200, r.text
    assert seen == [(kind, ("real",))]
    assert r.json()["source"] == "real"
    assert current_sources() == TICKET_SOURCES  # route trả lại nguồn sau khi xong


@pytest.mark.parametrize("kind", ["business", "ai"])
def test_api_source_all_gom_sim_eval(env: AuthEnv, monkeypatch: pytest.MonkeyPatch, kind: str) -> None:
    seen = _fake(monkeypatch)
    r = env.client.get(f"/api/dashboard/{kind}", params={"source": "all"}, headers=env.bearer(env.manager_token()))
    assert r.status_code == 200, r.text
    assert seen == [(kind, TICKET_SOURCES)]
    assert r.json()["source"] == "all"


@pytest.mark.parametrize("bad", ["sim", "eval", "REAL", ""])
def test_api_source_la_422(env: AuthEnv, monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    seen = _fake(monkeypatch)
    r = env.client.get("/api/dashboard/business", params={"source": bad}, headers=env.bearer(env.manager_token()))
    assert r.status_code == 422 and seen == []
