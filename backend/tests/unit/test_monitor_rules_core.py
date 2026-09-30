"""M9-B0: khung luật thuần — đăng ký `@rule`, `RuleContext`, `hourly_median`, `spike`, luật không đọc đồng hồ.

Nguồn: file chia việc M9 mục 3 (hợp đồng), mục 6 (B0); kế hoạch chung M9 mục 6 (trung vị 7 ngày, ranh giới spike).
"""

import ast
import importlib.util
import inspect
import textwrap
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.domain.alerts import AlertDraft
from app.monitor import evaluator, rules
from app.monitor.rules import (
    REGISTRY,
    DuplicateRuleError,
    RuleContext,
    hourly_median,
    rule,
    spike,
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")  # sau khi A0 merge: dùng app.monitor.window.VN_TZ


@pytest.fixture(autouse=True)
def isolated_registry() -> Iterator[None]:
    """Test đăng ký luật giả không được làm bẩn sổ toàn cục (B1/B2 đăng ký luật thật vào đó)."""
    saved_rules, saved_loaders = dict(REGISTRY), dict(evaluator.LOADERS)
    REGISTRY.clear()
    evaluator.LOADERS.clear()
    yield
    REGISTRY.clear()
    REGISTRY.update(saved_rules)
    evaluator.LOADERS.clear()
    evaluator.LOADERS.update(saved_loaders)


# ---- đăng ký luật -------------------------------------------------------------------------------


def test_duplicate_rule_id_fails_at_import(tmp_path: Path) -> None:
    """Hai luật cùng id ghi chung khoá chống trùng → cảnh báo của luật này che luật kia; phải lỗi LÚC IMPORT."""
    src = textwrap.dedent(
        """
        from app.monitor.rules import rule

        @rule("dup_import", "minute")
        def first(data, ctx):
            return []

        @rule("dup_import", "hourly")
        def second(data, ctx):
            return []
        """
    )
    path = tmp_path / "dup_rules_mod.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("dup_rules_mod", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(DuplicateRuleError):
        spec.loader.exec_module(module)


def _noop(data: Any, ctx: RuleContext) -> list[AlertDraft]:
    return []


def test_rule_rejects_bad_every_empty_id_async_fn() -> None:
    with pytest.raises(ValueError):
        rule("x", "yearly")(_noop)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        rule("", "minute")(_noop)

    async def io_rule(data: Any, ctx: RuleContext) -> list[AlertDraft]:
        return []

    with pytest.raises(TypeError):
        rule("async_rule", "minute")(io_rule)  # type: ignore[type-var]
    assert REGISTRY == {}  # không luật nào lọt vào sổ


def test_rule_returns_function_unchanged() -> None:
    fn = rule("keep_fn", "daily")(_noop)
    assert fn is _noop
    assert REGISTRY["keep_fn"].every == "daily"
    assert REGISTRY["keep_fn"].fn is _noop


def test_rule_context_requires_aware_now() -> None:
    with pytest.raises(ValueError):
        RuleContext(now=datetime(2026, 9, 30, 8, 0), tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)  # noqa: DTZ001 — cố ý naive
    ctx = RuleContext(now=datetime(2026, 9, 30, 8, 0, tzinfo=UTC), tz=VN_TZ, cap_usd=38.0, warn_ratio=0.8)
    assert ctx.now.tzinfo is not None


# ---- trung vị 168 giờ --------------------------------------------------------------------------


def test_hourly_median_empty_hours_count_as_zero() -> None:
    """Chỉ truyền giờ CÓ ca (SQL GROUP BY bỏ giờ trống); giờ trống phải được tính là 0."""
    assert hourly_median([2] * 84) == 1.0  # 84 số 2 + 84 số 0 → (0 + 2) / 2
    assert hourly_median([2] * 85) == 2.0  # 85 số 2 + 83 số 0 → phần tử 84, 85 đều là 2
    assert hourly_median([5, 7, 9]) == 0.0  # 3 giờ có ca, 165 giờ trống
    assert hourly_median([]) == 0.0


def test_hourly_median_dense_168_same_result() -> None:
    sparse = [2] * 84
    dense = [2] * 84 + [0] * 84
    assert hourly_median(dense) == hourly_median(sparse) == 1.0


def test_hourly_median_rejects_over_168_or_negative() -> None:
    with pytest.raises(ValueError):
        hourly_median([1] * 169)
    with pytest.raises(ValueError):
        hourly_median([1, -1])


# ---- spike -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "median", "expected"),
    [
        (6, 2.0, False),  # đúng bằng ngưỡng 3 × 2 → không báo
        (7, 2.0, True),  # hơn 1 → báo
        (2, 0.0, False),  # dưới tối thiểu 3 (dù > 3 × 0) → không báo
        (3, 0.0, True),  # đúng tối thiểu, > 3 × 0 → báo
        (3, 1.0, False),  # bằng ngưỡng 3 × 1
        (4, 1.0, True),
    ],
)
def test_spike_boundaries(count: int, median: float, expected: bool) -> None:
    assert spike(count, median) is expected


# ---- hàm luật không I/O, không đọc đồng hồ ------------------------------------------------------

_CLOCK_ATTRS = {"now", "utcnow", "today", "time", "monotonic", "perf_counter"}


@pytest.mark.parametrize("module", [rules, evaluator])
def test_rule_functions_never_read_clock(module: Any) -> None:
    """Mốc thời gian duy nhất là `ctx.now` (Clock của app): chạy lại phải ra đúng khoá cũ."""
    tree = ast.parse(inspect.getsource(module))
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
    assert len(funcs) >= 3  # quét không rỗng
    clock_calls = [
        c.lineno for c in ast.walk(tree)
        if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr in _CLOCK_ATTRS
    ]  # fmt: skip
    assert clock_calls == []
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert "time" not in imported


def test_rules_module_has_no_io_imports() -> None:
    tree = ast.parse(inspect.getsource(rules))
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported  # quét không rỗng
    banned = ("sqlalchemy", "app.db", "httpx", "asyncio")
    assert [m for m in imported if m.startswith(banned)] == []
