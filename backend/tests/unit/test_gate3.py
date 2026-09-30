"""`tests/stack/gate3.py` (PLAN-3h S15) — phần chạy được không cần stack: route mong đợi theo giờ (đối chiếu với CHÍNH policy
engine + `config/policy.json`), chốt an toàn (APP_ENV, LLM_BACKEND=scripted, không FAKE_SCENARIO), kiểm biến môi trường chỉ
có/không (không bao giờ in giá trị), tc28 luôn bật lại Qdrant, preset `config/scripted/tc*.yaml` khớp KB fixture. Kịch bản
thật chạy tay: `make gate3 S=…`."""

import hashlib
import subprocess
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast

import httpx
import pytest
import yaml
from app.core.clock import FakeClock
from app.llm.providers.scripted import FAKE_TAG
from app.rag.ingest.chunker import chunk_doc
from app.rag.ingest.loader import load_kb
from app.rag.token_counter import LocalTokenizerCounter
from app.risk.context import build_ctx
from app.risk.policy_engine import evaluate
from app.settings import get_policy
from tests.fakes.kb import FIXTURE_KB, KB_TEST_NOW
from tests.fakes.tokenizer import require_bge_tokenizer
from tests.stack import gate3
from tests.stack.gate2 import Report, Shell, StackError
from tests.unit.test_policy_rules_vpn import (
    F_NV001_LAP0342,
    F_NV002_PC0977,
    NGOAI_GIO,
    NV001,
    NV002,
    REPO,
    TRONG_GIO,
    VN,
    _action,
)

COMPOSE = "docker compose --env-file .env"
SECRET = "s3cr3t-" + "executor-token-value"  # ghép lúc chạy (gitleaks)
FLAGS_OK = "SVC_EXECUTOR_TOKEN=1\nFAKE_SCENARIO=0\nFAKE_APPROVER_ID=1\nLLM_BACKEND=scripted\n"


class FakeRun:
    """Thay subprocess: ghi mọi lệnh; trả lời theo loại lệnh (printenv APP_ENV, dò biến, gọi mock, psql)."""

    def __init__(self, app_env: str = "dev", flags: str = FLAGS_OK, sql: Callable[[str], str] | None = None) -> None:
        self.app_env = app_env
        self.flags = flags
        self.sql = sql or (lambda _: "0")
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        self.calls.append(cmd)
        if cmd[-2:] == ["printenv", "APP_ENV"]:
            return 0, f"{self.app_env}\n"
        if cmd[-1] == gate3.ENV_PROBE:
            return 0, self.flags
        if "postgres" in cmd:
            return 0, self.sql(stdin or "")
        return 0, "0\n"

    def tails(self) -> list[str]:
        return [" ".join(c[len(COMPOSE.split()):]) for c in self.calls]


def _main(argv: list[str], run: FakeRun, **env: str) -> tuple[int, list[str]]:
    out: list[str] = []
    code = gate3.main(argv, run=run, env={"COMPOSE": COMPOSE, **env}, echo=out.append)
    return code, out


# ---- Route mong đợi theo giờ (Q-3h-4) --------------------------------------------------------------------------------


def _route(decision: str | None) -> str:
    return {"allow": "AUTO", "approval_required": "HITL"}[decision or ""]


@pytest.mark.parametrize("now", [TRONG_GIO, NGOAI_GIO], ids=["10h", "20h"])
@pytest.mark.parametrize(("tc", "requester", "action"), [
    ("tc02", NV001, _action("renew_vpn_cert", "LAP-0342", "nv001", F_NV001_LAP0342)),
    ("tc06", NV001, _action("renew_vpn_cert", "LAP-0342", "nv001", F_NV001_LAP0342)),
    ("tc09", NV002, _action("reissue_vpn_access", "PC-0977", "nv002", F_NV002_PC0977)),
])  # fmt: skip
def test_expected_risk_equals_real_policy_engine(tc: str, requester: Any, action: Any, now: datetime) -> None:
    """Kỳ vọng của gate3 không được trôi khỏi luật thật: đi đúng đường M5 (build_ctx → evaluate) trên config/policy.json."""
    state = {"intended_action": action, "requester_context": requester, "ctx_flags": {}}
    verdict = evaluate(action, build_ctx(state, now, get_policy().business_hours))
    want = gate3.expected_risk(tc, gate3.within_business_hours(now, get_policy().business_hours))
    assert (verdict.rule_id, _route(verdict.decision), frozenset(verdict.all_matched)) == (
        want.rule, want.route, want.all_matched)  # fmt: skip


