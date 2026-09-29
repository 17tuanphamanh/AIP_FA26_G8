"""config/policy.json và config/slots.yaml: đúng hằng số [Chốt 01 mục 5.2], sai schema → lỗi."""

import json
from pathlib import Path

import pytest
from app.settings import (
    Settings,
    check_intent_config,
    get_action_metadata,
    get_policy,
    get_slots,
    load_action_metadata,
    load_policy,
    load_slots,
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


def test_policy_rules_not_accepted_yet(tmp_path: Path) -> None:
    raw = json.loads((REPO / "config" / "policy.json").read_text())
    raw["rules"] = [{"id": "R01"}]
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValidationError):  # Phase 3 mới thêm schema luật
        load_policy(path)


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
                    "scope: single_device, privilege_level: standard_user}\n")  # thiếu 2 action
    with pytest.raises(RuntimeError, match="thiếu metadata cho vpn: \\['check_vpn_status', 'reissue_vpn_access'\\]"):
        check_intent_config(Settings(_env_file=None), get_slots(), load_action_metadata(path))  # type: ignore[call-arg]


def test_enabled_intent_without_slots_refuses_startup() -> None:
    settings = Settings(_env_file=None, enabled_intents=["vpn", "account"])  # type: ignore[call-arg]
    with pytest.raises(RuntimeError, match="account"):
        check_intent_config(settings, get_slots(), get_action_metadata())


_META = "scope: single_device, privilege_level: standard_user"


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
