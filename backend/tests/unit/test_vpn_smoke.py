"""`tests/stack/vpn_smoke.py` (PLAN-3h S15b; phase3 11.9; chốt Q-3h-8) — phần chạy được không cần stack: TỪ CHỐI chạy LLM thật
khi trần chi `spend.cap_usd` (config container backend ĐANG nạp) > 1 hoặc model chưa có pricing — trước mọi HTTP/ticket;
script dò trong container (chạy thật ở đây với env giả) không in khoá/tên model; bảng số liệu `llm_calls`. Không gọi LLM."""

import json
import math
import os
import subprocess
import sys
from typing import Any

import pytest
from tests.stack import gate3, vpn_smoke
from tests.unit.test_gate3 import COMPOSE, FLAGS_OK, SECRET, FakeRun
from tests.unit.test_policy_rules_vpn import REPO

REAL_OK = {"backend": "real", "cap_usd": 1.0, "pricing_ok": True}


class SmokeRun(FakeRun):
    def __init__(self, probe: dict[str, Any] | str, flags: str = FLAGS_OK) -> None:
        super().__init__(flags=flags)
        self.probe = probe

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        if cmd[-1] == vpn_smoke.PROBE:
            self.calls.append(cmd)
            return 0, self.probe if isinstance(self.probe, str) else json.dumps(self.probe) + "\n"
        return super().__call__(cmd, stdin)


def _main(run: FakeRun) -> tuple[int, list[str]]:
    out: list[str] = []
    return vpn_smoke.main([], run=run, env={"COMPOSE": COMPOSE}, echo=out.append), out


# ---- Chốt trần chi / pricing -----------------------------------------------------------------------------------------


@pytest.mark.parametrize(("probe", "why"), [
    ({"backend": "real", "cap_usd": 38.0, "pricing_ok": True}, "spend.cap_usd = 38.0 > 1"),
    ({"backend": "real", "cap_usd": 1.01, "pricing_ok": True}, "spend.cap_usd = 1.01 > 1"),
    ({"backend": "real", "cap_usd": math.nan, "pricing_ok": True}, "spend.cap_usd"),
    ({"backend": "real", "pricing_ok": True}, "spend.cap_usd = None"),
    ({"backend": "real", "cap_usd": True, "pricing_ok": True}, "spend.cap_usd"),  # bool không phải số
    ({"backend": "real", "cap_usd": 1, "pricing_ok": False}, "chưa có dòng pricing"),
    ({"backend": "real", "cap_usd": 0.5}, "chưa có dòng pricing"),
    ({"backend": "?", "cap_usd": 1, "pricing_ok": True}, "không phải scripted/real"),
    ({"error": "ValidationError"}, "không đọc được cấu hình LLM"),
])  # fmt: skip
def test_refusal_reasons(probe: dict[str, Any], why: str) -> None:
    reason = vpn_smoke.refusal(probe)
    assert reason is not None and why in reason


@pytest.mark.parametrize("probe", [REAL_OK, {"backend": "real", "cap_usd": 0.2, "pricing_ok": True},
                                   {"backend": "scripted", "cap_usd": 38.0, "pricing_ok": True}])  # fmt: skip
def test_allowed(probe: dict[str, Any]) -> None:
    assert vpn_smoke.refusal(probe) is None


@pytest.mark.parametrize("probe", [{"backend": "real", "cap_usd": 38.0, "pricing_ok": True},
                                   {"backend": "real", "cap_usd": 1, "pricing_ok": False},
                                   "Traceback (most recent call last)\n", ""])  # fmt: skip
def test_refuses_before_any_ticket_or_llm_call(probe: dict[str, Any] | str) -> None:
    run = SmokeRun(probe)
    code, out = _main(run)
    assert code == 2 and any(line.startswith("TỪ CHỐI:") for line in out)
    # printenv APP_ENV, dò biến, dò cấu hình LLM — KHÔNG psql (mốc llm_calls), KHÔNG HTTP, KHÔNG ticket
    assert len(run.calls) == 3 and not any("postgres" in c for c in run.calls)


def test_real_backend_allowed_to_pass_env_gate_but_fake_scenario_still_stops() -> None:
    real = FLAGS_OK.replace("LLM_BACKEND=scripted", "LLM_BACKEND=real")
    assert gate3.env_gate(gate3.Shell(COMPOSE.split(), run=SmokeRun(REAL_OK, real), echo=lambda _: None),
                          require_scripted=False)["LLM_BACKEND"] == "real"  # fmt: skip
    code, out = _main(SmokeRun(REAL_OK, real.replace("FAKE_SCENARIO=0", "FAKE_SCENARIO=1")))
    assert code == 2 and any("FAKE_SCENARIO" in line for line in out)


