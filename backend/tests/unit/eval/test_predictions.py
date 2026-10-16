"""S1 T29 — hợp đồng `predictions.jsonl` v1 (`app.eval.predictions`, duyệt #32 ngày 13/10; chốt ở ghi chú t29-chot).

Chỉ dữ liệu tổng hợp. Lỗi đầu vào → `ValueError`, thông điệp nêu tên trường/số dòng, KHÔNG in giá trị dữ liệu.
"""

import json
import math
import typing
from pathlib import Path
from typing import Any

import pytest
from app.eval.predictions import PredictionRecord, Split, Strategy, load_predictions
from app.settings import Settings
from pydantic import ValidationError

CONTRACT_FIELDS = {
    "run_id", "strategy", "split", "scenario_id", "family", "ticket_id", "parent_ticket_id",
    "expected_route", "route", "decided_by", "raw_prob", "calibrated_prob", "p_method",
    "final_state", "exit_code", "close_reason", "resolution_path", "has_approval", "clarification_turns",
    "intent", "gold_intent", "doc_ids", "gold_doc_ids",
}  # fmt: skip
RISK_FIELDS = ("decided_by", "raw_prob", "calibrated_prob", "p_method")


def rec(**over: Any) -> dict[str, Any]:
    """Một lá tổng hợp hợp lệ: ca LLM, HITL, đã duyệt, đóng resolved."""
    base: dict[str, Any] = {
        "run_id": "0123456789ab", "strategy": "hybrid", "split": "test",
        "scenario_id": "TCX1-v1", "family": "TCX1", "ticket_id": "T-0001", "parent_ticket_id": None,
        "expected_route": "HITL", "route": "HITL", "decided_by": "llm",
        "raw_prob": 0.4, "calibrated_prob": 0.35, "p_method": "self_report",
        "final_state": "S_RESOLVED", "exit_code": None, "close_reason": "resolved_user_confirmed",
        "resolution_path": "approved", "has_approval": True, "clarification_turns": 1,
        "intent": "vpn", "gold_intent": "vpn", "doc_ids": ["kb-a", "kb-b"], "gold_doc_ids": ["kb-a"],
    }  # fmt: skip
    base.update(over)
    return base


def no_m5(**over: Any) -> dict[str, Any]:
    """Lá không tới M5 (không có điểm log 4)."""
    return rec(route=None, decided_by=None, raw_prob=None, calibrated_prob=None, p_method=None, **over)


def parse(data: dict[str, Any]) -> PredictionRecord:
    return PredictionRecord.model_validate_json(json.dumps(data))


def write(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


# ---- model ----------------------------------------------------------------------------------------------------------


def test_fields_exact() -> None:
    """Tên trường đúng hợp đồng v1 (theo DB/audit: không `p_raw`/`p_cal`; có `parent_ticket_id` — M1)."""
    assert set(PredictionRecord.model_fields) == CONTRACT_FIELDS


def test_valid_record_roundtrip() -> None:
    r = parse(rec())
    assert r.route == "HITL"
    assert r.doc_ids == ("kb-a", "kb-b")
    assert PredictionRecord.model_validate_json(r.model_dump_json()) == r


def test_no_m5_record_ok() -> None:
    r = parse(no_m5(expected_route="AUTO", has_approval=False, resolution_path="deflected", doc_ids=None))
    assert r.route is None and r.doc_ids is None


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError):
        parse(rec(p_raw=0.4))


def test_frozen() -> None:
    r = parse(rec())
    with pytest.raises(ValidationError):
        r.route = "AUTO"  # type: ignore[misc]


@pytest.mark.parametrize("field", RISK_FIELDS)
def test_route_none_requires_null_risk_fields(field: str) -> None:
    bad = no_m5()
    bad[field] = rec()[field]
    with pytest.raises(ValidationError, match="route"):
        parse(bad)


