"""`app.audit.m5_review` — phase6 mục 7 (chặng 6D), r1–r10. Viết TỪ ĐẶC TẢ trước thân code (7.1 P1–P8, 7.3; MẪU A 6D đã duyệt:
Q-6D-1 = A, Q-6D-2 = C, Q-6D-3 = A, Q-6D-4 = A).

- r1 `point4_rows`: chỉ dòng `POINT4_KEY`; điểm 3/7/8 + `llm_layer_disabled` bị bỏ; `decided_by` NULL giữ; thứ tự `log_id` toàn cục.
- r2–r4 `pick`/`sample_reasons`: bỏ trùng nguyên văn; tất định theo seed; `min_llm`; thiếu → báo số thật (Q-6D-1 = A).
- r5 không rò: canary trong TRƯỜNG `ticket_id`, `detail.route`, `matched_rule_id`, `detail.expected_route` không có ở đầu ra (hàm + stdout
  của vỏ). Q-6D-2 = C: chữ `reason` giữ nguyên — KHÔNG kiểm "R0–R20" bên trong reason.
- r6 `template_reasons`: 4 câu = `strategy.decide` ở cùng tham số (MẪU A bảng 4 mẫu) — test tự gọi `decide`, không chép chuỗi.
- r7–r9 `concentration`; r10 cảnh báo dữ liệu giả + mã 3 (Q-6D-4 = A: khác "real" kể cả None).
r7 "6/10 = 60 %" của 7.3 mâu thuẫn `n < 20 → None` (P6) → dùng cùng tỉ lệ ở n = 20, 30 (ghi "lệch spec" MẪU B).
"""

import asyncio
import csv
import math
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.audit import m5_review
from app.audit.check import POINT4_KEY
from app.audit.m5_review import (
    Point4,
    concentration,
    histogram,
    pick,
    point4_rows,
    probe_report,
    sample_reasons,
    template_reasons,
)
from app.domain.risk_factors import FactorCode
from app.risk.calibrator import Calibrator, CalibratorParams, FitInfo
from app.risk.estimator import RiskEstimate
from app.risk.models import RuleVerdict
from app.risk.strategy import FullAutoBypass, decide

SINCE = "2026-10-15T08:00:00+07:00"
SCRIPTED_WARNING = "DỮ LIỆU GIẢ (ScriptedLLM) — không dùng để chọn p_method"
_DSN_SECRET = "pw-" + "m5review-6d"  # ghép lúc chạy (gitleaks)
DSN = f"postgresql+psycopg://app_rw:{_DSN_SECRET}@db-host-6d:5432/servicedesk"


def _row(log_id: int, ticket: str, step: str = "B13/B14", event: str = "risk_decided", *, detail: dict[str, Any] | None = None,
         **cols: Any) -> dict[str, Any]:  # fmt: skip
    return {"log_id": log_id, "ticket_id": ticket, "step": step, "event": event, "detail": detail or {}, **cols}


def _p(reason: str, decided_by: str | None = "rule", *, ticket: str = "tk-x", route: str = "HITL",
       raw: float | None = None) -> Point4:  # fmt: skip
    return Point4(ticket_id=ticket, decided_by=decided_by, route=route, reason=reason, raw_prob=raw,
                  p_method="self_report" if decided_by == "llm" else None)  # fmt: skip


def _rules(k: int, prefix: str = "luật") -> list[Point4]:
    return [_p(f"{prefix} số {i}", ticket=f"tk-r{i}") for i in range(k)]


def _llms(k: int) -> list[Point4]:
    return [_p(f"mô hình số {i}", "llm", ticket=f"tk-l{i}", raw=0.9) for i in range(k)]


# ---- r1 point4_rows ----------------------------------------------------------------------------------------------------------------