# ---- Script dò chạy TRONG container: chạy thật ở đây với env giả --------------------------------------------------


def _run_probe(**env: str) -> str:
    base = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(REPO / "backend"), "APP_ENV": "test",
            "APP_ENV_FILE": ""}  # fmt: skip
    done = subprocess.run([sys.executable, "-c", vpn_smoke.PROBE], env={**base, **env}, cwd=REPO, capture_output=True,
                          text=True, timeout=60, check=True)  # fmt: skip
    return done.stdout + done.stderr


def test_probe_real_without_pricing_reports_false_and_leaks_nothing() -> None:
    out = _run_probe(LLM_BACKEND="real", FAST_MODEL="model-chua-co-gia", STRONG_MODEL="model-khac",
                     LLM_API_KEY=SECRET, LLM_BASE_URL="https://llm.example/v1")  # fmt: skip
    assert json.loads(out.strip().splitlines()[-1]) == {"backend": "real", "cap_usd": 38.0, "pricing_ok": False}
    assert SECRET not in out and "model-chua-co-gia" not in out and "llm.example" not in out


@pytest.mark.parametrize(("chat_model", "ok"), [
    ("", True),  # Q10: CHAT_MODEL trống → vai chat mượn model của fast/strong, không đòi thêm dòng giá
    ("deepseek-v4-pro", True),
    ("model-chua-co-gia", False),
])  # fmt: skip
def test_probe_real_checks_chat_model_pricing_only_when_set(chat_model: str, ok: bool) -> None:
    out = _run_probe(LLM_BACKEND="real", FAST_MODEL="deepseek-flash", STRONG_MODEL="deepseek-flash", CHAT_MODEL=chat_model,
                     LLM_API_KEY=SECRET, LLM_BASE_URL="https://llm.example/v1")  # fmt: skip
    assert json.loads(out.strip().splitlines()[-1]) == {"backend": "real", "cap_usd": 38.0, "pricing_ok": ok}
    assert "model-chua-co-gia" not in out and SECRET not in out


def test_probe_scripted_reads_config_cap() -> None:
    assert json.loads(_run_probe(LLM_BACKEND="scripted").strip()) == {"backend": "scripted", "cap_usd": 38.0,
                                                                       "pricing_ok": True}  # fmt: skip


def test_probe_bad_settings_prints_only_error_class() -> None:
    out = _run_probe(LLM_BACKEND=SECRET)
    assert json.loads(out.strip()) == {"error": "ValidationError"} and SECRET not in out


# ---- Bảng số liệu llm_calls -----------------------------------------------------------------------------------------


def _row(prompt: str, calls: int, parsed: int, valid: int, repaired: int, p95: float | None, cost: float) -> dict[str, Any]:
    return {"prompt_id": prompt, "calls": calls, "parsed": parsed, "valid_first": valid, "repaired": repaired,
            "cache_hits": calls - parsed, "errors": 0, "p95_ms": p95, "cost_usd": cost}  # fmt: skip


def test_render_stats_ratio_repairs_p95_cost() -> None:
    lines = vpn_smoke.render_stats([_row("b03_classify", 4, 4, 3, 1, 812.4, 0.0012),
                                    _row("b10_answer", 2, 1, 1, 0, None, 0.003)])  # fmt: skip
    assert lines[1] == "b03_classify | 4 | 3/4 | 1 | 0 | 0 | 812 | 0.001200"
    assert lines[2].endswith("| — | 0.003000")
    assert lines[-1] == "TỔNG: 6 lời gọi · JSON hợp lệ lần đầu 4/5 (80.0%) · sửa schema 1 · cost_usd 0.004200"


def test_render_stats_empty_has_no_division() -> None:
    assert vpn_smoke.render_stats([])[-1] == "TỔNG: 0 lời gọi · JSON hợp lệ lần đầu 0/0 (—) · sửa schema 0 · cost_usd 0.000000"


def test_stats_sql_only_rows_of_this_run() -> None:
    sql = vpn_smoke.STATS_SQL.format(marker=41)
    assert "WHERE call_id > 41" in sql and "percentile_cont(0.95)" in sql and "json_valid_first_try = false" in sql
