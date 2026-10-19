"""G2 mốc 3 — CLI + vòng chạy (`app.eval.runner`) trên stack giả `SimStack` (không Docker, đồng hồ giả).

Mọi giá trị dữ liệu tổng hợp (câu, id, họ, gold, tên file, ticket_id) chứa `SENTINEL_…`: chế độ mặc định chỉ in 7 dòng tổng hợp —
stdout/stderr KHÔNG được có chuỗi canh nào. `--per-case` in thêm `scenario_id` (chỉ `SENTINEL_ID_…`), vẫn không câu/họ/gold/ticket.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.eval import runner
from app.eval.predictions import load_predictions
from app.eval.runner import Deps, main
from app.eval.stack import Clock
from tests.unit.eval.fake_stack import GIT_SHA, FakeClock, SimStack

PW = "SENTINEL_PW"
ENV = {"EVAL_PASSWORD": PW}
SUMMARY = [
    r"eval run [0-9a-f]{12} strategy=hybrid split=test timeout_s=\d+",
    r"scenarios: loaded=\d+",
    r"warmup: rounds=\d+ first_ms=\d+ last_ms=\d+",
    r"outcomes: done=\d+ timeout=\d+ multi_leaf=\d+ error=\d+",
    r"records: written=\d+ route_none=\d+ calibrated_prob_nonnull=\d+",
    r"elapsed_s=\d+(\.\d+)?",
    r"files: predictions\.jsonl outcomes\.jsonl manifest\.json",
]
NOT_IN_PER_CASE = ("SENTINEL_TXT", "SENTINEL_FAM", "SENTINEL_DOC", "SENTINEL_TID", "SENTINEL_USER", "SENTINEL_PW",
                   "SENTINEL_FILE", "SENTINEL_FACTOR", "SENTINEL_ERR")  # fmt: skip


def scn(n: int, flow: str, *answers: str, decision: str | None = "approve", **over: Any) -> dict[str, Any]:
    gold: dict[str, Any] = {"intents": ["vpn"], "expected_route": "HITL", "gold_doc_ids": [f"SENTINEL_DOC_{n}"]}
    if decision is not None:
        gold["approver_decision"] = decision
    data: dict[str, Any] = {"id": f"SENTINEL_ID_{n}", "family": f"SENTINEL_FAM_{n}", "requester": "SENTINEL_USER",
                            "turns": [f"SENTINEL_TXT_{n} flow={flow}", *answers], "gold": gold}  # fmt: skip
    data.update(over)
    return data


def write_scenarios(d: Path, *items: dict[str, Any]) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    for i, item in enumerate(items):
        (d / f"SENTINEL_FILE_{i:02d}.yaml").write_text(yaml.safe_dump(item, allow_unicode=True), encoding="utf-8")
    return d


class Run:
    def __init__(self, tmp: Path, *items: dict[str, Any], sim: SimStack | None = None) -> None:
        self.tmp = tmp
        self.scen = write_scenarios(tmp / "scen", *items)
        self.outdir = tmp / "out"
        self.clock = FakeClock()
        self.sim = sim or SimStack(self.clock)
        self.sim.clock = self.clock
        self.out: list[str] = []
        self.err: list[str] = []
        self.deps_made = 0
        self.git_dirty = False

    def make_deps(self, url: str) -> Deps:
        self.deps_made += 1
        return Deps(backend=self.sim, http=self.sim.client(), clock=Clock(self.clock.monotonic, self.clock.sleep),
                    git_commit=GIT_SHA, now=lambda: datetime(2026, 10, 19, 3, 0, tzinfo=UTC), git_dirty=self.git_dirty)  # fmt: skip

    def __call__(self, *extra: str, env: dict[str, str] | None = None, timeout: str | None = "30",
                 base: bool = True) -> int:  # fmt: skip
        argv = ["--scenarios", str(self.scen), "--out", str(self.outdir)] if base else []
        argv += ["--strategy", "hybrid", "--split", "test"] if base else []
        if timeout is not None and base:
            argv += ["--timeout-s", timeout]
        argv += list(extra)
        return main(argv, env=ENV if env is None else env, make_deps=self.make_deps, out=self.out.append, err=self.err.append)

    @property
    def text(self) -> str:
        return "\n".join(self.out + self.err)

    def manifest(self) -> dict[str, Any]:
        return dict(json.loads((self.outdir / "manifest.json").read_text(encoding="utf-8")))

    def outcomes(self) -> list[dict[str, Any]]:
        return [json.loads(x) for x in (self.outdir / "outcomes.jsonl").read_text(encoding="utf-8").splitlines()]

    def paths(self) -> list[str]:
        return [path for _, path, _ in self.sim.api.calls]

    def no_files(self) -> bool:
        return not any((self.outdir / f).exists() for f in ("predictions.jsonl", "outcomes.jsonl", "manifest.json"))


def count(text: str, key: str) -> int:
    m = re.search(rf"\b{key}=(\d+)", text)
    assert m is not None, key
    return int(m.group(1))


# ---- CLI / preflight --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("strategy", ["rule_only", "manual", "hybrid_guarded"])
def test_cli_strategy_rejects(tmp_path: Path, strategy: str) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    argv = ["--scenarios", str(r.scen), "--out", str(r.outdir), "--strategy", strategy, "--split", "test", "--timeout-s", "30"]
    assert main(argv, env=ENV, make_deps=r.make_deps, out=r.out.append, err=r.err.append) == 2
    assert r.deps_made == 0


@pytest.mark.parametrize("timeout", [None, "0", "-5", "abc"])
def test_cli_timeout_required(tmp_path: Path, timeout: str | None) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r(timeout=timeout) == 2
    assert r.deps_made == 0 and r.no_files()


@pytest.mark.parametrize("env", [{}, {"EVAL_PASSWORD": ""}, {"EVAL_PASSWORD": "  "}])
def test_password_missing_exit2(tmp_path: Path, env: dict[str, str]) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r(env=env) == 2
    assert r.deps_made == 0 and r.no_files() and r.sim.api.calls == []
    assert "EVAL_PASSWORD" in r.text


def test_password_from_env_used(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "clarify", "SENTINEL_TXT_ans"))
    assert r() == 0
    logins = [body for method, path, body in r.sim.api.calls if path == "/api/auth/login"]
    assert logins and all(b["password"] == PW for b in logins)
    assert {b["username"] for b in logins} == {"SENTINEL_USER", "ha.lt"}


@pytest.mark.parametrize(("over", "app_env"), [
    ({"strategy": "llm_only"}, "dev"), ({"eval_mode": False}, "dev"), ({"llm_cache_mode": "default"}, "dev"),
    ({"app_git_sha": "deadbeef"}, "dev"), ({}, "prod"), ({}, None),
])  # fmt: skip
def test_preflight_refuses(tmp_path: Path, over: dict[str, Any], app_env: str | None) -> None:
    sim = SimStack(FakeClock(), info_over=over, app_env_value=app_env)
    r = Run(tmp_path, scn(1, "direct"), sim=sim)
    assert r() == 2
    assert r.no_files() and "/api/tickets" not in r.paths()
    assert r.text.startswith("DỪNG:") and "SENTINEL" not in r.text


def test_preflight_health_down(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), sim=SimStack(FakeClock(), health_runtime="down"))
    assert r() == 2 and r.no_files()


def test_preflight_git_sha_unset_warns(tmp_path: Path) -> None:
    """APP_GIT_SHA không đặt trong container → chạy tiếp, cảnh báo stderr, manifest `commit_verified=false`."""
    r = Run(tmp_path, scn(1, "direct"), sim=SimStack(FakeClock(), info_over={"app_git_sha": None}))
    assert r() == 0
    assert r.manifest()["commit_verified"] is False
    assert any("APP_GIT_SHA" in e for e in r.err)


def test_sla_warning(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), sim=SimStack(FakeClock(), info_over={"approval_sla_minutes_dev": 30}))
    assert r(timeout="600") == 0
    assert any("SLA" in e for e in r.err)
    assert len(r.out) == 7


@pytest.mark.parametrize("sla", [None, "", 0])
def test_preflight_sla_required(tmp_path: Path, sla: Any) -> None:
    """G2-Q6 (Tuấn Anh 19/10): harness chạy với APPROVAL_SLA_MINUTES_DEV=2 → ca ignore ra E6 trước timeout. Container không đặt / rỗng →
    DỪNG mã 2, lý do cố định, không tạo ticket, không ghi file."""
    r = Run(tmp_path, scn(1, "direct"), sim=SimStack(FakeClock(), info_over={"approval_sla_minutes_dev": sla}))
    assert r() == 2
    assert r.no_files() and "/api/tickets" not in r.paths()
    assert r.out[-1].startswith("DỪNG:") and "APPROVAL_SLA_MINUTES_DEV" in r.out[-1]


@pytest.mark.parametrize("sla", [2, 30])
def test_manifest_sla_recorded(tmp_path: Path, sla: int) -> None:
    r = Run(tmp_path, scn(1, "direct"), sim=SimStack(FakeClock(), info_over={"approval_sla_minutes_dev": sla}))
    assert r(timeout="3000") == 0
    assert r.manifest()["approval_sla_minutes_dev"] == sla


def test_sla_no_warning_when_timeout_large(tmp_path: Path) -> None:
    """Đối chứng cho `test_sla_warning`: SLA 2 phút, timeout 300 giây (≥ 2·60 + 60) → không cảnh báo."""
    r = Run(tmp_path, scn(1, "direct"), sim=SimStack(FakeClock(), info_over={"approval_sla_minutes_dev": 2}))
    assert r(timeout="300") == 0
    assert not any("SLA" in e for e in r.err)


def test_run_id_mismatch_exit2(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r("--run-id", "000000000000") == 2
    assert r.no_files() and "/api/tickets" not in r.paths()


def test_run_id_match_ok(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r() == 0
    rid = r.manifest()["run_id"]
    r2 = Run(tmp_path / "again", scn(1, "direct"))
    assert r2("--run-id", rid) == 0


def test_out_inside_scenarios_refused(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    r.outdir = r.scen / "out"
    assert r() == 2 and r.deps_made == 0


def test_out_existing_files_refused(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    r.outdir.mkdir()
    (r.outdir / "predictions.jsonl").write_text("cu\n", encoding="utf-8")
    assert r() == 2 and r.deps_made == 0
    assert (r.outdir / "predictions.jsonl").read_text(encoding="utf-8") == "cu\n"


# ---- luồng kịch bản ---------------------------------------------------------------------------------------------------


def test_flow_clarify_approve_resolve(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "clarify", "SENTINEL_TXT_ans"))
    assert r() == 0
    [rec] = load_predictions(r.outdir / "predictions.jsonl")
    assert (rec.scenario_id, rec.route, rec.final_state, rec.resolution_path) == ("SENTINEL_ID_1", "HITL", "S_RESOLVED", "approved")
    assert rec.has_approval is True and rec.clarification_turns == 1
    assert [o["outcome"] for o in r.outcomes()] == ["done"]
    assert ("POST", "/api/tickets/SENTINEL_TID-1/messages", {"text": "SENTINEL_TXT_ans"}) in r.sim.api.calls
    assert ("POST", "/api/tickets/SENTINEL_TID-1/confirm", {"confirmed": True}) in r.sim.api.calls


def test_flow_reject(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "reject", decision="reject"))
    assert r() == 0
    [rec] = load_predictions(r.outdir / "predictions.jsonl")
    assert (rec.final_state, rec.resolution_path) == ("S_REJECTED", "rejected")


def test_flow_ignore_waits_for_worker(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "ignore", decision="ignore"))
    assert r() == 0
    [rec] = load_predictions(r.outdir / "predictions.jsonl")
    assert (rec.final_state, rec.exit_code) == ("S_ESCALATED", "E6")
    assert not any("/decision" in p for p in r.paths())


def test_flow_default_decision_counted(tmp_path: Path) -> None:
    """TODO(G2-Q6): gold không có approver_decision mà tới chờ duyệt → approve + đếm `approver_default`."""
    r = Run(tmp_path, scn(1, "clarify", "SENTINEL_TXT_ans", decision=None))
    assert r() == 0
    assert r.manifest()["counts"]["approver_default"] == 1


def test_timeout_records_open_ticket(tmp_path: Path) -> None:
    """Hết câu khi B11 còn hỏi → chờ tới hạn → `timeout`; bản ghi vẫn ghi, ticket còn mở."""
    r = Run(tmp_path, scn(1, "stuck"), scn(2, "direct"))
    assert r() == 1
    recs = {x.scenario_id: x for x in load_predictions(r.outdir / "predictions.jsonl")}
    assert recs["SENTINEL_ID_1"].final_state is None and recs["SENTINEL_ID_1"].clarification_turns == 1
    assert [o["outcome"] for o in r.outcomes()] == ["timeout", "done"]
    assert r.outcomes()[0]["elapsed_s"] >= 30
    assert count(r.text, "timeout") == 1 and count(r.text, "done") == 1


def test_multi_leaf_skipped(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "multi"), scn(2, "direct"))
    assert r() == 0
    assert [x.scenario_id for x in load_predictions(r.outdir / "predictions.jsonl")] == ["SENTINEL_ID_2"]
    assert [o["outcome"] for o in r.outcomes()] == ["multi_leaf", "done"]
    assert count(r.text, "multi_leaf") == 1 and count(r.text, "written") == 1


def test_error_before_ticket(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "boom"), scn(2, "direct"))
    assert r() == 1
    o = r.outcomes()
    assert (o[0]["outcome"], o[0]["ticket_id"], o[0]["error_type"]) == ("error", None, "StackError")
    assert count(r.text, "error") == 1 and count(r.text, "written") == 1


@pytest.mark.parametrize("flags", [(), ("--per-case",)])
def test_error_message_not_printed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flags: tuple[str, ...]) -> None:
    def boom(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("SENTINEL_ERR thông điệp có dữ liệu")

    monkeypatch.setattr(runner, "collect", boom)
    r = Run(tmp_path, scn(1, "direct"))
    assert r(*flags) == 1
    assert "SENTINEL_ERR" not in r.text
    assert r.outcomes()[0]["error_type"] == "ValueError"


@pytest.mark.parametrize(("flow", "reason"), [("badstrategy", "strategy"), ("nostrategy", "thiếu khoá strategy")])
def test_strategy_abort_exit2(tmp_path: Path, flow: str, reason: str) -> None:
    r = Run(tmp_path, scn(1, "direct"), scn(2, flow))
    assert r() == 2
    assert r.no_files()
    assert r.out[-1].startswith("DỪNG:") and reason in r.out[-1]
    assert "SENTINEL" not in r.text


def test_strategy_abort_messages_differ(tmp_path: Path) -> None:
    a = Run(tmp_path / "a", scn(1, "badstrategy"))
    b = Run(tmp_path / "b", scn(1, "nostrategy"))
    assert a() == 2 and b() == 2
    assert a.out[-1] != b.out[-1]


def test_written_file_roundtrip(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), scn(2, "clarify", "SENTINEL_TXT_a"), scn(3, "calib"))
    assert r() == 0
    recs = load_predictions(r.outdir / "predictions.jsonl")
    assert [x.scenario_id for x in recs] == ["SENTINEL_ID_1", "SENTINEL_ID_2", "SENTINEL_ID_3"]
    assert {x.run_id for x in recs} == {r.manifest()["run_id"]}
    assert len(r.outcomes()) == 3


def test_calibrated_prob_nonnull_counted(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "calib"), scn(2, "direct"))
    assert r() == 0
    assert r.manifest()["counts"]["calibrated_prob_nonnull"] == 1
    assert count(r.text, "calibrated_prob_nonnull") == 1


def test_prob_method_mismatch_counted(tmp_path: Path) -> None:
    """`p_method` thuộc chính sách — harness không đọc; so `--prob-method` với cột `p_method` của bản ghi sau khi chạy."""
    r = Run(tmp_path, scn(1, "clarify", "SENTINEL_TXT_a"))
    assert r("--prob-method", "sampling_k5") == 0
    assert r.manifest()["counts"]["p_method_mismatch"] == 1
    assert any("p_method" in e for e in r.err)


# ---- warm-up ----------------------------------------------------------------------------------------------------------


def test_warmup_before_first_ticket(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r("--warmup-rounds", "4") == 0
    paths = r.paths()
    assert paths.index("warmup") < paths.index("/api/tickets")
    assert ("EXEC", "warmup", 4) in r.sim.api.calls
    assert r.manifest()["warmup"] == {"rounds": 4, "first_ms": 120, "last_ms": 40}


def test_warmup_fail_aborts(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), sim=SimStack(FakeClock(), warmup_fails=True))
    assert r() == 2
    assert "/api/tickets" not in r.paths() and r.no_files()


# ---- in ra ------------------------------------------------------------------------------------------------------------


def all_flows() -> list[dict[str, Any]]:
    return [scn(1, "direct"), scn(2, "clarify", "SENTINEL_TXT_a"), scn(3, "reject", decision="reject"),
            scn(4, "ignore", decision="ignore"), scn(5, "stuck"), scn(6, "multi"), scn(7, "calib"), scn(8, "boom")]  # fmt: skip


def test_default_output_aggregate_only(tmp_path: Path) -> None:
    r = Run(tmp_path, *all_flows())
    assert r() == 1
    assert len(r.out) == 7
    for line, pattern in zip(r.out, SUMMARY, strict=True):
        assert re.fullmatch(pattern, line), line
    assert "SENTINEL" not in r.text
    assert "route" not in r.text.replace("route_none", "")
    assert (count(r.text, "done"), count(r.text, "timeout"), count(r.text, "multi_leaf"), count(r.text, "error")) == (5, 1, 1, 1)


def test_per_case_output(tmp_path: Path) -> None:
    r = Run(tmp_path, *all_flows())
    assert r("--per-case") == 1
    for n in range(1, 9):
        assert any(line.startswith(f"SENTINEL_ID_{n} ") for line in r.out)
    assert not any(s in r.text for s in NOT_IN_PER_CASE)
    assert all(re.fullmatch(p, x) for p, x in zip(SUMMARY, r.out[-7:], strict=True))


def test_harness_never_calls_policy_api(tmp_path: Path) -> None:
    """Rev 27: harness KHÔNG gọi GET /api/policy hay endpoint chính sách nào — soát mọi đường dẫn một lượt chạy đủ luồng."""
    r = Run(tmp_path, *all_flows())
    r("--per-case")
    paths = r.paths()
    assert "/api/tickets" in paths and "/api/health" in paths  # đối chứng: có ghi được đường dẫn
    assert not [p for p in paths if "/policy" in p]


# ---- nạp kịch bản qua CLI ---------------------------------------------------------------------------------------------


def test_cli_load_error_no_file_name(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), scn(2, "direct", bogus="SENTINEL_TXT_x"))
    assert r() == 2
    assert r.deps_made == 0 and r.no_files()
    assert "SENTINEL" not in r.text
    assert "file #2/2: không hợp lệ (bogus)" in r.out
    r2 = Run(tmp_path / "pc", scn(1, "direct"), scn(2, "direct", bogus="SENTINEL_TXT_x"))
    assert r2("--per-case") == 2
    assert "SENTINEL_FILE_01.yaml: không hợp lệ (bogus)" in r2.out


def test_cli_check_only(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), scn(2, "direct"))
    assert r("--check-only", env={}, timeout=None) == 0
    assert r.out == ["scenarios: loaded=2 errors=0"]
    assert r.deps_made == 0 and r.no_files()


def test_cli_check_only_errors(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"), scn(2, "direct", family=None), scn(3, "direct", bogus=1))
    assert r("--check-only", env={}, timeout=None) == 2
    assert r.out == ["scenarios: loaded=1 errors=2", "file #2/3: không hợp lệ (family)", "file #3/3: không hợp lệ (bogus)"]
    assert "SENTINEL" not in r.text


def test_cli_check_only_allow_extra(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct", bogus=1))
    assert r("--check-only", "--allow-extra-fields", env={}, timeout=None) == 0
    assert r.out == ["scenarios: loaded=1 errors=0", "ignored_fields=1"]


def test_cli_ignored_fields_manifest(tmp_path: Path) -> None:
    data = scn(1, "direct", bogus="SENTINEL_TXT_x")
    data["gold"]["leaves"] = ["SENTINEL_TXT_y"]
    r = Run(tmp_path, data, scn(2, "direct", bogus=2))
    assert r("--allow-extra-fields") == 0
    assert r.manifest()["ignored_fields"] == {"allowed": True, "count": 3, "paths": ["bogus", "gold.leaves"]}
    assert len(r.out) == 8 and r.out[-1] == "ignored_fields=3"
    assert "SENTINEL" not in r.text


def test_manifest_without_flag(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r() == 0
    assert r.manifest()["ignored_fields"] == {"allowed": False, "count": 0, "paths": []}


# ---- manifest ---------------------------------------------------------------------------------------------------------

MANIFEST_KEYS = {
    "run_id", "config", "git_commit", "git_dirty", "app_git_sha", "commit_verified", "dataset_sha256", "dataset_file_count", "strategy",
    "split", "timeout_s", "enable_proactive_diagnosis", "llm_cache_mode", "clf_mode", "policy_sha256", "llm_backend",
    "started_at", "finished_at", "host", "warmup", "counts", "ignored_fields", "unavailable", "approval_sla_minutes_dev",
    "b2_tau", "b2_judge_model", "injection_clf_sha", "intent_clf_sha", "rate_limits",
}  # fmt: skip
LATER = ("b2_tau", "b2_judge_model", "injection_clf_sha", "intent_clf_sha", "rate_limits")


def test_manifest_keys(tmp_path: Path) -> None:
    r = Run(tmp_path, scn(1, "direct"))
    assert r() == 0
    m = r.manifest()
    assert set(m) == MANIFEST_KEYS
    assert all(m[k] is None for k in LATER) and set(LATER) <= set(m["unavailable"])
    assert (m["strategy"], m["split"], m["timeout_s"], m["clf_mode"], m["git_commit"]) == ("hybrid", "test", 30, "shadow", GIT_SHA)
    assert m["commit_verified"] is True and m["policy_sha256"] == "ab" * 32
    assert m["git_dirty"] is False
    assert m["counts"] == {"loaded": 1, "done": 1, "timeout": 0, "multi_leaf": 0, "error": 0, "written": 1, "route_none": 0,
                           "calibrated_prob_nonnull": 0, "approver_default": 0, "p_method_mismatch": 0}  # fmt: skip
    assert "SENTINEL" not in json.dumps(m)


@pytest.mark.parametrize("dirty", [True, False])
def test_manifest_git_dirty(tmp_path: Path, dirty: bool) -> None:
    """Dương 19/10: manifest ghi `git_dirty` (cây có thay đổi / file untracked) — chỉ cờ, không tên file."""
    r = Run(tmp_path, scn(1, "direct"))
    r.git_dirty = dirty
    assert r() == 0
    assert r.manifest()["git_dirty"] is dirty


def test_real_deps_git_dirty_from_porcelain(monkeypatch: pytest.MonkeyPatch) -> None:
    """`real_deps`: `git_dirty` = `git status --porcelain` có dòng; manifest không chép tên file."""
    seen: list[tuple[str, ...]] = []

    def fake_git(*args: str) -> str:
        seen.append(args)
        return {"rev-parse": GIT_SHA + "\n", "status": "?? SENTINEL_FILE_x.py\n"}[args[0]]

    monkeypatch.setattr(runner, "_git", fake_git)
    deps = runner.real_deps("http://127.0.0.1:8000")
    assert (deps.git_commit, deps.git_dirty) == (GIT_SHA, True)
    assert ("status", "--porcelain") in seen
    monkeypatch.setattr(runner, "_git", lambda *a: GIT_SHA if a[0] == "rev-parse" else "")
    assert runner.real_deps("http://127.0.0.1:8000").git_dirty is False