def test_r1_point4_rows_only_point4_and_keeps_null() -> None:
    assert POINT4_KEY == ("B13/B14", "risk_decided")
    by_ticket = {
        "tk-a": [
            _row(1, "tk-a", "B8", "retrieved", detail={"query": "q", "top_score": 0.8}),
            _row(4, "tk-a", decided_by="rule", policy_decision="allow", risk_level="low", reason="Luật cho phép",
                 detail={"route": "AUTO"}),
            _row(7, "tk-a", "B18", "executed_ok", detail={"write_calls": 1}),
            _row(9, "tk-a", "B20", "closed", final_state="S_RESOLVED"),
        ],
        "tk-b": [
            _row(2, "tk-b", "B13/B14", "llm_layer_disabled", reason="lỗi estimator", detail={"route": "ESCALATE_L2"}),
            _row(3, "tk-b", decided_by="llm", reason="Mô hình …", raw_prob=0.9, p_method="self_report",
                 detail={"route": "ESCALATE_L2"}),
        ],
        "tk-c": [_row(5, "tk-c", decided_by=None, detail={"strategy": "full_auto", "route": "AUTO", "policy_sha256": "a" * 64})],
    }  # fmt: skip
    got = point4_rows(by_ticket)
    assert got == [
        Point4("tk-b", "llm", "ESCALATE_L2", "Mô hình …", 0.9, "self_report"),
        Point4("tk-a", "rule", "AUTO", "Luật cho phép", None, None),
        Point4("tk-c", None, "AUTO", None, None, None),
    ]


# ---- r2–r4 chọn mẫu -------------------------------------------------------------------------------------------------------------------


def test_r2_dedup_verbatim_reason() -> None:
    rows = [_p("cùng một câu", ticket=f"tk-d{i}") for i in range(6)] + _rules(4, "khác")
    got = sample_reasons(rows, n=10, seed=7, min_llm=0)
    assert len(got) == len(set(got)) == 5
    assert set(got) == {"cùng một câu", *(f"khác số {i}" for i in range(4))}


def test_r2_dedup_keeps_first_row() -> None:
    rows = [_p("trùng", ticket="tk-first"), _p("trùng", ticket="tk-second")]
    assert [p.ticket_id for p in pick(rows, n=10, seed=1, min_llm=0)] == ["tk-first"]


def test_r3_deterministic_by_seed() -> None:
    rows = _rules(25)
    a = sample_reasons(rows, n=10, seed=42, min_llm=0)
    assert a == sample_reasons(list(rows), n=10, seed=42, min_llm=0)
    assert a != sample_reasons(rows, n=10, seed=43, min_llm=0)
    assert len(a) == 10


@pytest.mark.parametrize("n_llm, want_llm", [(3, 3), (5, 3)])
def test_r4_min_llm_met(n_llm: int, want_llm: int) -> None:
    got = pick(_llms(n_llm) + _rules(20), n=10, seed=3, min_llm=3)
    assert len(got) == 10
    assert sum(p.decided_by == "llm" for p in got) == want_llm


def test_r4_min_llm_short_takes_all_llm() -> None:
    got = pick(_llms(1) + _rules(20), n=10, seed=3, min_llm=3)
    assert len(got) == 10
    assert sum(p.decided_by == "llm" for p in got) == 1 and sum(p.decided_by == "rule" for p in got) == 9


def test_r4_rules_short_fill_from_llm() -> None:
    got = pick(_llms(6) + _rules(2), n=10, seed=3, min_llm=3)
    assert len(got) == 8 and sum(p.decided_by == "llm" for p in got) == 6


def test_r4_skips_null_decided_by_and_empty_reason() -> None:
    rows = [_p("full_auto", None), _p("", "rule"), Point4("tk-n", "rule", "HITL", None, None, None), *_rules(2)]
    assert sorted(sample_reasons(rows, n=10, seed=1, min_llm=0)) == ["luật số 0", "luật số 1"]


@pytest.mark.parametrize("kw", [{"n": 0, "min_llm": 0}, {"n": 5, "min_llm": -1}])
def test_r4_bad_arguments(kw: dict[str, int]) -> None:
    with pytest.raises(ValueError):
        pick(_rules(3), seed=1, **kw)


# ---- vỏ sample (r4 báo thiếu, r5 không rò) ----------------------------------------------------------------------------------------


