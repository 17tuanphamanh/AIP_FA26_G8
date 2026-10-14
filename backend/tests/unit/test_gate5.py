"""`tests/stack/gate5.py` (phase5 mục 7.6, T24 P8; PLAN-T24 S15) — phần chạy được KHÔNG cần stack: thứ tự kịch bản, 9 preset ScriptedLLM
(đủ khoá của preset cũ kể cả `b14_*`, đúng schema, slot qua `sanitize_slots` với ĐÚNG câu gửi), luật mong đợi khớp `policy.json`,
chốt an toàn ENABLED_INTENTS (in nhãn — không giá trị), biên bản. Kịch bản thật: `make gate5 S=…` / `make verify G=2345`."""

import ast
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.domain.slots import phrase_in_text, sanitize_slots
from app.domain.ticket_state import RiskDecision
from app.guard.patterns import PRIVACY_FILE, load_privacy_patterns
from app.guard.privacy import RegexPrivacyGuard
from app.llm.providers.scripted import FAKE_TAG, load_presets
from app.settings import get_action_metadata, get_policy, get_slots
from tests.fakes.llm import repo_registry
from tests.stack import gate4, gate5
from tests.unit.test_chain_t20a import chain
from tests.unit.test_gate3 import COMPOSE, FakeRun

REPO = Path(__file__).resolve().parents[3]
SCRIPTED = REPO / "config" / "scripted"
OLD_PRESETS = frozenset({"default", "g4_0124", "g4_0501", "g4_0700", "tc02", "tc04", "tc05", "tc06", "tc09", "tc13", "tc16", "tc28",
                         "vpn"})  # fmt: skip
NEW_PRESETS = frozenset({"tc01", "tc03", "tc07", "tc08", "tc17", "tc18", "tc21a", "tc21b", "hb04"})
# T20b (phase5 5.2.7): 5 kịch bản nhiều ý — preset cha + preset con `<cha>-<i>`
MULTI = frozenset({"tc34", "tc35", "tc36", "tc32", "tc12r"})
T20B_PRESETS = MULTI | {c for cs in gate5.CHILD_PRESETS.values() for c in cs}


class IntentsRun(FakeRun):
    """FakeRun của gate3 + trả lời dò ENABLED_INTENTS theo container."""

    def __init__(self, backend: str = "INTENTS=du\n", worker: str = "INTENTS=du\n", **kw: Any) -> None:
        super().__init__(**kw)
        self.intents = {"backend": backend, "worker": worker}

    def __call__(self, cmd: list[str], stdin: str | None) -> tuple[int, str]:
        if cmd[-1] == gate5.INTENTS_PROBE:
            self.calls.append(cmd)
            return 0, self.intents[cmd[cmd.index("-T") + 1]]
        return super().__call__(cmd, stdin)


def _main(argv: list[str], run: FakeRun) -> tuple[int, list[str]]:
    out: list[str] = []
    code = gate5.main(argv, run=run, env={"COMPOSE": COMPOSE}, echo=out.append)
    return code, out


# ---- Kịch bản + preset -------------------------------------------------------------------------------------------------------


def test_all_order_preflight_first_audit_last_every_table_7_6_case() -> None:
    assert gate5.ALL[0] == "preflight" and gate5.ALL[-1] == "g5-audit" and len(set(gate5.ALL)) == len(gate5.ALL)
    assert set(gate5.ALL) == {"preflight", "g5-audit", *NEW_PRESETS, *MULTI}  # bảng 7.6: 9 kịch bản + T20b bảng 5.2.7: 5 kịch bản


def test_nine_new_presets_old_thirteen_untouched() -> None:
    """P8: 9 preset MỚI; 13 preset cũ vẫn đủ (không xoá/đổi tên)."""
    assert {f.stem for f in SCRIPTED.glob("*.yaml")} == OLD_PRESETS | NEW_PRESETS | T20B_PRESETS
    assert {p for p, _, _ in gate5.TICKET_PRESETS} == NEW_PRESETS


def test_presets_have_every_prompt_key_and_valid_schema() -> None:
    """P8: mỗi file đủ MỌI khoá prompt của preset cũ, kể cả `b14_*` (giá trị an toàn của default.yaml); schema đúng (bộ nạp thật)."""
    default = yaml.safe_load((SCRIPTED / "default.yaml").read_text(encoding="utf-8"))
    presets = load_presets(SCRIPTED, repo_registry())  # kiểm schema từng phản hồi như lúc khởi động
    for name in NEW_PRESETS:
        assert set(presets[name]) == set(default), name
        assert presets[name]["b14_risk_estimate"] == default["b14_risk_estimate"], name
        assert presets[name]["b14_risk_vote"] == default["b14_risk_vote"], name
        assert presets[name]["b02_injection_judge"]["is_attack"] is False, name