def test_expected_risk_table() -> None:
    assert gate3.expected_risk("tc02", True) == gate3.Risk("R20", "AUTO", frozenset({"R20"}))
    assert gate3.expected_risk("tc06", False) == gate3.Risk("R18", "HITL", frozenset({"R18", "R20"}))
    assert gate3.expected_risk("tc09", True) == gate3.Risk("R17", "HITL", frozenset({"R17"}))
    assert gate3.expected_risk("tc09", False) == gate3.Risk("R17", "HITL", frozenset({"R17", "R18"}))
    for tc in ("tc04", "tc05", "tc13", "tc16", "tc28"):
        with pytest.raises(KeyError):
            gate3.expected_risk(tc, True)


@pytest.mark.parametrize(("local", "label"), [
    (datetime(2026, 9, 30, 7, 59, tzinfo=VN), "NGOÀI GIỜ"), (datetime(2026, 9, 30, 8, 0, tzinfo=VN), "TRONG GIỜ"),
    (datetime(2026, 9, 30, 17, 59, tzinfo=VN), "TRONG GIỜ"), (datetime(2026, 9, 30, 18, 0, tzinfo=VN), "NGOÀI GIỜ"),
    (datetime(2026, 10, 3, 10, 0, tzinfo=VN), "NGOÀI GIỜ"),  # thứ Bảy
])  # fmt: skip
def test_hours_label_uses_policy_business_hours(local: datetime, label: str) -> None:
    assert gate3.hours_label(local, get_policy().business_hours) == label


def test_header_prints_window_first() -> None:
    out: list[str] = []
    ctx = gate3.Ctx(shell=Shell(COMPOSE.split(), run=FakeRun(), echo=out.append), http=None,  # type: ignore[arg-type]
                    report=Report(echo=out.append), password="x", now=lambda: NGOAI_GIO)  # fmt: skip
    gate3.header(ctx)
    assert out[0].startswith("Khung giờ lúc chạy: NGOÀI GIỜ (29/09/2026 20:00")


def test_scenario_window_change_is_fail_not_silent() -> None:
    times = iter([TRONG_GIO, NGOAI_GIO])
    out: list[str] = []
    ctx = gate3.Ctx(shell=Shell(COMPOSE.split(), run=FakeRun(), echo=out.append), http=None,  # type: ignore[arg-type]
                    report=Report(echo=out.append), password="x", now=lambda: next(times))  # fmt: skip
    in_hours = ctx.in_hours()
    gate3._same_window(ctx, "tk-1", in_hours)
    assert out[-1].startswith("FAIL tk-1 khung giờ không đổi") and "chạy lại" in out[-1]


# ---- Chốt an toàn -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("app_env", ["prod", "staging", ""])
def test_stops_before_anything_when_backend_not_dev(app_env: str) -> None:
    run = FakeRun(app_env)
    code, out = _main(["all"], run)
    assert code == 2 and len(run.calls) == 1
    assert any("DỪNG (chốt an toàn)" in line for line in out)


@pytest.mark.parametrize("backend", ["real", "?"])
def test_stops_when_llm_backend_not_scripted(backend: str) -> None:
    run = FakeRun(flags=FLAGS_OK.replace("LLM_BACKEND=scripted", f"LLM_BACKEND={backend}"))
    code, out = _main(["tc02"], run)
    assert code == 2 and len(run.calls) == 2  # printenv APP_ENV + dò biến — không lệnh nào khác, không HTTP
    assert any("không phải 'scripted'" in line for line in out)


