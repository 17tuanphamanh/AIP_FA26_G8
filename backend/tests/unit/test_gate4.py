"""`tests/stack/gate4.py` (PLAN-4d mục 11.5, phase4 7.1 P6, 7.4) — phần chạy được KHÔNG cần stack: thứ tự kịch bản, preset ScriptedLLM,
chốt an toàn (SLA=2 ở backend VÀ worker, in nhãn — không giá trị), cửa sổ nhắc, biên bản (TQ-17), làm nóng một lần (TQ-15). Kịch bản
thật: `make gate4 S=…` (thành viên chạy — `backend/tests/stack/README.md`)."""

import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.llm.providers.scripted import FAKE_TAG
from tests.stack import gate3, gate4
from tests.stack.gate2 import Line, Report, Shell
from tests.unit.test_gate3 import COMPOSE, FLAGS_OK, SECRET, FakeRun
from tests.unit.test_policy_rules_vpn import REPO

SCRIPTED = REPO / "config" / "scripted"
T0 = datetime(2026, 10, 2, 13, 0, tzinfo=UTC)


class SlaRun(FakeRun):
    """FakeRun của gate3 + trả lời dò SLA theo container và lệnh làm nóng."""

    def __init__(self, backend: str = "SLA=2\n", worker: str = "SLA=2\n", **kw: Any) -> None:
        super().__init__(**kw)
        self.sla = {"backend": backend, "worker": worker}

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        if cmd[-1] == gate4.SLA_PROBE:
            self.calls.append(cmd)
            return 0, self.sla[cmd[cmd.index("-T") + 1]]
        if cmd[-1] == gate3.WARM:
            self.calls.append(cmd)
            return 0, "embed_ms=5 rerank_ms=9\n"
        if cmd[:1] == ["git"]:
            self.calls.append(cmd)
            return 0, {"rev-parse": "abc1234\n", "status": " M a.py\n M b.py\n"}[cmd[1]]
        return super().__call__(cmd, stdin)


def _main(argv: list[str], run: FakeRun, **kw: Any) -> tuple[int, list[str]]:
    out: list[str] = []
    code = gate4.main(argv, run=run, env={"COMPOSE": COMPOSE}, echo=out.append, **kw)
    return code, out


# ---- Kịch bản + preset -------------------------------------------------------------------------------------------------------


def test_all_order_preflight_first_g4_12_last_every_spec_scenario() -> None:
    assert gate4.ALL[0] == "preflight" and gate4.ALL[-1] == "g4-12" and len(set(gate4.ALL)) == len(gate4.ALL)
    # phase4 7.4: g4-01…g4-12 TRỪ g4-08 (Q-4d-9 = B — manager bắt buộc MFA; x4 phủ ở e2e i5_x4 + unit x4)
    assert set(gate4.ALL) == {"preflight", *(f"g4-{n:02d}" for n in range(1, 13) if n != 8)}


def test_q4d9_no_manager_no_mfa_on_stack() -> None:
    """Q-4d-9 = B: gate4 không đăng nhập manager (quan.tm), không có OTP/ghi danh MFA, không preset cho người gửi là manager."""
    assert "quan.tm" not in gate4.USERS and all(who != "quan.tm" for _, who, _ in gate4.TICKET_PRESETS)
    source = Path(gate4.__file__).read_text(encoding="utf-8")
    assert "app.auth.mfa" not in source and "pyotp" not in source and '"otp"' not in source


def test_every_ticket_preset_has_all_prompts_and_device_in_sentence() -> None:
    default = yaml.safe_load((SCRIPTED / "default.yaml").read_text(encoding="utf-8"))
    assert {p for p, _, _ in gate4.TICKET_PRESETS} == {f.stem for f in SCRIPTED.glob("g4_*.yaml")}
    for preset_name, _, sentence in gate4.TICKET_PRESETS:
        preset = yaml.safe_load((SCRIPTED / f"{preset_name}.yaml").read_text(encoding="utf-8"))
        assert set(preset) == set(default), preset_name
        [intent] = preset["b03_classify"]["intents"]
        assert intent["slots"]["device_id"] in sentence and intent["action_hint"] == "renew_vpn_cert", preset_name
        assert preset["b02_injection_judge"]["is_attack"] is False
        assert FAKE_TAG.search(f"{sentence} [fake:{preset_name}]").group(1) == preset_name  # type: ignore[union-attr]


# ---- Chốt an toàn: SLA chỉ in nhãn --------------------------------------------------------------------------------------------