@pytest.mark.parametrize(("preset", "who", "sentence"), gate5.TICKET_PRESETS, ids=[p for p, _, _ in gate5.TICKET_PRESETS])
def test_preset_slots_survive_sanitize_with_exact_sentence(preset: str, who: str, sentence: str) -> None:
    """Slot B3 của preset qua `sanitize_slots` với ĐÚNG câu gate5 gửi (slot đích phải có trong câu — T20a P5) — không slot nào bị bỏ;
    `action_hint` thuộc `action_types`; thẻ `[fake:<preset>]` chọn đúng preset."""
    data = yaml.safe_load((SCRIPTED / f"{preset}.yaml").read_text(encoding="utf-8"))
    [intent] = data["b03_classify"]["intents"]
    spec = get_slots().intents[intent["type"]]
    assert intent["action_hint"] in spec.action_types
    raw = {**intent["slots"], "action": intent["action_hint"]}
    clean, dropped = sanitize_slots(spec, raw, text=sentence)
    assert dropped == {} and set(clean) == set(raw), (preset, dropped)
    assert FAKE_TAG.search(f"{sentence} [fake:{preset}]").group(1) == preset  # type: ignore[union-attr]
    assert who in (gate5.AN, gate5.BINH)


def _guard() -> RegexPrivacyGuard:
    return RegexPrivacyGuard(load_privacy_patterns(REPO / "config" / PRIVACY_FILE), ["congty-abc.vn"])


@pytest.mark.asyncio
@pytest.mark.parametrize(("preset", "who", "sentence"), gate5.TICKET_PRESETS, ids=[p for p, _, _ in gate5.TICKET_PRESETS])
async def test_q_t24_10_tag_survives_real_privacy_guard(preset: str, who: str, sentence: str) -> None:
    """Q-T24-10 = A (verify lần 2: tc01/tc07/tc18 ra E1): câu gate5 + thẻ `[fake:<preset>]` đi qua privacy guard THẬT (luật
    `config/privacy_patterns.json`) mà thẻ còn nguyên, không bị che như bí mật — mất thẻ = preset `default` (out_of_scope) → E1."""
    redacted = await _guard().redact(f"{sentence} [fake:{preset}]")
    assert redacted.secrets_found == 0, redacted.text
    assert FAKE_TAG.search(redacted.text).group(1) == preset  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_q_t24_10_control_password_rule_eats_tag_without_period() -> None:
    """Đối chứng (ghim nguyên nhân): "mật khẩu" + ≤ 4 từ + `:` của thẻ → luật `password` che tên preset."""
    redacted = await _guard().redact("đặt lại mật khẩu tài khoản AD [fake:tc01]")
    assert redacted.secrets_found == 1 and FAKE_TAG.search(redacted.text) is None


def test_expected_rules_exist_for_preset_action() -> None:
    """Luật mong đợi (bảng 7.6) có trong `policy.json` và thuộc đúng hành động của preset; route khớp loại luật."""
    rules = {r.id: r for r in get_policy().rules}
    hints = {p: yaml.safe_load((SCRIPTED / f"{p}.yaml").read_text(encoding="utf-8"))["b03_classify"]["intents"][0]["action_hint"]
             for p in NEW_PRESETS}  # fmt: skip
    for tc, want in gate5.EXPECTED.items():
        for rid in want.all_matched | {want.rule}:
            action = rules[rid].action
            actions = (action,) if isinstance(action, str) else tuple(action)
            assert hints[tc] in actions, (tc, rid)
        assert want.route == {"allow": "AUTO", "approval_required": "HITL"}[rules[want.rule].type], tc
    assert set(gate5.EXPECTED) == NEW_PRESETS - {"tc18"}  # tc18 dừng ở B7, không tới B12
    assert {"install_software"} <= set(get_action_metadata().of("software"))


USER_ID = {gate5.AN: "nv001", gate5.BINH: "nv002"}


@pytest.mark.asyncio
@pytest.mark.parametrize(("preset", "who", "sentence"), [c for c in gate5.TICKET_PRESETS if c[0] in gate5.EXPECTED],
                         ids=[c[0] for c in gate5.TICKET_PRESETS if c[0] in gate5.EXPECTED])  # fmt: skip
