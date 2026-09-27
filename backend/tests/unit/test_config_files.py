"""config/policy.json và config/slots.yaml: đúng hằng số [Chốt 01 mục 5.2], sai schema → lỗi."""

import json
from pathlib import Path

import pytest
from app.settings import get_policy, get_slots, load_policy, load_slots
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[3]


def test_policy_constants_match_spec() -> None:
    c = get_policy().constants
    assert (c.MAX_LOOPS, c.MAX_CLARIFICATION_TURNS, c.TOOL_RETRY, c.BACKOFF_BASE_SECONDS) == (5, 3, 2, 1)
    assert (c.MAX_AUTH_FAILURES, c.AUTH_FAILURE_WINDOW_MINUTES, c.SLA_MINUTES) == (5, 10, 30)
    assert (c.THRESHOLD_LOW, c.THRESHOLD_HIGH, c.RETRIEVAL_THRESHOLD) == (0.25, 0.75, 0.6)
    assert (c.CLARIFY_TIMEOUT_HOURS, c.CONFIRM_TIMEOUT_HOURS) == (24, 48)


def test_tool_arg_slots_match_b11() -> None:
    assert get_slots().tool_arg_slots == {"device_id", "resource_path", "target_user", "software_name",
                                          "account_type"}  # fmt: skip


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