@pytest.mark.parametrize("field", ["raw_prob", "calibrated_prob"])
@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_prob_out_of_range(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        parse(rec(**{field: value}))


@pytest.mark.parametrize("field", ["raw_prob", "calibrated_prob"])
def test_prob_not_finite(field: str) -> None:
    with pytest.raises(ValidationError):
        PredictionRecord.model_validate(rec(**{field: math.nan}))


@pytest.mark.parametrize("field", ["raw_prob", "calibrated_prob"])
@pytest.mark.parametrize("value", [0, 1, 0.0, 1.0])
def test_prob_bounds_inclusive(field: str, value: float) -> None:
    assert getattr(parse(rec(**{field: value})), field) == value


@pytest.mark.parametrize(
    ("field", "value"),
    [("decided_by", "human"), ("p_method", "abc"), ("final_state", "S_NEW"), ("exit_code", "E10"),
     ("close_reason", "closed"), ("resolution_path", "manual"), ("intent", "printer")],
)  # fmt: skip
def test_db_enum_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        parse(rec(**{field: value}))


@pytest.mark.parametrize(("field", "value"), [("expected_route", "L2"), ("route", "auto"), ("strategy", "hybrid2"),
                                              ("split", "train")])  # fmt: skip
def test_literal_rejected(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        parse(rec(**{field: value}))


@pytest.mark.parametrize("value", ["1", True, -1, 1.5])
def test_clarification_turns_strict(value: Any) -> None:
    with pytest.raises(ValidationError):
        parse(rec(clarification_turns=value))


@pytest.mark.parametrize("value", ["true", 1, None])
def test_has_approval_strict(value: Any) -> None:
    with pytest.raises(ValidationError):
        parse(rec(has_approval=value))


@pytest.mark.parametrize("value", ["0123456789AB", "0123456789a", "0123456789abc", ""])
def test_run_id_pattern(value: str) -> None:
    """P8 §5.1: `run_id = sha256(...)[:12]` — 12 chữ số hex thường."""
    with pytest.raises(ValidationError):
        parse(rec(run_id=value))


@pytest.mark.parametrize("field", ["scenario_id", "family", "ticket_id"])
def test_ids_not_empty(field: str) -> None:
    with pytest.raises(ValidationError):
        parse(rec(**{field: ""}))


def test_doc_ids_items_not_empty() -> None:
    with pytest.raises(ValidationError):
        parse(rec(doc_ids=["kb-a", ""]))


def test_strategy_matches_settings() -> None:
    """Một nguồn: `Strategy` = Literal của `settings.strategy` (settings.py:191)."""
    assert typing.get_args(Strategy) == typing.get_args(Settings.model_fields["strategy"].annotation)


def test_split_values() -> None:
    assert typing.get_args(Split) == ("calibration", "test")


def test_error_does_not_echo_input() -> None:
    with pytest.raises(ValidationError) as exc:
        parse(rec(exit_code="ZZSECRET9", ticket_id="T-0001"))
    assert "ZZSECRET9" not in str(exc.value)


# ---- load_predictions ---------------------------------------------------------------------------------------------


def test_load_ok_keeps_order(tmp_path: Path) -> None:
    rows = [rec(ticket_id=f"T-{i}", scenario_id=f"S-{i}") for i in range(3)] + [no_m5(ticket_id="T-9", scenario_id="S-9")]
    out = load_predictions(write(tmp_path / "p.jsonl", rows))
    assert [r.ticket_id for r in out] == ["T-0", "T-1", "T-2", "T-9"]
    assert all(isinstance(r, PredictionRecord) for r in out)


def test_load_empty_file(tmp_path: Path) -> None:
    p = tmp_path / "p.jsonl"
    p.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="rỗng"):
        load_predictions(p)


def test_load_blank_line(tmp_path: Path) -> None:
    p = tmp_path / "p.jsonl"
    p.write_text(json.dumps(rec()) + "\n\n" + json.dumps(rec(ticket_id="T-2", scenario_id="S-2")) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="dòng 2: dòng trống"):
        load_predictions(p)


def test_load_invalid_line_reports_line_not_content(tmp_path: Path) -> None:
    p = tmp_path / "p.jsonl"
    p.write_text(json.dumps(rec()) + "\n" + '{"ticket_id": "ZZSECRET7", \n', encoding="utf-8")
    with pytest.raises(ValueError, match="dòng 2") as exc:
        load_predictions(p)
    assert "ZZSECRET7" not in str(exc.value)


def test_load_invalid_field_reports_field_not_value(tmp_path: Path) -> None:
    p = write(tmp_path / "p.jsonl", [rec(), rec(ticket_id="T-2", scenario_id="S-2", exit_code="ZZSECRET8")])
    with pytest.raises(ValueError, match="dòng 2.*exit_code") as exc:
        load_predictions(p)
    assert "ZZSECRET8" not in str(exc.value)


@pytest.mark.parametrize(("field", "other"), [("run_id", "ba9876543210"), ("strategy", "rule_only"), ("split", "calibration")])
def test_load_rejects_mixed(tmp_path: Path, field: str, other: str) -> None:
    rows = [rec(), rec(ticket_id="T-2", scenario_id="S-2", **{field: other})]
    with pytest.raises(ValueError, match=field) as exc:
        load_predictions(write(tmp_path / "p.jsonl", rows))
    assert other not in str(exc.value)


def test_load_rejects_duplicate_ticket_id(tmp_path: Path) -> None:
    rows = [rec(ticket_id="T-ZZSECRET", scenario_id="S-1"), rec(ticket_id="T-ZZSECRET", scenario_id="S-2")]
    with pytest.raises(ValueError, match="ticket_id.*dòng 2") as exc:
        load_predictions(write(tmp_path / "p.jsonl", rows))
    assert "ZZSECRET" not in str(exc.value)


def test_load_rejects_multi_intent_leaf(tmp_path: Path) -> None:
    """Q-T29-1: lá con (có cha) = kịch bản nhiều ý → từ chối tới khi có `gold.leaves`."""
    rows = [rec(), rec(ticket_id="T-2", scenario_id="S-2", parent_ticket_id="P-ZZSECRET")]
    with pytest.raises(ValueError, match="dòng 2.*nhiều ý") as exc:
        load_predictions(write(tmp_path / "p.jsonl", rows))
    assert "ZZSECRET" not in str(exc.value)


def test_load_rejects_duplicate_scenario_id(tmp_path: Path) -> None:
    """v1: một kịch bản một bộ gold → đúng một lá (hai lá cùng kịch bản = gold bị dùng chung — như Q-T29-1)."""
    rows = [rec(ticket_id="T-1", scenario_id="S-ZZSECRET"), rec(ticket_id="T-2", scenario_id="S-ZZSECRET")]
    with pytest.raises(ValueError, match="scenario_id.*dòng 2") as exc:
        load_predictions(write(tmp_path / "p.jsonl", rows))
    assert "ZZSECRET" not in str(exc.value)
