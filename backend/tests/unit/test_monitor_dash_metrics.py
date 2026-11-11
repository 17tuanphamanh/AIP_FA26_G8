"""M9 A1, A2 — `metrics.py`: `METRIC_SOURCES` (chỉ khóa response, hai chiều, nghiệp vụ + AI), `PENDING_SOURCES`
(Q-M9-A1-7, Q-M9-A2-8), `is_pending` (khóa lạ → KeyError), hằng E1 nguyên văn `reason_detail`, hằng N3.
F12 (#45): `multi_intent` ready (chỉ `first_stop`; `messages_per_turn` pending riêng), E1 thêm `split_span_invalid`,
`E5_SENSITIVE_REASONS`."""

import ast
from pathlib import Path

import pytest
from app.domain.exit_codes import REASON_DETAILS
from app.domain.override import OVERRIDE_EVENT, OVERRIDE_STEP
from app.monitor.metrics import (
    E1_OTHER,
    E1_REASONS,
    E5_SENSITIVE_REASONS,
    METRIC_SOURCES,
    N3_SENSITIVITY,
    N3_WEIGHTS,
    PENDING_SOURCES,
    is_pending,
)
from app.monitor.queries.ai import AI_METRICS
from app.monitor.queries.business import BUSINESS_METRICS

REPO = Path(__file__).resolve().parents[3]
GRAPH_CHILDREN = REPO / "backend" / "app" / "graph" / "children.py"
PENDING_RULE_SOURCES = {"b3_cascade", "tool_spans", "b2_classifier"}
FIRST_STOP = "multi_intent_first_stop_to_reply_s"
PER_TURN = "multi_intent_messages_per_turn"
PENDING_METRICS = {PER_TURN}


def test_metric_sources_equal_response_keys_both_ways() -> None:
    assert len(BUSINESS_METRICS) == 10  # quét rỗng thì đỏ, không xanh giả
    assert len(AI_METRICS) == 14  # Q-M9-A2-6: 12 dòng bảng 5.2 = 14 khóa
    assert not set(BUSINESS_METRICS) & set(AI_METRICS)
    assert len(METRIC_SOURCES) >= 24
    assert set(METRIC_SOURCES) == set(BUSINESS_METRICS) | set(AI_METRICS)


def test_pending_sources_exact() -> None:
    assert dict(PENDING_SOURCES) == dict.fromkeys(PENDING_RULE_SOURCES, "pending") | {
        "approval_view": "ready",
        "override_count": "ready",  # 4d (e510a6e) đã ghi dòng OVERRIDE
        "multi_intent": "ready",  # F12: v_child_notices (0011) — giữ khóa, không xóa
    }
    assert "policy_saved" not in PENDING_SOURCES  # luật 11 chạy truy vấn thật, không gọi is_pending


def test_is_pending_values() -> None:
    for key in PENDING_RULE_SOURCES:
        assert is_pending(key) is True, key
    assert is_pending("approval_view") is False
    assert is_pending("override_count") is False  # có ở cả hai dict, cùng ready
    assert is_pending("multi_intent") is False
    for key in PENDING_METRICS:
        assert is_pending(key) is True, key
    for key in set(METRIC_SOURCES) - PENDING_METRICS:  # gồm b2_llm_rate, b3_llm_rate, intent_model_version, first_stop
        assert is_pending(key) is False, key


def test_multi_intent_sources_split() -> None:
    """F12: `first_stop` đi theo `PENDING_SOURCES["multi_intent"]` (ready, nguồn `child_notices`); `messages_per_turn`
    GIỮ pending với nguồn RIÊNG (`d30_parent_turns`: cần lượt của ticket cha, D-30 không cho đọc) — không còn đi theo
    `multi_intent`, không mang lý do cũ `phase5_multi_intent`."""
    first, per_turn = METRIC_SOURCES[FIRST_STOP], METRIC_SOURCES[PER_TURN]
    assert first.status == PENDING_SOURCES["multi_intent"] == "ready"
    assert "child_notices" in first.tables and first.pending_reason is None
    assert per_turn.status == "pending" and per_turn.pending_reason == "d30_parent_turns"
    assert is_pending(FIRST_STOP) is False and is_pending(PER_TURN) is True
    assert all(s.pending_reason != "phase5_multi_intent" for s in METRIC_SOURCES.values())


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
    assert (override.step, override.event) == (OVERRIDE_STEP, OVERRIDE_EVENT) == ("OVERRIDE", "override_recorded")
    assert override.status == "ready" and override.pending_reason is None


def test_e1_reasons_verbatim_reason_detail() -> None:
    assert E1_REASONS == (
        "out_of_scope", "multi_intent_not_enabled", "intent_low_confidence", "intent_not_enabled", "split_span_invalid",
        "reverse_action_requested",  # D-84 (12/11): thêm vào CUỐI
    )  # fmt: skip
    assert set(E1_REASONS) <= REASON_DETAILS
    assert "intent_out_of_scope" not in E1_REASONS  # tên event audit B4, không phải reason_detail
    assert E1_OTHER == "other" and E1_OTHER not in E1_REASONS


def _graph_e1_reasons() -> set[str]:
    """`E1_REASONS` của `graph/children.py` (bảng 5.2.2) đọc bằng AST — monitor không được import `app.graph`
    (`.importlinter`), test cũng không import để khỏi chạy code graph."""
    tree = ast.parse(GRAPH_CHILDREN.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "E1_REASONS":
            assert node.value is not None
            return {c.value for c in ast.walk(node.value) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
    raise AssertionError("graph/children.py không còn E1_REASONS")


def test_e1_reasons_cover_graph_children() -> None:
    """F12: mọi reason_detail E1 mà graph ghi (bảng 5.2.2, gồm `split_span_invalid`) có khóa riêng; khóa cũ
    `multi_intent_not_enabled` (Phase 3–4, dữ liệu cũ) vẫn giữ."""
    graph = _graph_e1_reasons()
    assert "split_span_invalid" in graph and len(graph) == 4  # quét rỗng/đổi bảng thì đỏ
    assert graph <= set(E1_REASONS)
    assert "multi_intent_not_enabled" in E1_REASONS


def test_e5_sensitive_reasons_constant() -> None:
    """F12 (#45): chỉ `llm_high_risk` (B12 lớp LLM chuyển L2) ép nhóm sensitive; `llm_layer_disabled` giữ hành vi cũ."""
    assert E5_SENSITIVE_REASONS == ("llm_high_risk",)
    assert set(E5_SENSITIVE_REASONS) <= REASON_DETAILS
    assert "llm_layer_disabled" not in E5_SENSITIVE_REASONS


def test_n3_weights_constants() -> None:
    assert dict(N3_WEIGHTS) == {"routine": 0.7, "approval": 0.2, "sensitive": 0.1}
    assert {k: dict(v) for k, v in N3_SENSITIVITY.items()} == {
        "60/30/10": {"routine": 0.6, "approval": 0.3, "sensitive": 0.1},
        "80/15/5": {"routine": 0.8, "approval": 0.15, "sensitive": 0.05},
    }
    for weights in (N3_WEIGHTS, *N3_SENSITIVITY.values()):
        assert sum(weights.values()) == pytest.approx(1.0)