async def test_expected_risk_matches_real_chain_on_seed(preset: str, who: str, sentence: str) -> None:
    """Đối chiếu bảng `EXPECTED` với chuỗi node THẬT B3 → B6 → B11 → B12 (`test_chain_t20a.chain`: tool thật trên bản giả seed.json,
    luật thật) — cùng preset, cùng câu, cùng người gửi như gate5 → lần chạy stack đầu không lệch vì kỳ vọng sai."""
    data = yaml.safe_load((SCRIPTED / f"{preset}.yaml").read_text(encoding="utf-8"))
    [item] = data["b03_classify"]["intents"]
    state, audit, _ = await chain(USER_ID[who], sentence, item["type"], item["action_hint"], dict(item["slots"]))
    risk = RiskDecision.model_validate(state["risk"])
    [row] = [r for r in audit.rows if r["step"] == "B13/B14"]
    want = gate5.EXPECTED[preset]
    got = (risk.matched_rule_id, risk.route, frozenset(row["detail"]["all_matched"]))
    assert got == (want.rule, want.route, want.all_matched), preset


# ---- T20b: preset nhiều ý (bảng 5.2.7) ----------------------------------------------------------------------------------------

# Luật mong đợi của từng con (bảng 5.2.7): (preset con, ý của preset cha, slot thêm sau câu hỏi B11, luật, route)
CHILD_RISK: tuple[tuple[str, str, int, dict[str, str], str, str], ...] = (
    ("tc34-1", "tc34", 0, {}, "R01", "AUTO"), ("tc34-2", "tc34", 1, {}, "R14", "HITL"),
    ("tc35-1", "tc35", 0, {}, "R01", "AUTO"), ("tc35-2", "tc35", 1, {"duration": "30"}, "R10", "AUTO"),
    ("tc32-1", "tc32", 0, {}, "R01", "AUTO"),
)  # fmt: skip


def _intents(preset: str) -> list[dict[str, Any]]:
    return list(yaml.safe_load((SCRIPTED / f"{preset}.yaml").read_text(encoding="utf-8"))["b03_classify"]["intents"])


def test_t20b_multi_presets_and_children_complete() -> None:
    """Mỗi kịch bản nhiều ý có preset cha (≥ 2 ý) + đủ preset con cho MỌI ý chạy được (ý ngoài phạm vi không gọi LLM — không preset)."""
    assert {p for p, _, _ in gate5.MULTI_PRESETS} == MULTI == set(gate5.CHILD_PRESETS)
    for parent, children in gate5.CHILD_PRESETS.items():
        intents = _intents(parent)
        assert len(intents) >= 2, parent
        runnable = [i for i, it in enumerate(intents, start=1) if it["type"] != "out_of_scope"]
        assert children == tuple(f"{parent}-{i}" for i in runnable), parent


@pytest.mark.parametrize(("preset", "who", "sentence"), gate5.MULTI_PRESETS, ids=[p for p, _, _ in gate5.MULTI_PRESETS])
def test_t20b_spans_in_sentence_and_slots_survive_span_sanitize(preset: str, who: str, sentence: str) -> None:
    """Span của MỌI ý nằm trong đúng câu gate5 gửi (không thì con E1 `split_span_invalid`); slot của ý chạy được qua
    `sanitize_slots(text=span)` không bị bỏ (P2 — slot chỉ lấy trong span của CHÍNH ý); `action_hint` ∈ `action_types`."""
    for it in _intents(preset):
        assert it["span"] and phrase_in_text(it["span"], f"{sentence} [fake:{preset}]"), (preset, it["span"])
        if it["type"] == "out_of_scope":
            continue
        spec = get_slots().intents[it["type"]]
        assert it["action_hint"] in spec.action_types
        raw = {**it["slots"], "action": it["action_hint"]}
        clean, dropped = sanitize_slots(spec, raw, text=it["span"])
        assert dropped == {} and set(clean) == set(raw), (preset, dropped)
    assert who == gate5.AN


