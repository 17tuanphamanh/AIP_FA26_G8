"""D-60 P2 — `GET /api/dashboard/strategies` không cần DB (SQL thật: `tests/integration/test_dashboard_strategies_pg.py`).

- Hợp đồng BE chốt 26/10: đúng 17 khoá, đúng thứ tự, `kind`/`unit`; tỉ lệ `{num, den}`; giá trị `{value}` hoặc `{value, n}` (khoá kèm n);
  chiến lược 0 lá → null; `strategies` = RUNTIME_SELECTABLE; `source` real|sim (mặc định real), `all` → 422; `source` trong thân trùng
  `source` gửi; thiếu DSN monitor → 503 `monitor_unavailable`; quyền `dashboard:read:all` (L1, L2, nhân viên → 403).
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

import pytest
from app.api import dashboard_strategies as route
from app.monitor.queries.strategies import STRATEGY_METRICS, assemble, cells
from app.risk.strategy import RUNTIME_SELECTABLE
from tests.fakes.auth import EPOCH
from tests.unit.auth_helpers import AuthEnv, auth_env

PATH = "/api/dashboard/strategies"
KEYS = [
    "tickets", "auto_rate", "hitl_rate", "l2_rate", "confirmed_rate", "no_response_rate", "unresolved_rate", "l1_reject_rate",
    "quick_approve_rate", "system_time_p50", "system_time_p90", "human_wait_p50", "human_minutes_per_100", "e5_recheck_failed",
    "overrides", "rollbacks", "llm_cost_per_ticket",
]  # fmt: skip  — hợp đồng BE chốt 26/10, viết tay (không suy từ code)
WITH_N = {"system_time_p50", "system_time_p90", "human_wait_p50", "human_minutes_per_100", "llm_cost_per_ticket"}
UNITS = {"tickets": "count", "system_time_p50": "s", "system_time_p90": "s", "human_wait_p50": "min", "human_minutes_per_100": "min",
         "e5_recheck_failed": "count", "overrides": "count", "rollbacks": "count", "llm_cost_per_ticket": "usd"}  # fmt: skip
AGG = {
    "n": 10, "auto": 4, "hitl": 3, "l2": 2, "b19": 5, "confirmed": 3, "no_response": 1, "unresolved": 1, "approved": 2, "rejected": 1,
    "quick": 1, "sys_p50": 1500.0, "sys_p90": 4200.0, "sys_n": 8, "wait_p50": 90.0, "wait_n": 3, "view_s": 120.0, "recheck": 1,
    "overrides": 2, "rollbacks": 0, "cost": 0.05,
}  # fmt: skip


@pytest.fixture(autouse=True)
def _no_monitor_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MONITOR_DATABASE_URL", raising=False)


@pytest.fixture
def env() -> Iterator[AuthEnv]:
    with auth_env() as e:
        yield e


def _get(env: AuthEnv, token: str | None, **params: str) -> tuple[int, Any]:
    r = env.client.get(PATH, params=params, headers=env.bearer(token) if token else {})
    return r.status_code, r.json()


# ---- thuần ----------------------------------------------------------------------------------------------------------


def test_17_keys_order_kind_unit() -> None:
    assert [m.key for m in STRATEGY_METRICS] == KEYS
    for m in STRATEGY_METRICS:
        assert m.kind == ("value" if m.key in UNITS else "ratio"), m.key
        assert m.unit == UNITS.get(m.key), m.key
        assert m.with_n == (m.key in WITH_N), m.key


def test_cells_num_den_and_values() -> None:
    c = cells(AGG)
    assert list(c) == KEYS
    assert c["tickets"] == {"value": 10}
    assert (c["auto_rate"], c["hitl_rate"], c["l2_rate"]) == ({"num": 4, "den": 10}, {"num": 3, "den": 10}, {"num": 2, "den": 10})
    assert (c["confirmed_rate"], c["no_response_rate"], c["unresolved_rate"]) == (
        {"num": 3, "den": 5}, {"num": 1, "den": 5}, {"num": 1, "den": 5})
    assert (c["l1_reject_rate"], c["quick_approve_rate"]) == ({"num": 1, "den": 3}, {"num": 1, "den": 3})
    assert (c["system_time_p50"], c["system_time_p90"]) == ({"value": 1.5, "n": 8}, {"value": 4.2, "n": 8})
    assert c["human_wait_p50"] == {"value": 1.5, "n": 3}  # 90 giây → 1,5 phút
    assert c["human_minutes_per_100"] == {"value": pytest.approx(20.0), "n": 10}  # 100 × 120 s / 60 / 10 lá
    assert (c["e5_recheck_failed"], c["overrides"], c["rollbacks"]) == ({"value": 1}, {"value": 2}, {"value": 0})
    assert c["llm_cost_per_ticket"] == {"value": pytest.approx(0.005), "n": 10}


def test_cells_no_spans_no_human_decision_value_null_with_n_zero() -> None:
    c = cells({**AGG, "sys_p50": None, "sys_p90": None, "sys_n": 0, "wait_p50": None, "wait_n": 0, "approved": 0, "rejected": 0,
               "quick": 0, "b19": 0, "confirmed": 0, "no_response": 0, "unresolved": 0})  # fmt: skip
    assert c["system_time_p50"] == {"value": None, "n": 0}
    assert c["human_wait_p50"] == {"value": None, "n": 0}
    assert c["l1_reject_rate"] == {"num": 0, "den": 0} and c["confirmed_rate"] == {"num": 0, "den": 0}


def test_assemble_zero_leaf_strategy_is_null_everywhere() -> None:
    got = assemble(list(RUNTIME_SELECTABLE), {"hybrid": AGG}, {"hybrid": {"vpn": 7, "none": 3}})
    assert [spec.key for spec, _ in got.metrics] == KEYS
    for _, values in got.metrics:
        assert list(values) == ["rule_only", "hybrid", "hybrid_guarded"]
        assert values["rule_only"] is None and values["hybrid_guarded"] is None and values["hybrid"] is not None
    assert got.intent_mix == {"rule_only": {}, "hybrid": {"vpn": 7, "none": 3}, "hybrid_guarded": {}}
    assert got.unavailable == ()


# ---- HTTP -----------------------------------------------------------------------------------------------------------


def test_401_403(env: AuthEnv) -> None:
    assert _get(env, None) == (401, {"detail": "unauthorized"})
    for user in ("an.nv", "ha.lt", "long.nh"):
        assert _get(env, env.token(user)) == (403, {"detail": "forbidden"}), user


@pytest.mark.parametrize("value", ["all", "eval", "REAL", ""])
def test_source_outside_real_sim_422(env: AuthEnv, value: str) -> None:
    assert _get(env, env.manager_token(), source=value) == (422, {"error": "invalid_request", "fields": ["query.source"]})


def test_403_before_422(env: AuthEnv) -> None:
    assert _get(env, env.token("long.nh"), source="all") == (403, {"detail": "forbidden"})


@pytest.mark.parametrize("value", [None, "real", "sim"])
def test_valid_params_503_monitor_unavailable(env: AuthEnv, value: str | None) -> None:
    params = {} if value is None else {"source": value}
    assert _get(env, env.manager_token(), **params) == (503, {"detail": "monitor_unavailable"})


@pytest.mark.parametrize("value", ["real", "sim"])
def test_body_shape_exact(env: AuthEnv, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    seen: dict[str, Any] = {}

    @asynccontextmanager
    async def snapshot(_: Any) -> AsyncIterator[None]:
        yield None

    async def fake(conn: Any, frm: Any, to: Any, *, source: str, strategies: list[str]) -> Any:
        seen.update(source=source, strategies=strategies, frm=frm, to=to)
        return assemble(strategies, {"hybrid_guarded": AGG}, {"hybrid_guarded": {"account": 10}})

    monkeypatch.setattr(route, "read_snapshot", snapshot)
    monkeypatch.setattr(route, "strategy_comparison", fake)
    status, body = _get(env, env.manager_token(), source=value)
    assert status == 200, body
    assert seen["source"] == value and seen["strategies"] == ["rule_only", "hybrid", "hybrid_guarded"]
    assert list(body) == ["source", "from", "to", "strategies", "intent_mix", "metrics", "unavailable"]
    assert body["source"] == value
    assert (body["from"], body["to"]) == ((EPOCH - timedelta(days=7)).isoformat().replace("+00:00", "Z"),
                                          EPOCH.isoformat().replace("+00:00", "Z"))  # fmt: skip
    assert body["strategies"] == ["rule_only", "hybrid", "hybrid_guarded"]
    assert body["intent_mix"] == {"rule_only": {}, "hybrid": {}, "hybrid_guarded": {"account": 10}}
    assert body["unavailable"] == []
    assert [m["key"] for m in body["metrics"]] == KEYS
    for m in body["metrics"]:
        assert set(m) == ({"key", "kind", "values"} | ({"unit"} if m["key"] in UNITS else set())), m
        assert list(m["values"]) == ["rule_only", "hybrid", "hybrid_guarded"]
        assert m["values"]["rule_only"] is None and m["values"]["hybrid"] is None
    by = {m["key"]: m for m in body["metrics"]}
    assert by["tickets"] == {"key": "tickets", "kind": "value", "unit": "count",
                             "values": {"rule_only": None, "hybrid": None, "hybrid_guarded": {"value": 10}}}  # fmt: skip
    assert by["auto_rate"]["values"]["hybrid_guarded"] == {"num": 4, "den": 10}
    assert by["human_wait_p50"]["values"]["hybrid_guarded"] == {"value": 1.5, "n": 3}
    assert isinstance(by["overrides"]["values"]["hybrid_guarded"]["value"], int)  # đếm giữ kiểu số nguyên