def _probe(env: dict[str, str]) -> str:
    return subprocess.run(["sh", "-c", gate4.SLA_PROBE], env={"PATH": "/usr/bin:/bin", **env}, capture_output=True,
                          text=True, check=True).stdout  # fmt: skip


@pytest.mark.parametrize(("value", "label"), [("2", "SLA=2"), (None, "SLA=0"), ("", "SLA=0"), ("5", "SLA=khac"),
                                              (SECRET, "SLA=khac")], ids=["2", "khong-dat", "rong", "5", "bi-mat"])  # fmt: skip
def test_sla_probe_prints_label_never_value(value: str | None, label: str) -> None:
    out = _probe({} if value is None else {"APPROVAL_SLA_MINUTES_DEV": value})
    assert out.splitlines() == [label] and SECRET not in out


def test_parse_sla_drops_unknown() -> None:
    assert [gate4.parse_sla(o) for o in ("SLA=2\n", "SLA=0", "SLA=khac", f"SLA={SECRET}", "", "X=2")] == ["2", "0", "khac", "?", "?",
                                                                                                    "?"]  # fmt: skip


@pytest.mark.parametrize(("backend", "worker"), [("SLA=0\n", "SLA=2\n"), ("SLA=2\n", "SLA=khac\n"), ("rác\n", "SLA=2\n")],
                         ids=["backend-chua-dat", "worker-khac", "dau-ra-la"])  # fmt: skip
def test_stops_before_http_when_sla_not_2_on_backend_or_worker(backend: str, worker: str) -> None:
    run = SlaRun(backend=backend, worker=worker)
    code, out = _main(["all"], run)
    assert code == 2 and any("APPROVAL_SLA_MINUTES_DEV" in line and "DỪNG" in line for line in out)
    assert not [c for c in run.calls if c[-1] == gate3.WARM]  # dừng TRƯỚC làm nóng, trước mọi HTTP
    assert all(SECRET not in line for line in out)


@pytest.mark.parametrize("flags", [FLAGS_OK.replace("FAKE_SCENARIO=0", "FAKE_SCENARIO=1"),
                                   FLAGS_OK.replace("LLM_BACKEND=scripted", "LLM_BACKEND=real")],
                         ids=["fake-scenario", "llm-that"])  # fmt: skip
def test_stops_like_gate3_on_fake_scenario_or_real_llm(flags: str) -> None:
    run = SlaRun(flags=flags)
    code, _ = _main(["g4-01"], run)
    assert code == 2 and not [c for c in run.calls if c[-1] == gate4.SLA_PROBE]


def test_unknown_scenario_and_bad_url_stop_before_commands() -> None:
    run = SlaRun()
    assert _main(["g4-99"], run)[0] == 2 and run.calls == []
    out: list[str] = []
    assert gate4.main(["g4-01"], run=run, env={"COMPOSE": COMPOSE, "GATE4_URL": "http://staging.example:8000"},
                      echo=out.append) == 2 and run.calls == []  # fmt: skip


# ---- Cửa sổ nhắc (g4-03) ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("offset_s", "ok"), [(None, False), (58, False), (59.5, True), (60, True), (75, True), (119.9, True),
                                              (120, False), (130, False)])  # fmt: skip
def test_reminder_window_never_early_never_after_deadline(offset_s: float | None, ok: bool) -> None:
    mark, deadline = T0 + timedelta(seconds=60), T0 + timedelta(seconds=120)
    at = None if offset_s is None else T0 + timedelta(seconds=offset_s)
    assert gate4.reminder_in_window(at, mark, deadline) is ok


# ---- Biên bản (TQ-17) ------------------------------------------------------------------------------------------------------------


def test_bienban_render_counts_blank_runner_and_machine_no_values() -> None:
    rows = gate4.outcomes([
        ("preflight", [Line(True, "-", "health", "ok")]),
        ("g4-01", [Line(True, "t1", "a", "ok"), Line(False, "t1", "b", "mong đợi 1, thấy 2")]),
    ])  # fmt: skip
    text = gate4.render_bienban(rows, run_id="r1", started=T0, ended=T0 + timedelta(minutes=9), commit="abc1234", dirty=2)
    assert "| preflight | 1 | 0 |  |" in text and "| g4-01 | 1 | 1 | FAIL t1 b: mong đợi 1, thấy 2 |" in text
    assert "`abc1234`" in text and "đang sửa: 2" in text and "KHÔNG ĐẠT (1 FAIL)" in text
    assert "Người chạy (không làm chính): ______" in text and "Máy (hãng, CPU, RAM, hệ điều hành): ______" in text