@pytest.mark.parametrize("flags", [FLAGS_OK.replace("FAKE_SCENARIO=0", "FAKE_SCENARIO=1"),
                                   FLAGS_OK.replace("FAKE_SCENARIO=0\n", "")])  # fmt: skip
def test_stops_when_fake_scenario_set_or_unknown(flags: str) -> None:
    run = FakeRun(flags=flags)
    code, out = _main(["tc02"], run)
    assert code == 2 and len(run.calls) == 2
    assert any("FAKE_SCENARIO" in line for line in out)


def test_bad_url_and_unknown_scenario_stop_before_commands() -> None:
    run = FakeRun()
    assert _main(["tc02"], run, GATE3_URL="http://staging.example:8000")[0] == 2 and run.calls == []
    assert _main(["khong-co"], run)[0] == 2 and run.calls == []


def test_all_order_preflight_first_tc28_last() -> None:
    assert gate3.ALL[0] == "preflight" and gate3.ALL[-1] == "tc28"
    assert set(gate3.ALL) == {"preflight", "tc02", "tc04", "tc05", "tc06", "tc09", "tc13", "tc16", "tc28"}


# ---- Biến môi trường: chỉ CÓ/KHÔNG, không bao giờ giá trị -----------------------------------------------------------


def _probe(env: dict[str, str]) -> str:
    return subprocess.run(["sh", "-c", gate3.ENV_PROBE], env={"PATH": "/usr/bin:/bin", **env}, capture_output=True,
                          text=True, check=True).stdout  # fmt: skip


def test_env_probe_prints_names_and_flags_only() -> None:
    out = _probe({"SVC_EXECUTOR_TOKEN": SECRET, "FAKE_APPROVER_ID": "l1_01", "LLM_BACKEND": "scripted"})
    assert out.splitlines() == ["SVC_EXECUTOR_TOKEN=1", "FAKE_SCENARIO=0", "FAKE_APPROVER_ID=1", "LLM_BACKEND=scripted"]
    assert SECRET not in out and "l1_01" not in out


def test_env_probe_unknown_backend_value_not_echoed() -> None:
    out = _probe({"LLM_BACKEND": SECRET, "FAKE_SCENARIO": "approval"})
    assert "LLM_BACKEND=?" in out.splitlines() and "FAKE_SCENARIO=1" in out.splitlines() and SECRET not in out


def test_parse_flags_drops_unknown_keys_and_values() -> None:
    flags = gate3.parse_flags(f"SVC_EXECUTOR_TOKEN={SECRET}\nFAKE_SCENARIO=0\nOTHER=1\nLLM_BACKEND=real\n")
    assert flags == {"FAKE_SCENARIO": "0", "LLM_BACKEND": "real"}


def test_env_probe_command_echoed_without_values() -> None:
    out: list[str] = []
    shell = Shell(COMPOSE.split(), run=FakeRun(flags=f"SVC_EXECUTOR_TOKEN=1\nFAKE_SCENARIO=0\nLLM_BACKEND=scripted\n"
                                                     f"# {SECRET}\n"), echo=out.append)  # fmt: skip
    gate3.env_gate(shell)
    assert out and all(SECRET not in line for line in out)


# ---- tc28 luôn bật lại Qdrant ---------------------------------------------------------------------------------------


def _ctx_with_http(handler: Callable[[httpx.Request], httpx.Response]) -> tuple[gate3.Ctx, FakeRun, list[str]]:
    run, out = FakeRun(), cast(list[str], [])
    http = httpx.Client(base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(handler))
    ctx = gate3.Ctx(shell=Shell(COMPOSE.split(), run=run, echo=out.append), http=http,
                    report=Report(echo=out.append), password="x")  # fmt: skip
    return ctx, run, out


