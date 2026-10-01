"""M9 A1 — phần thuần của `queries/business.py` (trọng số N3, hợp đồng mục 3, cửa sổ) + migration 0008 (tĩnh)."""

import dataclasses
import importlib.util
import inspect
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.monitor.metrics import N3_SENSITIVITY, N3_WEIGHTS
from app.monitor.queries import business
from app.monitor.queries.business import WeightedRate, escalation_rate_weighted, weigh

REPO = Path(__file__).resolve().parents[3]
MIGRATION = REPO / "backend" / "app" / "db" / "alembic" / "versions" / "0008_monitor_views.py"
FRM = datetime(2030, 1, 1, tzinfo=UTC)
TO = datetime(2030, 1, 2, tzinfo=UTC)
HAND = {"routine": (4, 1), "approval": (2, 1), "sensitive": (2, 2)}  # rate 0,25 / 0,5 / 1,0


def load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m9_0008_monitor_views", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_weigh_three_groups_hand_computed() -> None:
    assert weigh(HAND, N3_WEIGHTS) == pytest.approx(0.7 * 0.25 + 0.2 * 0.5 + 0.1 * 1.0)  # 0,375
    assert weigh(HAND, N3_SENSITIVITY["60/30/10"]) == pytest.approx(0.40)
    assert weigh(HAND, N3_SENSITIVITY["80/15/5"]) == pytest.approx(0.325)


def test_weigh_only_routine_renormalized() -> None:
    # (a) Q-M9-A1-3: chỉ có nhóm routine → weighted = rate routine, không bị kéo xuống 0,7 × 0,25
    only_routine = {"routine": (4, 1), "approval": (0, 0), "sensitive": (0, 0)}
    for weights in (N3_WEIGHTS, *N3_SENSITIVITY.values()):
        assert weigh(only_routine, weights) == pytest.approx(0.25)


def test_weigh_two_groups_renormalized() -> None:
    counts = {"routine": (2, 0), "sensitive": (1, 1)}  # thiếu khóa approval = 0 lá
    assert weigh(counts, N3_WEIGHTS) == pytest.approx((0.7 * 0 + 0.1 * 1.0) / 0.8)


def test_weigh_no_leaves_none() -> None:
    assert weigh({}, N3_WEIGHTS) is None
    assert weigh({"routine": (0, 0), "approval": (0, 0), "sensitive": (0, 0)}, N3_WEIGHTS) is None


def test_contract_signature() -> None:
    assert list(inspect.signature(escalation_rate_weighted).parameters) == ["conn", "frm", "to"]
    assert [f.name for f in dataclasses.fields(WeightedRate)] == ["raw", "weighted", "by_group", "sensitivity"]
    assert WeightedRate.__dataclass_params__.frozen  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("frm", "to"),
    [
        (datetime(2030, 1, 1), TO),  # noqa: DTZ001 — cố ý naive
        (FRM, datetime(2030, 1, 2)),  # noqa: DTZ001
        (TO, FRM),
        (FRM, FRM),
    ],
)
@pytest.mark.asyncio
async def test_naive_or_inverted_window_rejected(frm: datetime, to: datetime) -> None:
    conn: Any = None  # kiểm cửa sổ trước khi chạm DB
    with pytest.raises(ValueError):
        await business.business_metrics(conn, frm, to)


def test_own_keys_subset_of_business() -> None:
    assert business.OWN_KEYS == ("approval_expired_count", "decided_by_distribution", "top_matched_rules")
    assert set(business.OWN_KEYS) <= set(business.BUSINESS_METRICS)
    assert set(business.QUERIES) == set(business.BUSINESS_METRICS)


def test_alembic_single_head_is_0008() -> None:
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert script.get_heads() == ["0008"]
    assert script.get_revision("0008").down_revision == "0007"  # type: ignore[union-attr]


def test_migration_views_sql_static() -> None:
    m = load_migration()
    sql = dict(m.VIEWS)
    assert list(sql) == ["v_leaf", "v_decisions", "v_l2_queue"]
    for name, query in sql.items():
        assert "*" not in query, name  # cột tường minh
    assert "is_parent = false" in sql["v_leaf"]
    assert "a.step = 'B13/B14'" in sql["v_decisions"]
    assert "ix_tickets_leaf" not in MIGRATION.read_text(encoding="utf-8").split('"""')[2]  # không tạo lại chỉ mục
    assert m.DECISION_COLUMNS[0] == "log_id"
    assert "is_parent" not in m.LEAF_COLUMNS
