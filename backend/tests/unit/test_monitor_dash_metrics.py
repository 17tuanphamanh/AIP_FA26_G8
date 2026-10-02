"""M9 A1 — `metrics.py`: `METRIC_SOURCES` (chỉ khóa response, hai chiều), `PENDING_SOURCES` (Q-M9-A1-7), `is_pending`
(khóa lạ → KeyError), hằng E1 nguyên văn `reason_detail`, hằng N3."""

import pytest
from app.domain.exit_codes import REASON_DETAILS
from app.monitor.metrics import (
    E1_OTHER,
    E1_REASONS,
    METRIC_SOURCES,
    N3_SENSITIVITY,
    N3_WEIGHTS,
    PENDING_SOURCES,
    is_pending,
)
from app.monitor.queries.business import BUSINESS_METRICS

PENDING_RULE_SOURCES = {"override_count", "multi_intent", "b3_cascade", "tool_spans"}


def test_metric_sources_equal_response_keys_both_ways() -> None:
    assert len(BUSINESS_METRICS) == 10  # quét rỗng thì đỏ, không xanh giả
    assert set(METRIC_SOURCES) == set(BUSINESS_METRICS)


def test_pending_sources_exact() -> None:
    assert dict(PENDING_SOURCES) == dict.fromkeys(PENDING_RULE_SOURCES, "pending") | {"approval_view": "ready"}
    assert "policy_saved" not in PENDING_SOURCES  # luật 11 chạy truy vấn thật, không gọi is_pending


def test_is_pending_values() -> None:
    for key in PENDING_RULE_SOURCES:
        assert is_pending(key) is True, key
    assert is_pending("approval_view") is False
    for key in set(METRIC_SOURCES) - {"override_count"}:
        assert is_pending(key) is False, key


@pytest.mark.parametrize("key", ["policy_saved", "khong_co", "b3_llm_rate", ""])
def test_is_pending_unknown_key_raises(key: str) -> None:
    with pytest.raises(KeyError):
        is_pending(key)


def test_shared_keys_agree() -> None:
    shared = set(METRIC_SOURCES) & set(PENDING_SOURCES)
    assert shared == {"override_count"}
    for key in shared:
        assert METRIC_SOURCES[key].status == PENDING_SOURCES[key]


def test_pending_metric_has_reason() -> None:
    for key, source in METRIC_SOURCES.items():
        assert source.tables, key
        assert (source.status == "pending") == (source.pending_reason is not None), key
    override = METRIC_SOURCES["override_count"]
    assert (override.step, override.event) == ("OVERRIDE", "override_recorded")


def test_e1_reasons_verbatim_reason_detail() -> None:
    assert E1_REASONS == ("out_of_scope", "multi_intent_not_enabled", "intent_low_confidence", "intent_not_enabled")
    assert set(E1_REASONS) <= REASON_DETAILS
    assert "intent_out_of_scope" not in E1_REASONS  # tên event audit B4, không phải reason_detail
    assert E1_OTHER == "other" and E1_OTHER not in E1_REASONS


def test_n3_weights_constants() -> None:
    assert dict(N3_WEIGHTS) == {"routine": 0.7, "approval": 0.2, "sensitive": 0.1}
    assert {k: dict(v) for k, v in N3_SENSITIVITY.items()} == {
        "60/30/10": {"routine": 0.6, "approval": 0.3, "sensitive": 0.1},
        "80/15/5": {"routine": 0.8, "approval": 0.15, "sensitive": 0.05},
    }
    for weights in (N3_WEIGHTS, *N3_SENSITIVITY.values()):
        assert sum(weights.values()) == pytest.approx(1.0)
