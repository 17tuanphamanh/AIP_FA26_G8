"""config/policy.json và config/slots.yaml: đúng hằng số [Chốt 01 mục 5.2], sai schema → lỗi. 3h: `business_hours` + luật
R16–R20 đúng phase3 11.2; luật/giờ hỏng → không nạp; `check_policy_config` (Q-3h-1); `policy_sha256` (3-Q29)."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from app.settings import (
    ActionMetadataFile,
    Settings,
    check_intent_config,
    check_policy_config,
    get_action_metadata,
    get_policy,
    get_slots,
    load_action_metadata,
    load_policy,
    load_slots,
    policy_sha256,
)
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[3]


def test_policy_constants_match_spec() -> None:
    c = get_policy().constants
    assert (c.MAX_LOOPS, c.MAX_CLARIFICATION_TURNS, c.TOOL_RETRY, c.BACKOFF_BASE_SECONDS) == (5, 3, 2, 1)
    assert (c.MAX_AUTH_FAILURES, c.AUTH_FAILURE_WINDOW_MINUTES, c.SLA_MINUTES) == (5, 10, 30)
    assert (c.THRESHOLD_LOW, c.THRESHOLD_HIGH, c.RETRIEVAL_THRESHOLD) == (0.25, 0.75, 0.6)
    assert (c.CLARIFY_TIMEOUT_HOURS, c.CONFIRM_TIMEOUT_HOURS) == (24, 48)
    assert c.TAU_INTENT == 0.6  # 3-Q29, B03 §7


def test_tool_arg_slots_match_b11() -> None:
    assert get_slots().tool_arg_slots == {"device_id", "resource_path", "target_user", "software_name",
                                          "account_type"}  # fmt: skip


def test_query_slots_match_3c() -> None:
    assert get_slots().query_slots == ("error_code",)  # 3-Q13


def _policy(tmp_path: Path, **over: object) -> Path:
    raw = json.loads((REPO / "config" / "policy.json").read_text())
    raw["constants"].update(over)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw))
    return path


@pytest.mark.parametrize(
    "over",
    [{"THRESHOLD_LOW": 0.8}, {"TOOL_RETRY": -1}, {"MAX_AUTH_FAILURES": "năm"}, {"KHOA_LA": 1}],
    ids=["low>=high", "negative", "wrong-type", "unknown-key"],
)
def test_bad_policy_rejected(tmp_path: Path, over: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        load_policy(_policy(tmp_path, **over))


def test_incomplete_rule_rejected(tmp_path: Path) -> None:
    raw = json.loads((REPO / "config" / "policy.json").read_text())
    raw["rules"] = [{"id": "R01"}]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValidationError):  # luật thiếu trường (3h: schema `domain.policy.Rule`)
        load_policy(path)


# ---- 3h: luật R16–R20 + giờ hành chính (phase3 11.2; PLAN-3h S1) ----------------------------------------------------

SPEC_11_2: dict[str, Any] = {
    "business_hours": {"tz": "Asia/Ho_Chi_Minh", "weekdays": [1, 2, 3, 4, 5], "start": "08:00", "end": "18:00"},
    "rules": [
        {"id": "R16", "type": "allow", "intent": "vpn", "action": "check_vpn_status",
         "conditions": {"all": [{"fact": "ctx.target_is_other", "op": "is_false"}]},
         "description": "Kiểm tra trạng thái VPN của chính mình"},
        {"id": "R17", "type": "approval_required", "intent": "vpn", "action": ["renew_vpn_cert", "reissue_vpn_access"],
         "conditions": {"all": [
            {"fact": "action.facts.device_registered", "op": "is_false"},
            {"fact": "action.facts.device_owner_is_requester", "op": "is_true"}]},  # Phase 4 P7 (Q-4-M)
         "description": "Thiết bị chưa đăng ký"},
        {"id": "R18", "type": "approval_required", "intent": "vpn", "action": ["renew_vpn_cert", "reissue_vpn_access"],
         "conditions": {"all": [
            {"fact": "time.within_business_hours", "op": "is_false"},
            {"fact": "action.facts.device_owner_is_requester", "op": "is_true"}]},  # Phase 4 P7 (Q-4-M)
         "description": "Ngoài giờ hành chính"},
        {"id": "R19", "type": "approval_required", "intent": "vpn", "action": ["renew_vpn_cert", "reissue_vpn_access"],
         "conditions": {"all": [
            {"fact": "requester.employment_status", "op": "eq", "value": "probation"},
            {"fact": "action.facts.device_owner_is_requester", "op": "is_true"}]},  # Phase 4 P7 (Q-4-M)
         "description": "Nhân viên chưa qua thử việc"},
        {"id": "R20", "type": "allow", "intent": "vpn", "action": ["renew_vpn_cert", "reissue_vpn_access"],
         "conditions": {"all": [
            {"fact": "action.facts.device_registered", "op": "is_true"},
            {"fact": "action.facts.device_owner_is_requester", "op": "is_true"},
            {"fact": "ctx.target_is_other", "op": "is_false"}]},
         "description": "Cấp lại cho thiết bị đã đăng ký của chính người gửi"},
    ],
}  # fmt: skip


def test_policy_json_rules_are_exactly_spec_11_2() -> None:
    raw = json.loads((REPO / "config" / "policy.json").read_text())
    assert raw["business_hours"] == SPEC_11_2["business_hours"]
    assert raw["rules"] == SPEC_11_2["rules"]
    assert [r.id for r in get_policy().rules] == ["R16", "R17", "R18", "R19", "R20"]
    check_policy_config(get_policy(), get_slots(), get_action_metadata())


def test_policy_sha256_is_file_bytes() -> None:
    assert policy_sha256() == hashlib.sha256((REPO / "config" / "policy.json").read_bytes()).hexdigest()


def _with(tmp_path: Path, fn: Any) -> Path:
    raw = json.loads((REPO / "config" / "policy.json").read_text())
    fn(raw)
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw, ensure_ascii=False))
    return path


def _cond(raw: dict[str, Any], i: int, **over: Any) -> None:
    raw["rules"][i]["conditions"]["all"][0] = {**raw["rules"][i]["conditions"]["all"][0], **over}


BAD_POLICIES = {
    "fact-la": lambda r: _cond(r, 1, fact="action.facts.bogus"),
    "nguon-slots": lambda r: _cond(r, 1, fact="slots.device_id"),
    "nguon-cau-nguoi-dung": lambda r: _cond(r, 1, fact="redacted_request"),
    "requester-la": lambda r: _cond(r, 3, fact="requester.password"),
    "is_true-co-value": lambda r: _cond(r, 1, value=True),
    "eq-thieu-value": lambda r: _cond(r, 3, value=None),
    "lt-value-bool": lambda r: _cond(r, 3, op="lt", value=True),
    "in-rong": lambda r: _cond(r, 3, op="in", value=[]),
    "op-la": lambda r: _cond(r, 3, op="matches"),
    "id-trung": lambda r: r["rules"][1].update(id="R16"),
    "id-sai-dang": lambda r: r["rules"][1].update(id="rule-17"),
    "type-la": lambda r: r["rules"][1].update(type="maybe"),
    "action-rong": lambda r: r["rules"][1].update(action=[]),
    "ca-all-lan-any": lambda r: r["rules"][1]["conditions"].update(any=[{"fact": "ctx.target_is_other", "op": "is_true"}]),
    "all-rong": lambda r: r["rules"][1].update(conditions={"all": []}),
    "khoa-la-trong-luat": lambda r: r["rules"][1].update(note="x"),
    "khong-co-luat": lambda r: r.update(rules=[]),
    "tz-la": lambda r: r["business_hours"].update(tz="Asia/Khong_Co"),
    "start-sau-end": lambda r: r["business_hours"].update(start="18:00", end="08:00"),
    "thu-8": lambda r: r["business_hours"].update(weekdays=[1, 8]),
    "thu-trung": lambda r: r["business_hours"].update(weekdays=[1, 1]),
    "thieu-business-hours": lambda r: r.pop("business_hours"),
    # soát S7 NGHI 1: kiểu CHẶT lúc nạp — `[true]` không bị ép thành `(1,)`, chuỗi số không thành số
    "in-bool-bi-ep-so": lambda r: _cond(r, 3, fact="action.facts.device_count", op="in", value=[True]),
    "lt-chuoi-so": lambda r: _cond(r, 3, fact="action.facts.device_count", op="lt", value="3"),
}


@pytest.mark.parametrize("name", sorted(BAD_POLICIES))
def test_bad_rules_or_hours_rejected(tmp_path: Path, name: str) -> None:
    assert len(BAD_POLICIES) >= 20  # quy ước 3.9
    with pytest.raises(ValidationError):
        load_policy(_with(tmp_path, BAD_POLICIES[name]))


def test_nested_any_group_accepted(tmp_path: Path) -> None:
    def nest(r: dict[str, Any]) -> None:
        r["rules"][4]["conditions"] = {"all": [{"any": [{"fact": "ctx.target_is_other", "op": "is_false"}]},
                                               {"fact": "action.facts.device_registered", "op": "is_true"}]}  # fmt: skip

    assert load_policy(_with(tmp_path, nest)).rules[4].id == "R20"


def test_q3h1_rule_action_outside_intent_refuses_start(tmp_path: Path) -> None:
    policy = load_policy(_with(tmp_path, lambda r: r["rules"][1].update(action=["renew_vpn_cert", "reset_password"])))
    with pytest.raises(RuntimeError, match="R17"):
        check_policy_config(policy, get_slots(), get_action_metadata())
    policy = load_policy(_with(tmp_path, lambda r: r["rules"][1].update(intent="account")))
    with pytest.raises(RuntimeError, match="R17"):
        check_policy_config(policy, get_slots(), get_action_metadata())


def test_q3h1_action_type_in_two_intents_refuses_start() -> None:
    meta = copy.deepcopy(get_action_metadata().model_dump())
    meta["account"] = {"renew_vpn_cert": meta["vpn"]["renew_vpn_cert"]}
    with pytest.raises(RuntimeError, match="renew_vpn_cert"):
        check_policy_config(get_policy(), get_slots(), ActionMetadataFile.model_validate(meta))


def test_bad_slots_rejected(tmp_path: Path) -> None:
    path = tmp_path / "slots.yaml"
    path.write_text("tool_arg_slots: []\n")
    with pytest.raises(ValidationError):
        load_slots(path)


# ---- 3f: slots.yaml intents, action_metadata.yaml, ENABLED_INTENTS (phase3 3.2, 9.2, 3-Q27) ----------------------


def test_vpn_intent_slots_match_spec() -> None:
    vpn = get_slots().intents["vpn"]
    assert (vpn.required, vpn.optional) == (("device_id", "action"), ("reason", "error_code"))
    assert vpn.action_types == ("renew_vpn_cert", "reissue_vpn_access", "check_vpn_status")  # 3-Q38
    assert vpn.value_rules["device_id"].pattern == r"^[A-Z]{2,4}-\d{3,5}$"
    assert vpn.value_rules["error_code"].pattern == r"^(0x[0-9A-Fa-f]{4,8}|\d{3,4})$"
    assert vpn.value_rules["reason"].max_len == 200


def test_every_action_type_has_metadata_and_repo_config_passes() -> None:
    meta = get_action_metadata()
    for intent, spec in get_slots().intents.items():
        assert set(spec.action_types) <= set(meta.of(intent)), intent
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.enabled_intents == ["vpn"]
    check_intent_config(settings, get_slots(), meta)


def _slots_file(tmp_path: Path, extra: str = "") -> Path:
    base = (REPO / "config" / "slots.yaml").read_text(encoding="utf-8")
    path = tmp_path / "slots.yaml"
    path.write_text(base + extra, encoding="utf-8")
    return path


def test_missing_action_metadata_refuses_startup(tmp_path: Path) -> None:
    path = tmp_path / "action_metadata.yaml"
    path.write_text("vpn:\n  renew_vpn_cert: {reversible: true, reversibility: full, data_sensitivity: low, "
                    "scope: single_device, privilege_level: standard_user, procedure_doc: KB-VPN-004}\n")  # thiếu 2 action
    with pytest.raises(RuntimeError, match="thiếu metadata cho vpn: \\['check_vpn_status', 'reissue_vpn_access'\\]"):
        check_intent_config(Settings(_env_file=None), get_slots(), load_action_metadata(path))  # type: ignore[call-arg]


def test_enabled_intent_without_slots_refuses_startup() -> None:
    settings = Settings(_env_file=None, enabled_intents=["vpn", "account"])  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="account"):
        check_intent_config(settings, get_slots(), get_action_metadata())


def test_q3g7_rediagnose_flag_refuses_startup() -> None:
    """3g (chốt Q-3g-7): chẩn đoán lại D-20 chưa hiện thực — bật cờ là không khởi động (fail-closed), không chạy nửa vời."""
    settings = Settings(_env_file=None, rediagnose_on_new_slot=True)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="REDIAGNOSE_ON_NEW_SLOT"):
        check_intent_config(settings, get_slots(), get_action_metadata())
    check_intent_config(Settings(_env_file=None), get_slots(), get_action_metadata())  # type: ignore[call-arg]  # tắt → qua


_META = "scope: single_device, privilege_level: standard_user, procedure_doc: KB-VPN-004"


@pytest.mark.parametrize(
    "body",
    [
        f"vpn: {{renew_vpn_cert: {{reversible: true, reversibility: none, data_sensitivity: low, {_META}}}}}\n",
        f"vpn: {{renew_vpn_cert: {{reversible: true, reversibility: full, data_sensitivity: low, {_META}, x: 1}}}}\n",
        f"vpn: {{renew_vpn_cert: {{reversibility: full, data_sensitivity: low, {_META}}}}}\n",
    ],
    ids=["reversible-lech-reversibility", "khoa-la", "thieu-reversible-khong-mac-dinh"],
)
def test_bad_action_metadata_rejected(tmp_path: Path, body: str) -> None:
    path = tmp_path / "action_metadata.yaml"
    path.write_text(body)
    with pytest.raises(ValidationError):
        load_action_metadata(path)


_META_NO_DOC = "reversible: true, reversibility: full, data_sensitivity: low, scope: single_device, privilege_level: standard_user"


@pytest.mark.parametrize(
    "tail", ["", ", procedure_doc: null", ", procedure_doc: KB-VPN-4", ", procedure_doc: kb-vpn-004",
             ", procedure_doc: KB-XYZ-004", ", procedure_doc: 'KB-VPN-004 x'"],
    ids=["thieu", "null", "sai-so-chu-so", "chu-thuong", "nhom-la", "duoi-thua"],
)
def test_s16_action_metadata_without_valid_procedure_doc_refuses_startup(tmp_path: Path, tail: str) -> None:
    """s16 (Phase 4 S0-P10): `procedure_doc` BẮT BUỘC, đúng mẫu `doc_id` KB — thiếu/sai → không nạp được → backend/worker không
    khởi động (`open_runtime` nạp `get_action_metadata()` trước DB). Đối chứng: bản đúng nạp được và giữ giá trị."""
    path = tmp_path / "action_metadata.yaml"
    path.write_text(f"vpn: {{renew_vpn_cert: {{{_META_NO_DOC}{tail}}}}}\n")
    with pytest.raises(ValidationError, match="procedure_doc"):
        load_action_metadata(path)
    path.write_text(f"vpn: {{renew_vpn_cert: {{{_META_NO_DOC}, procedure_doc: KB-VPN-004}}}}\n")
    assert load_action_metadata(path).of("vpn")["renew_vpn_cert"].procedure_doc == "KB-VPN-004"


def test_s16_repo_action_metadata_procedure_docs_match_spec() -> None:
    """S0-P10: `renew_vpn_cert`, `reissue_vpn_access` → KB-VPN-004; `check_vpn_status` → KB-VPN-001 (có trong KB fixture)."""
    docs = {a: m.procedure_doc for a, m in get_action_metadata().of("vpn").items()}
    assert docs == {"renew_vpn_cert": "KB-VPN-004", "reissue_vpn_access": "KB-VPN-004", "check_vpn_status": "KB-VPN-001"}


def test_slot_named_like_fact_rejected(tmp_path: Path) -> None:
    body = (REPO / "config" / "slots.yaml").read_text(encoding="utf-8").replace(
        "optional: [reason, error_code]", "optional: [reason, error_code, device_registered]"
    )
    path = tmp_path / "slots.yaml"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValidationError, match="trùng tên fact"):
        load_slots(path)


# ---- b26: config/vi_abbrev.yaml, config/vi_stopwords.txt (BM25 — thiết kế Phase 3 mục 5.6) -----------


def _stopwords() -> list[str]:
    lines = (REPO / "config" / "vi_stopwords.txt").read_text(encoding="utf-8").splitlines()
    return [w.strip() for w in lines if w.strip() and not w.lstrip().startswith("#")]


def test_stopwords_exclude_negation() -> None:
    stopwords = _stopwords()
    assert "không" not in stopwords  # M-3b-7: phủ định đổi nghĩa câu hỏi
    assert not [w for w in stopwords if any(ch.isdigit() for ch in w)]
    assert all(w == w.lower() and " " not in w for w in stopwords)
    assert len(stopwords) == len(set(stopwords)) >= 30


def test_abbrev_loads_lowercase() -> None:
    import yaml
    from app.rag.bm25 import load_lexicon

    raw = yaml.safe_load((REPO / "config" / "vi_abbrev.yaml").read_text(encoding="utf-8"))
    assert raw and all(isinstance(k, str) and k == k.lower() for k in raw)
    assert all(isinstance(v, str) and v == v.lower() for v in raw.values())
    lx = load_lexicon(REPO / "config")
    assert lx.abbrev["mk"] == "mật khẩu" and lx.abbrev["ko"] == "không"
    assert lx.stopwords == frozenset(_stopwords())


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_rejected(tmp_path: Path, bad: str) -> None:
    """Soát S7 NGHI 3: `json.loads` mặc định nhận NaN/Infinity — điều kiện `ne NaN`/`lt Infinity` luôn đúng."""
    text = (REPO / "config" / "policy.json").read_text()
    text = text.replace('"op": "eq", "value": "probation"', f'"op": "lt", "value": {bad}')
    assert bad in text
    path = tmp_path / "policy.json"
    path.write_text(text)
    with pytest.raises(ValueError):
        load_policy(path)


@pytest.mark.asyncio
async def test_q3h1_open_runtime_refuses_bad_policy_before_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Soát S7 FAIL (Q-3h-1): `open_runtime` (backend + worker) gọi `check_policy_config` TRƯỚC khi đụng DB — luật nhắm
    action gõ sai (`reissue_vpn_acess`) im lặng không bao giờ khớp → R20 allow thay cho R18."""
    from app.db.session import create_engines
    from app.graph import wiring
    from pydantic import SecretStr

    typo = load_policy(_with(tmp_path, lambda r: r["rules"][2].update(action=["renew_vpn_cert", "reissue_vpn_acess"])))
    monkeypatch.setattr(wiring, "get_policy", lambda: typo)
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, app_env="dev", llm_backend="scripted", ml_service_token=SecretStr("t" * 32),
        database_url="postgresql+psycopg://x@127.0.0.1:1/khong_co",
    )
    engines = create_engines(settings)
    with pytest.raises(RuntimeError, match="R18"):
        async with wiring.open_runtime(settings, engines, clock=None, can_execute=False):  # type: ignore[arg-type]
            pass
    await engines.dispose()