def _stack_handler(ticket_status: int = 500, raise_on_ticket: BaseException | None = None) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"status": "ok", "kb": {"status": "ready"}})
        if request.url.path == "/api/tickets":
            if raise_on_ticket is not None:
                raise raise_on_ticket
            return httpx.Response(ticket_status, json={"detail": "x"})
        return httpx.Response(404)

    return handler


@pytest.mark.parametrize("failure", [None, RuntimeError("lỗi bất ngờ")], ids=["http-500", "ngoai-le-khac"])
def test_tc28_always_starts_qdrant_again(failure: BaseException | None) -> None:
    ctx, run, _ = _ctx_with_http(_stack_handler(raise_on_ticket=failure))
    with pytest.raises(type(failure) if failure else StackError):
        gate3.tc28(ctx)
    tails = run.tails()
    assert "stop qdrant" in tails and "start qdrant" in tails
    assert tails.index("stop qdrant") < tails.index("start qdrant")
    assert not any(" down" in t or "-v" in t.split() for t in tails)


class StopFails(FakeRun):
    """`compose stop qdrant` trả mã ≠ 0 (vd đã dừng một phần rồi lỗi) — vẫn phải `start` lại."""

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        if cmd[-2:] == ["stop", "qdrant"]:
            self.calls.append(cmd)
            return 1, "lỗi giả"
        return super().__call__(cmd, stdin)


def test_tc28_stop_failure_still_starts_qdrant() -> None:
    run, out = StopFails(), cast(list[str], [])
    http = httpx.Client(base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(_stack_handler()))
    ctx = gate3.Ctx(shell=Shell(COMPOSE.split(), run=run, echo=out.append), http=http,
                    report=Report(echo=out.append), password="x")  # fmt: skip
    with pytest.raises(StackError):
        gate3.tc28(ctx)
    assert run.tails()[-2:] == ["stop qdrant", "start qdrant"]


def test_writes_count_every_post_except_login() -> None:
    """"0 lời gọi ghi" phải thấy ghi sang MỌI hệ thống (AD, file, phần mềm), không chỉ `/vpn/`."""

    class Counts(FakeRun):
        def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
            if cmd[-3] == "-c" and cmd[-1].startswith("/"):  # `mock python -c <code> <path_prefix>`
                self.calls.append(cmd)
                return 0, {"/": "7\n", gate3.AUTH: "5\n"}.get(cmd[-1], "0\n")
            return super().__call__(cmd, stdin)

    run = Counts()
    ctx = gate3.Ctx(shell=Shell(COMPOSE.split(), run=run, echo=lambda _: None), http=None,  # type: ignore[arg-type]
                    report=Report(echo=lambda _: None), password="x")  # fmt: skip
    assert ctx.mock_writes() == 2
    assert [c[-1] for c in run.calls] == ["/", gate3.AUTH]


def test_tc28_failure_is_reported_and_run_continues() -> None:
    ctx, run, out = _ctx_with_http(_stack_handler())
    assert gate3.run_scenarios(ctx, ["tc28"]) is None
    assert any(line.startswith("FAIL - tc28 dừng giữa chừng") for line in out)
    assert run.tails()[-1] == "start qdrant"


