"""M9 A1, A2 — `metrics.py`: `METRIC_SOURCES` (chỉ khóa response, hai chiều, nghiệp vụ + AI), `PENDING_SOURCES`
(Q-M9-A1-7, Q-M9-A2-8), `is_pending` (khóa lạ → KeyError), hằng E1 nguyên văn `reason_detail`, hằng N3."""

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
from app.monitor.queries.ai import AI_METRICS
from app.monitor.queries.business import BUSINESS_METRICS

PENDING_RULE_SOURCES = {"override_count", "multi_intent", "b3_cascade", "tool_spans", "b2_classifier"}
MULTI_INTENT_KEYS = {"multi_intent_first_stop_to_reply_s", "multi_intent_messages_per_turn"}
PENDING_METRICS = {"override_count", *MULTI_INTENT_KEYS}


def test_metric_sources_equal_response_keys_both_ways() -> None:
    assert len(BUSINESS_METRICS) == 10  # quét rỗng thì đỏ, không xanh giả
    assert len(AI_METRICS) == 14  # Q-M9-A2-6: 12 dòng bảng 5.2 = 14 khóa
    assert not set(BUSINESS_METRICS) & set(AI_METRICS)
    assert len(METRIC_SOURCES) >= 24
    assert set(METRIC_SOURCES) == set(BUSINESS_METRICS) | set(AI_METRICS)


def test_pending_sources_exact() -> None:
    assert dict(PENDING_SOURCES) == dict.fromkeys(PENDING_RULE_SOURCES, "pending") | {"approval_view": "ready"}
    assert "policy_saved" not in PENDING_SOURCES  # luật 11 chạy truy vấn thật, không gọi is_pending


def test_is_pending_values() -> None:
    for key in PENDING_RULE_SOURCES:
        assert is_pending(key) is True, key
    assert is_pending("approval_view") is False
    for key in PENDING_METRICS:
        assert is_pending(key) is True, key
    for key in set(METRIC_SOURCES) - PENDING_METRICS:  # gồm b2_llm_rate, b3_llm_rate, intent_model_version (ready)
        assert is_pending(key) is False, key


def test_multi_intent_metrics_follow_source() -> None:
    for key in MULTI_INTENT_KEYS:
        assert METRIC_SOURCES[key].status == PENDING_SOURCES["multi_intent"], key


@pytest.mark.parametrize("key", ["policy_saved", "khong_co", "b3_llm_ratio", "multi_intent_rate", ""])
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