def _fake_scenarios(monkeypatch: pytest.MonkeyPatch, ok: bool = True) -> list[str]:
    ran: list[str] = []

    def make(name: str) -> Callable[[gate4.Ctx], None]:
        def scenario(ctx: gate4.Ctx) -> None:
            ran.append(name)
            ctx.report.check("-", name, ok, "x", "x")

        return scenario

    monkeypatch.setattr(gate4, "SCENARIOS", {n: make(n) for n in gate4.ALL})
    monkeypatch.setattr(gate3, "warnings", lambda ctx, flags: None)  # không HTTP thật
    return ran


def test_all_writes_bienban_and_warms_once_before_first(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ran = _fake_scenarios(monkeypatch)
    run = SlaRun()
    code, out = _main(["all"], run, out_dir=tmp_path)
    assert code == 0 and ran == gate4.ALL
    warm_at = [i for i, c in enumerate(run.calls) if c[-1] == gate3.WARM]
    assert len(warm_at) == 1
    [path] = list(tmp_path.glob("bienban-gate4-*.md"))
    text = path.read_text(encoding="utf-8")
    assert "ĐẠT (0 FAIL)" in text and "`abc1234`" in text and "đang sửa: 2" in text
    assert all(f"| {n} | 1 | 0 |" in text for n in gate4.ALL)
    assert any("APPROVAL_SLA_MINUTES_DEV: backend=2, worker=2" in line for line in out)
    assert SECRET not in text


def test_single_scenario_writes_no_bienban(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_scenarios(monkeypatch)
    code, _ = _main(["g4-01"], SlaRun(), out_dir=tmp_path)
    assert code == 0 and list(tmp_path.glob("bienban-gate4-*.md")) == []


def test_failed_scenario_is_reported_in_bienban(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_scenarios(monkeypatch, ok=False)
    code, _ = _main(["all"], SlaRun(), out_dir=tmp_path)
    text = next(tmp_path.glob("bienban-gate4-*.md")).read_text(encoding="utf-8")
    assert code == 1 and f"KHÔNG ĐẠT ({len(gate4.ALL)} FAIL)" in text


def test_scenario_exception_is_fail_and_run_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    out: list[str] = []
    ctx = gate4.Ctx(shell=Shell(COMPOSE.split(), run=SlaRun(), echo=out.append), http=None,  # type: ignore[arg-type]
                    report=Report(echo=out.append), password="x")  # fmt: skip
    ran: list[str] = []

    def boom(ctx: gate4.Ctx) -> None:
        raise KeyError("approval_id")

    monkeypatch.setattr(gate4, "SCENARIOS", {"g4-01": boom, "g4-12": lambda c: ran.append("g4-12")})
    stopped, per = gate4.run_scenarios(ctx, ["g4-01", "g4-12"])
    assert stopped is None and ran == ["g4-12"]  # một kịch bản ném lỗi → FAIL, các kịch bản sau vẫn chạy
    assert [(n, [line.ok for line in lines]) for n, lines in per] == [("g4-01", [False]), ("g4-12", [])]
    assert any(line.startswith("FAIL - g4-01 dừng giữa chừng") for line in out)


T1, T2 = "0b5c1f6e-1111-4c00-8000-000000000001", "0b5c1f6e-2222-4c00-8000-000000000002"
CLEAN = "audit_check: nguồn app_rw (READ ONLY)\nKẾT LUẬN: 0 thiếu, 0 bí mật (2 ticket)\naudit_check_exit=0\n"
MISSING = ("audit_check: nguồn app_rw (READ ONLY)\n| ticket | điểm thiếu | trường thiếu |\n|---|---|---|\n"
           f"| {T2} | 5 | approver_id (dòng 41) |\nKẾT LUẬN: 1 thiếu, 0 bí mật (2 ticket)\naudit_check_exit=1\n")


class AuditRun(SlaRun):
    """Trả lời lệnh audit_check bọc `sh -c` của g4-12 (`audit`) và `compose logs` (`logs`: (mã, đầu ra))."""

    def __init__(self, audit: str = CLEAN, logs: tuple[int, str] = (0, "backend-1 | INFO ok\n")) -> None:
        super().__init__()
        self.audit, self.logs = audit, logs

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        if gate4.AUDIT_SH in cmd:
            self.calls.append(cmd)
            return 0, self.audit
        if "logs" in cmd:
            self.calls.append(cmd)
            return self.logs
        return super().__call__(cmd, stdin)


def _g4_12(run: AuditRun, tickets: tuple[str, ...] = (T1, T2)) -> tuple[gate4.Ctx, list[str]]:
    out: list[str] = []
    ctx = gate4.Ctx(shell=Shell(COMPOSE.split(), run=run, echo=out.append), http=None,  # type: ignore[arg-type]
                    report=Report(echo=out.append), password="x")  # fmt: skip
    ctx.owner.update({t: "chau.hm" for t in tickets})
    gate4.g4_12(ctx)
    return ctx, out


def test_audit_result_keeps_table_lines_and_exit_code() -> None:
    code, lines = gate4.audit_result(MISSING + "rác\n")
    assert code == 1 and lines[0].startswith("| ticket") and lines[-1].startswith("KẾT LUẬN: 1 thiếu")
    assert not any("nguồn" in line or "rác" in line for line in lines)
    assert gate4.audit_result("không có dòng mã\n") == (None, [])


def test_q4d10_g4_12_audits_exactly_this_runs_tickets_not_since() -> None:
    """Q-4d-10 = A: truyền ĐÚNG id ticket lần chạy đã tạo (không `--since`); sạch → PASS; quét log vẫn `--since`."""
    run = AuditRun()
    ctx, out = _g4_12(run)
    [audit] = [c for c in run.calls if gate4.AUDIT_SH in c]
    assert audit[audit.index(gate4.AUDIT_SH) + 2:] == [T1, T2] and "--since" not in audit
    assert any("--since" in c for c in run.calls if "logs" in c)
    assert [line.ok for line in ctx.report.lines] == [True, True]
    assert not any(gate4.AUDIT_SH in line for line in out)  # in nhãn lệnh, không in đoạn sh


def test_q4d10_g4_12_missing_prints_whole_table_no_values() -> None:
    """Mã 1 → FAIL + in NGUYÊN bảng (dòng `| …`, `KẾT LUẬN`) — bảng chỉ có ticket/điểm/tên trường."""
    ctx, out = _g4_12(AuditRun(audit=MISSING))
    assert [line.ok for line in ctx.report.lines] == [False, True]
    assert any(f"| {T2} | 5 | approver_id (dòng 41) |" in line for line in out)
    assert any("KẾT LUẬN: 1 thiếu, 0 bí mật" in line for line in out)


def test_q4d10_g4_12_no_ticket_in_this_run_fails_clearly() -> None:
    """Chạy lẻ S=g4-12 (chưa tạo ticket) → FAIL rõ lý do, KHÔNG gọi audit_check (không xanh giả)."""
    run = AuditRun()
    ctx, _ = _g4_12(run, tickets=())
    assert ctx.report.lines[0].ok is False and "chưa tạo ticket nào" in ctx.report.lines[0].render()
    assert not [c for c in run.calls if gate4.AUDIT_SH in c]


def test_g4_12_logs_command_failure_prints_first_line_only() -> None:
    """Soát 4d DỪNG 2 (NGHI-6): `compose logs` lỗi → FAIL chỉ dòng đầu, KHÔNG in đuôi đầu ra (chính là log cần quét)."""
    ctx, out = _g4_12(AuditRun(logs=(1, f"backend-1 | mật khẩu là {SECRET}\n")))
    assert [line.ok for line in ctx.report.lines] == [True, False]
    assert all(SECRET not in line for line in out)


def test_audit_sh_passes_ids_verbatim_and_captures_exit_code(tmp_path: Path) -> None:
    """Chạy CHÍNH `AUDIT_SH` với `python` giả: id đi nguyên vẹn qua `"$@"`, stderr gộp vào stdout, mã thoát của audit_check được in."""
    stub = tmp_path / "python"
    stub.write_text('#!/bin/sh\necho "args:$*" >&2\nexit 1\n', encoding="utf-8")
    stub.chmod(0o755)
    done = subprocess.run(["sh", "-c", gate4.AUDIT_SH, "sh", T1, T2], env={"PATH": f"{tmp_path}:/usr/bin:/bin"},
                          capture_output=True, text=True, check=True)  # fmt: skip
    assert f"args:-m app.audit.check {T1} {T2}" in done.stdout and gate4.audit_result(done.stdout)[0] == 1