def _tc09_ctx(stack: str, *, in_hours: bool = True) -> tuple[gate3.Ctx, list[str], list[tuple[str, str, str]]]:
    """Ctx giả trả kết quả stack của tc09: `pending` (Phase 4 S0-P7 — R17 chờ duyệt, B11 procedure_doc) hoặc `e3_b9` (hành vi 3h:
    dừng ở B9 E3 `no_grounding`, reranker thật 0,047)."""
    out: list[str] = []
    opened: list[tuple[str, str, str]] = []
    ctx = gate3.Ctx(shell=Shell(COMPOSE.split(), run=FakeRun(), echo=out.append), http=None,  # type: ignore[arg-type]
                    report=Report(echo=out.append), password="x")  # fmt: skip
    e3 = stack == "e3_b9"
    view = {"final_state": "S_ESCALATED" if e3 else None, "status": "S_ESCALATED" if e3 else "S_PENDING_APPROVAL",
            "exit_code": "E3" if e3 else None,
            "conversation": [{"kind": "escalation", "text": gate3.user_message("E3")}] if e3 else []}  # fmt: skip
    grounding = {"top_score": 0.047, "above_threshold": False, "kb_gap": True}
    audit = [{"step": "B8", "event": "retrieved", "detail": {}}] + (
        [{"step": "B10", "event": "needs_action", "detail": {"grounding": grounding}}]
        + [{"step": "B9", "event": "no_evidence", "detail": {}}] if e3 else
        [{"step": "B10", "event": "needs_action", "detail": {"grounding": grounding}},
         {"step": "B11", "event": "action_built", "detail": {"procedure_doc": "KB-VPN-004"}}]
    )  # fmt: skip
    want = gate3.expected_risk("tc09", in_hours)
    risk = [] if e3 else [{"matched_rule_id": want.rule, "route": want.route, "all_matched": sorted(want.all_matched)}]
    def _open(who: str, preset: str, sentence: str) -> str:
        opened.append((who, preset, sentence))
        return "t9"

    stubs: dict[str, Any] = {
        "mock_reset": lambda: None, "login_users": lambda: None, "in_hours": lambda: in_hours, "open": _open,
        "settle": lambda ticket, before: view, "mock_writes": lambda: 0, "risk": lambda ticket: risk,
        "escalation": lambda ticket: [["E3", "no_grounding"]] if e3 else [],
        "audit": lambda ticket: audit, "approvals": lambda ticket: [] if e3 else [{"status": "pending"}],
    }
    for name, fn in stubs.items():
        object.__setattr__(ctx, name, fn)
    return ctx, out, opened


@pytest.mark.parametrize("in_hours", [True, False], ids=["trong-gio", "ngoai-gio"])
def test_tc09_expects_pending_approval_and_fails_old_e3_result(in_hours: bool) -> None:
    """Phase 4 S0-P7: tc09 (reranker thật, điểm 0,047) → R17 (+R18 ngoài giờ) → chờ duyệt, 1 phiếu, 0 ghi, B11 ghi
    `procedure_doc=KB-VPN-004`. Kết quả kiểu 3h (E3 ở B9) giờ là FAIL — gate3 không xanh oan khi hành vi lùi lại."""
    ctx, out, opened = _tc09_ctx("pending", in_hours=in_hours)
    gate3.tc09(ctx)
    assert opened == [(gate3.BINH, "tc09", gate3.TC09)]
    assert ctx.report.lines and all(line.ok for line in ctx.report.lines), out
    names = {line.name for line in ctx.report.lines}
    assert {"R17 → chờ duyệt", "1 phiếu pending", "B11 căn cứ quy trình (procedure_doc)", "không dừng ở B9"} <= names
    ctx, out, _ = _tc09_ctx("e3_b9", in_hours=in_hours)
    gate3.tc09(ctx)
    failed = {line.name for line in ctx.report.lines if not line.ok}
    assert {"R17 → chờ duyệt", "1 phiếu pending", "B11 căn cứ quy trình (procedure_doc)"} <= failed, out


def test_tc16_still_e3_template() -> None:
    """S0-P7: tc16 (câu hỏi thông tin, KB không có MFA) vẫn E3 `no_grounding` + mẫu "Mình chưa có thông tin về việc này"."""
    assert gate3.user_message("E3").startswith("Mình chưa có thông tin về việc này")


# ---- Preset và KB fixture --------------------------------------------------------------------------------------------