@pytest.mark.asyncio
@pytest.mark.parametrize(("preset", "who", "sentence"), gate5.MULTI_PRESETS, ids=[p for p, _, _ in gate5.MULTI_PRESETS])
async def test_t20b_tag_survives_real_privacy_guard(preset: str, who: str, sentence: str) -> None:
    """Q-T24-10 áp cho câu nhiều ý: thẻ `[fake:<cha>]` qua privacy guard THẬT còn nguyên, 0 bí mật."""
    redacted = await _guard().redact(f"{sentence} [fake:{preset}]")
    assert redacted.secrets_found == 0, redacted.text
    assert FAKE_TAG.search(redacted.text).group(1) == preset  # type: ignore[union-attr]


@pytest.mark.asyncio
@pytest.mark.parametrize(("child", "parent", "index", "extra", "rule", "route"), CHILD_RISK, ids=[c[0] for c in CHILD_RISK])
async def test_t20b_child_expected_risk_matches_real_chain_on_seed(
    child: str, parent: str, index: int, extra: dict[str, str], rule: str, route: str
) -> None:
    """Luật của từng con (bảng 5.2.7) khớp chuỗi node THẬT B3 → B6 → B11 → B12 trên seed giả với câu = SPAN của ý (con vào B6 với
    slot của ý; slot thêm = câu trả lời B11 của preset con) — lần chạy stack đầu không lệch vì kỳ vọng sai."""
    it = _intents(parent)[index]
    data = yaml.safe_load((SCRIPTED / f"{child}.yaml").read_text(encoding="utf-8"))
    assert data["b11_extract_slots"]["slots"] == extra, child
    state, _audit, _ = await chain("nv001", it["span"], it["type"], it["action_hint"], {**it["slots"], **extra})
    risk = RiskDecision.model_validate(state["risk"])
    assert (risk.matched_rule_id, risk.route) == (rule, route), child


# ---- Chốt an toàn ENABLED_INTENTS: chỉ in nhãn --------------------------------------------------------------------------------


@pytest.mark.parametrize(("out", "label"), [("INTENTS=du\n", "du"), ("INTENTS=thieu\n", "thieu"), ("x\nINTENTS=?\n", "?"),
                                            ("INTENTS=vpn,account\n", "?"), ("", "?")])  # fmt: skip
def test_parse_intents_closed_labels(out: str, label: str) -> None:
    assert gate5.parse_intents(out) == label


def test_intents_probe_prints_only_fixed_labels() -> None:
    """Script dò chỉ `print` chuỗi hằng (nhãn) — không bao giờ in giá trị biến môi trường."""
    calls = [n for n in ast.walk(ast.parse(gate5.INTENTS_PROBE)) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "print"]
    assert calls
    for call in calls:
        [arg] = call.args
        if isinstance(arg, ast.IfExp):
            assert isinstance(arg.body, ast.Constant) and isinstance(arg.orelse, ast.Constant)
        else:
            assert isinstance(arg, ast.Constant)


@pytest.mark.parametrize(("backend", "worker"), [("INTENTS=thieu\n", "INTENTS=du\n"), ("INTENTS=du\n", "INTENTS=?\n")])
def test_stops_before_http_when_intents_not_four(backend: str, worker: str) -> None:
    code, out = _main(["all"], IntentsRun(backend=backend, worker=worker))
    assert code == 2 and any("ENABLED_INTENTS" in line and "DỪNG" in line for line in out)


def test_stops_like_gate3_on_fake_scenario() -> None:
    code, out = _main(["all"], IntentsRun(flags="SVC_EXECUTOR_TOKEN=1\nFAKE_SCENARIO=1\nLLM_BACKEND=scripted\n"))
    assert code == 2 and any("FAKE_SCENARIO" in line for line in out)


def test_unknown_scenario_stops_before_commands() -> None:
    run = IntentsRun()
    code, out = _main(["tc99"], run)
    assert code == 2 and run.calls == [] and "kịch bản lạ" in out[0]


# ---- Biên bản -----------------------------------------------------------------------------------------------------------------


def test_bienban_render_gate5_title_counts_blank_runner() -> None:
    rows = [gate4.Outcome("tc01", 9, 0, ""), gate4.Outcome("tc21b", 7, 1, "FAIL | x")]
    text = gate5.render_bienban(rows, run_id="abc", started=datetime(2026, 10, 14, 1, 0, tzinfo=UTC),
                                ended=datetime(2026, 10, 14, 1, 9, tzinfo=UTC), commit="1234567", dirty=0)  # fmt: skip
    assert text.startswith("# Biên bản chạy cổng 5") and "KHÔNG ĐẠT (1 FAIL)" in text
    assert "| tc21b | 7 | 1 | FAIL / x |" in text and "Người chạy: ______" in text