def _settings(llm_backend: str | None = "real") -> SimpleNamespace:
    return SimpleNamespace(monitor_database_url=None, database_url=DSN, llm_backend=llm_backend)


def _shell(monkeypatch: pytest.MonkeyPatch, rows: Sequence[Point4] | Exception, llm_backend: str | None = "real") -> None:
    monkeypatch.setattr(m5_review, "get_settings", lambda: _settings(llm_backend))

    async def fetch(dsn: str, since: datetime) -> list[Point4]:
        assert dsn == DSN and since.utcoffset() is not None
        if isinstance(rows, Exception):
            raise rows
        return list(rows)

    monkeypatch.setattr(m5_review, "_fetch", fetch)


def test_r4_shell_reports_llm_short_exit_0(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _shell(monkeypatch, _llms(1) + _rules(20))
    assert m5_review.sample_main(["--since", SINCE, "--n", "10", "--seed", "5", "--min-llm", "3"]) == 0
    out, err = capsys.readouterr()
    assert "thiếu câu llm: 1/3" in err
    assert [line.split(". ", 1)[0] for line in out.splitlines()] == [str(i) for i in range(1, 11)]


def test_r4_shell_total_short_exit_1(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _shell(monkeypatch, _rules(4))
    assert m5_review.sample_main(["--since", SINCE, "--n", "10", "--seed", "5", "--min-llm", "0"]) == 1
    out, err = capsys.readouterr()
    assert len(out.splitlines()) == 4 and "4/10" in err


CANARY_TICKET = "tk-CANARY6dTK"
CANARY_ROUTE = "CANARY6dROUTE"
CANARY_RULE = "CANARY6dRULE"
CANARY_EXPECTED = "CANARY6dEXP"
CANARIES = (CANARY_TICKET, CANARY_ROUTE, CANARY_RULE, CANARY_EXPECTED)


def _canary_rows() -> list[Point4]:
    raw: list[dict[str, Any]] = []
    for i in range(14):
        decided_by = "llm" if i % 3 == 0 else "rule"
        raw.append(_row(i + 1, f"{CANARY_TICKET}{i}", decided_by=decided_by, matched_rule_id=CANARY_RULE,
                        reason=f"Lý do bình thường số {i}", raw_prob=0.9 if decided_by == "llm" else None,
                        detail={"route": CANARY_ROUTE, "expected_route": CANARY_EXPECTED, "policy_sha256": "b" * 64}))  # fmt: skip
    by_ticket: dict[str, list[dict[str, Any]]] = {}
    for r in raw:
        by_ticket.setdefault(r["ticket_id"], []).append(r)
    return point4_rows(by_ticket)


def test_r5_function_output_has_no_field_canary() -> None:
    text = "\n".join(sample_reasons(_canary_rows(), n=10, seed=11, min_llm=3))
    assert text and not [c for c in CANARIES if c in text]


def test_r5_shell_stdout_has_no_field_canary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    _shell(monkeypatch, _canary_rows())
    key = tmp_path / "key.csv"
    argv = ["--since", SINCE, "--n", "10", "--seed", "11", "--min-llm", "3", "--templates", "--key-out", str(key)]
    assert m5_review.sample_main(argv) == 0
    out, err = capsys.readouterr()
    assert not [c for c in (*CANARIES, _DSN_SECRET, "db-host-6d") if c in out + err]
    assert len(out.splitlines()) == 14 and sum("[mẫu]" in line for line in out.splitlines()) == 4
    # đối chứng: canary CÓ trong file đối chiếu (ticket_id, route) — đầu ra sạch không phải vì dữ liệu rỗng
    rows = list(csv.reader(key.read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["so", "ticket_id", "decided_by", "route"] and len(rows) == 11
    assert all(r[1].startswith(CANARY_TICKET) and r[3] == CANARY_ROUTE for r in rows[1:])
    assert [r[0] for r in rows[1:]] == [str(i) for i in range(1, 11)]


def test_r5_shell_reason_text_kept_verbatim(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Q-6D-2 = C: reason = mã luật / chứa "Luật R07" vẫn in nguyên văn (câu "không hiểu" cần phát hiện)."""
    _shell(monkeypatch, [_p("R05"), _p("Luật R07 cho phép; kiểm tra bổ sung")])
    assert m5_review.sample_main(["--since", SINCE, "--n", "2", "--seed", "1", "--min-llm", "0"]) == 0
    out = capsys.readouterr().out
    assert sorted(line.split(". ", 1)[1] for line in out.splitlines()) == ["Luật R07 cho phép; kiểm tra bổ sung", "R05"]


def test_shell_db_error_prints_class_only(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _shell(monkeypatch, OSError(f"connect failed {DSN}"))
    assert m5_review.sample_main(["--since", SINCE, "--n", "10", "--seed", "1"]) == 2
    out, err = capsys.readouterr()
    assert "OSError" in err and _DSN_SECRET not in out + err and "db-host-6d" not in out + err


def test_shell_since_needs_timezone() -> None:
    with pytest.raises(SystemExit) as exc:
        m5_review.sample_main(["--since", "2026-10-15T08:00:00", "--n", "10", "--seed", "1"])
    assert exc.value.code == 2


# ---- r6 template_reasons ----------------------------------------------------------------------------------------------------------


def _estimate(raw: float, *factors: FactorCode) -> RiskEstimate:
    return RiskEstimate(raw_prob=raw, p_method="self_report", factors=factors, prompt_id="b14_risk_estimate",
                        prompt_version="1", model="mau")  # fmt: skip


def test_r6_templates_equal_strategy_decide() -> None:
    cal = Calibrator(CalibratorParams(
        version="platt-20261015-00000000", method="platt", a=1.0, b=0.0,
        fitted_on=FitInfo(split="calibration", n=40, n_pos=10, n_families=8, data_sha256="0" * 64),
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    ))  # fmt: skip
    none = RuleVerdict(matched=False, decision=None, rule_id=None, all_matched=[], description=None)
    allow = RuleVerdict(matched=True, decision="allow", rule_id="(mẫu)", all_matched=["(mẫu)"], description="mẫu")
    th = (0.25, 0.75)
    cases = [
        ("hybrid", none, _estimate(0.10, FactorCode.ROUTINE_LOW_RISK), cal, False, "AUTO"),
        ("hybrid", none, _estimate(0.10, FactorCode.ROUTINE_LOW_RISK), None, False, "HITL"),
        ("hybrid", none, _estimate(0.10, FactorCode.NO_POLICY_EVIDENCE), cal, True, "HITL"),
        ("hybrid_guarded", allow, _estimate(0.60, FactorCode.TARGET_IS_OTHER, FactorCode.SENSITIVE_DATA), cal, False, "HITL"),
    ]  # fmt: skip
    want = []
    for strategy, verdict, est, calibrator, kb_gap, route in cases:
        d = decide(strategy, verdict, est, calibrator=calibrator, thresholds=th, kb_gap=kb_gap)  # type: ignore[arg-type]
        assert not isinstance(d, FullAutoBypass) and d.route == route
        want.append(d.reason)
    assert len(set(want)) == 4
    assert template_reasons() == want


# ---- r7–r9 concentration ----------------------------------------------------------------------------------------------------------


def _spread(on_two: int, n: int) -> list[float]:
    """`on_two` giá trị chia đều cho 2 mức 0,10 / 0,20; phần còn lại mỗi giá trị một mức riêng (0,31, 0,32, …)."""
    rest = [round(0.31 + 0.01 * i, 2) for i in range(n - on_two)]
    return [0.10] * (on_two // 2) + [0.20] * (on_two - on_two // 2) + rest


@pytest.mark.parametrize("n", [20, 30])
def test_r7_exactly_60_percent_is_self_report(n: int) -> None:
    c = concentration(_spread(n * 6 // 10, n))
    assert c.n == n and c.share == pytest.approx(0.60) and c.recommend == "self_report"


@pytest.mark.parametrize("n", [20, 30])
def test_r7_70_percent_is_sampling(n: int) -> None:
    c = concentration(_spread(n * 7 // 10, n))
    assert c.share == pytest.approx(0.70) and c.recommend == "sampling_k5"


def test_r7_n19_not_enough() -> None:
    c = concentration([0.9] * 19)
    assert c.n == 19 and c.recommend is None


def test_r7_all_same_level() -> None:
    c = concentration([0.9] * 20)
    assert c.recommend == "sampling_k5" and c.share == 1.0 and c.top == ((0.9, 20),)


def test_r7_empty() -> None:
    c = concentration([])
    assert (c.n, c.top, c.share, c.recommend) == (0, (), 0.0, None)


def test_r8_rounding_to_two_digits() -> None:
    c = concentration([0.904] * 10 + [0.896] * 10)
    assert c.top[0] == (0.9, 20) and len(c.top) == 1


@pytest.mark.parametrize("bad", [math.nan, 1.2, -0.1, math.inf, True])
def test_r9_bad_input_value_error_without_value(bad: float) -> None:
    with pytest.raises(ValueError) as exc:
        concentration([0.5] * 20 + [bad])
    msg = str(exc.value)
    assert not [s for s in ("nan", "1.2", "-0.1", "inf", "True") if s in msg]


def test_histogram_ten_bins_edges() -> None:
    bins = histogram([0.0, 0.05, 0.1, 0.3, 0.7, 0.99, 1.0])
    assert [(lo, hi) for lo, hi, _ in bins] == [(round(i / 10, 1), round((i + 1) / 10, 1)) for i in range(10)]
    assert [c for *_, c in bins] == [2, 1, 0, 1, 0, 0, 0, 1, 0, 2]


# ---- r10 cảnh báo dữ liệu giả + mã thoát (Q-6D-3, Q-6D-4) -------------------------------------------------------------------------


def test_r10_scripted_warns_first_line_exit_3() -> None:
    text, code = probe_report([0.9] * 30, llm_backend="scripted")
    assert code == 3 and text.splitlines()[0] == SCRIPTED_WARNING
    assert "#" in text  # vẫn in bảng


def test_r10_real_no_warning() -> None:
    text, code = probe_report([0.9] * 30, llm_backend="real")
    assert code == 0 and "DỮ LIỆU GIẢ" not in text and "không dùng để chọn p_method" not in text
    assert "sampling_k5" in text


def test_r10_none_backend_warns_exit_3() -> None:
    text, code = probe_report([0.9] * 30, llm_backend=None)
    assert code == 3 and "không dùng để chọn p_method" in text.splitlines()[0]


@pytest.mark.parametrize("backend, code", [("real", 1), ("scripted", 3), (None, 3)])
def test_r10_not_enough_data(backend: str | None, code: int) -> None:
    text, got = probe_report([0.9] * 5, llm_backend=backend)
    assert got == code and "không đủ dữ liệu" in text


def test_probe_shell_csv_and_filter(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rows = [*_llms(25), _p("luật", "rule"), Point4("tk-q", "llm", "HITL", "x", None, None)]
    _shell(monkeypatch, rows, llm_backend="scripted")
    out_csv = tmp_path / "p.csv"
    assert m5_review.probe_main(["--since", SINCE, "--csv", str(out_csv)]) == 3
    out, err = capsys.readouterr()
    assert out.splitlines()[0] == SCRIPTED_WARNING and "n = 25" in out
    assert _DSN_SECRET not in out + err
    lines = list(csv.reader(out_csv.read_text(encoding="utf-8").splitlines()))
    assert lines[0] == ["bin_lo", "bin_hi", "count"] and len(lines) == 11 and lines[-1] == ["0.9", "1.0", "25"]


def test_probe_shell_db_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    _shell(monkeypatch, RuntimeError(DSN))
    assert m5_review.probe_main(["--since", SINCE]) == 2
    out, err = capsys.readouterr()
    assert "RuntimeError" in err and _DSN_SECRET not in out + err


def test_module_dispatch_rejects_unknown_command() -> None:
    assert m5_review._dispatch(["khac"]) == 2
    assert asyncio.iscoroutinefunction(m5_review.load_point4)