def test_every_ticket_scenario_has_a_preset_with_all_prompts() -> None:
    default = yaml.safe_load((REPO / "config" / "scripted" / "default.yaml").read_text(encoding="utf-8"))
    for name in (n for n in gate3.SCENARIOS if n.startswith("tc")):
        preset = yaml.safe_load((REPO / "config" / "scripted" / f"{name}.yaml").read_text(encoding="utf-8"))
        assert set(preset) == set(default), name
        assert FAKE_TAG.search(f"{gate3.TC02} [fake:{name}]").group(1) == name  # type: ignore[union-attr]


def test_tc13_preset_judge_says_no_attack() -> None:
    """E0 của tc13 phải đến từ lớp tất định (L2/L3) — preset không được để LLM "cứu" lớp mẫu bị hỏng."""
    preset = yaml.safe_load((REPO / "config" / "scripted" / "tc13.yaml").read_text(encoding="utf-8"))
    assert preset["b02_injection_judge"]["is_attack"] is False


@pytest.mark.asyncio
async def test_tc13_expected_final_state_is_what_real_b2_does() -> None:
    """Lần chạy stack đầu (30/09/2026): gate3 đòi `S_ESCALATED` nhưng B2 thật chặn câu tc13 bằng `S_BLOCKED` E0. Kỳ vọng của
    gate3 đối chiếu với CHÍNH node B2 thật trên câu của gate3 (không chép lại bảng)."""
    from tests.fakes.identity import SESSION
    from tests.unit.test_b02_screen import _env

    h, _ = _env()
    v = (await h.submit_as("t1", SESSION, text=gate3.TC13)).values
    assert (v["status"], v["exit_code"], v["block_reason"]) == (gate3.TC13_FINAL, "E0", "injection_detected")


def test_fixture_collection_is_sha_of_enabled_doc_ids() -> None:
    enabled = "\n".join(f"KB-VPN-00{i}:1" for i in (1, 3, 4, 5, 7))  # KB-VPN-002 enabled=false
    assert gate3.fixture_collection() == "kb_" + hashlib.sha256(enabled.encode()).hexdigest()


@pytest.mark.tokenizer_real
@pytest.mark.asyncio
async def test_answer_presets_cite_real_fixture_chunks() -> None:
    """chunk_id mà preset tc04/tc05/tc28 trích phải là chunk thật của KB fixture (chia bằng tokenizer bge-m3 thật), đúng
    mục: cổng kết nối (KB-VPN-001) và lỗi 809 (KB-VPN-003)."""
    counter = LocalTokenizerCounter(require_bge_tokenizer())
    docs, _ = load_kb(FIXTURE_KB, FakeClock(KB_TEST_NOW))
    headings = {c.chunk_id: c.heading_path for d in docs if d.fm.enabled for c in await chunk_doc(d, counter)}
    expect = {"tc04": ("KB-VPN-001#", "cổng"), "tc05": ("KB-VPN-003#", "Lỗi 809"), "tc28": ("KB-VPN-001#", "cổng")}
    for name, (prefix, word) in expect.items():
        preset = yaml.safe_load((REPO / "config" / "scripted" / f"{name}.yaml").read_text(encoding="utf-8"))
        [cited] = preset["b10_answer"]["citations"]
        assert cited.startswith(prefix) and word in headings[cited], (name, cited, headings.get(cited))
    assert gate3.TC04_SOURCE == "KB-VPN-001#" and gate3.TC05_SOURCE == "KB-VPN-003#"


def test_ctx_sql_checks_ticket_id_before_query() -> None:
    seen: list[str] = []

    def sql(query: str) -> str:
        seen.append(query)
        return "[]"

    ctx = gate3.Ctx(shell=Shell(COMPOSE.split(), run=FakeRun(sql=sql), echo=lambda _: None), http=None,  # type: ignore[arg-type]
                    report=Report(echo=lambda _: None), password="x")  # fmt: skip
    assert ctx.risk("tk-1") == [] and "'tk-1'" in seen[-1]
    with pytest.raises(StackError):
        ctx.txlog("x'; DROP TABLE tickets; --")
    assert len(seen) == 1
