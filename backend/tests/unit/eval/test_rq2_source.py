"""RQ2 — dựng lại đầu vào B14 từ `prompt_full` của 5 phiếu S1 (dữ liệu GIẢ render bằng `render` của gateway) + kiểm byte."""

import json
from typing import Any

import pytest
from app.eval.rq2.source import (
    ESTIMATE_PROMPT,
    Rejected,
    VoteCall,
    fetch_vote_calls,
    parse_evidence,
    rebuild,
    sample_index,
)
from app.llm.context import EMPTY, render
from tests.fakes.llm import repo_registry
from tests.unit.eval.rq2_fakes import (
    BUDGET_IN,
    FakeSql,
    prompt_full,
    variables,
    vote_calls,
    vote_prompt,
)


def _estimate(vars_: dict[str, Any], budget_in: int = BUDGET_IN) -> str:
    return prompt_full(repo_registry().get(ESTIMATE_PROMPT), vars_, budget_in=budget_in)


def test_rebuild_gives_byte_identical_estimate_input() -> None:
    """Đầu vào (a) dựng lại render ra ĐÚNG từng byte như render từ biến gốc (score gốc khác nhau, bản dựng đặt bằng nhau)."""
    original = variables()
    got = rebuild("t1", vote_calls(original), vote_prompt(), budget_in=BUDGET_IN)
    assert _estimate(got.variables) == _estimate(original)
    assert [e["anchor_chunk_id"] for e in got.variables["evidence"]] == ["kb-vpn-01#2", "kb-vpn-02#1"]
    assert got.variables["intended_action"] == original["intended_action"]
    assert len(got.messages) == 5 and "số 0." in got.messages[0][1]["content"]


def test_rebuild_trimming_order_matches_original_under_small_budget() -> None:
    """Score không được render; điểm bằng nhau giữ đúng thứ tự cắt (khối cuối trước) như score gốc giảm dần."""
    original = variables()
    got = rebuild("t1", vote_calls(original), vote_prompt(), budget_in=BUDGET_IN)
    est_full = render(repo_registry().get(ESTIMATE_PROMPT), original, budget_in=BUDGET_IN).est_tokens
    small = est_full - 5  # buộc cắt đúng một khối
    a = render(repo_registry().get(ESTIMATE_PROMPT), original, budget_in=small)
    b = render(repo_registry().get(ESTIMATE_PROMPT), got.variables, budget_in=small)
    assert a.trimmed_evidence == b.trimmed_evidence == 1
    assert a.messages == b.messages


def test_rebuild_empty_evidence() -> None:
    original = variables(evidence=[])
    got = rebuild("t1", vote_calls(original), vote_prompt(), budget_in=BUDGET_IN)
    assert got.variables["evidence"] == []
    assert EMPTY in got.messages[0][1]["content"]
    assert _estimate(got.variables) == _estimate(original)


def test_rebuild_text_that_looks_like_a_header_still_byte_identical() -> None:
    tricky = [{"anchor_chunk_id": "kb-a#1", "title": "A", "heading_path": "H",
               "text": "dòng 1\n\n[kb-gia#9] Giả › Mục\nvẫn là đoạn của kb-a", "score": 0.9}]  # fmt: skip
    got = rebuild("t1", vote_calls(variables(tricky)), vote_prompt(), budget_in=BUDGET_IN)
    assert _estimate(got.variables) == _estimate(variables(tricky))


def test_more_than_three_blocks_rejected() -> None:
    four = [{"anchor_chunk_id": f"kb-{i}#1", "title": "T", "heading_path": "H", "text": "x", "score": 0.9} for i in range(4)]
    with pytest.raises(Rejected) as e:
        rebuild("t1", vote_calls(variables(four)), vote_prompt(), budget_in=BUDGET_IN)
    assert e.value.reason == "too_many_evidence"


@pytest.mark.parametrize(("trimmed", "reason"), [(1, "trimmed_evidence"), (None, "trimmed_unknown")])
def test_trimmed_or_unknown_rejected(trimmed: int | None, reason: str) -> None:
    with pytest.raises(Rejected) as e:
        rebuild("t1", vote_calls(trimmed=trimmed), vote_prompt(), budget_in=BUDGET_IN)
    assert e.value.reason == reason


def _tamper(call: VoteCall, old: str, new: str) -> VoteCall:
    assert call.prompt_full is not None and old in call.prompt_full
    return VoteCall(call.call_id, call.provider, call.model, call.prompt_version, call.prompt_full.replace(old, new, 1),
                    call.error, call.trimmed_evidence)  # fmt: skip


def test_rerender_mismatch_rejected() -> None:
    calls = vote_calls()
    # JSON vẫn đọc được nhưng không còn dạng gọn của `_fmt` → render lại lệch byte
    calls[0] = _tamper(calls[0], '\\"target\\":\\"user\\"', '\\"target\\": \\"user\\"')
    with pytest.raises(Rejected) as e:
        rebuild("t1", calls, vote_prompt(), budget_in=BUDGET_IN)
    assert e.value.reason == "rerender_mismatch"


def test_inconsistent_votes_rejected() -> None:
    calls = vote_calls()
    calls[2] = _tamper(calls[2], "tenure_days\\\":12", "tenure_days\\\":13")
    with pytest.raises(Rejected) as e:
        rebuild("t1", calls, vote_prompt(), budget_in=BUDGET_IN)
    assert e.value.reason == "inconsistent_votes"


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda cs: cs[:4], "vote_calls_count"),
        (lambda cs: [cs[0], cs[0], *cs[2:]], "sample_idx"),
        (lambda cs: [VoteCall(c.call_id, c.provider, c.model, c.prompt_version, c.prompt_full, "LLMUnavailable",
                              c.trimmed_evidence) for c in cs], "vote_call_error"),
        (lambda cs: [VoteCall(c.call_id, c.provider, f"m{i}", c.prompt_version, c.prompt_full, None, c.trimmed_evidence)
                     for i, c in enumerate(cs)], "mixed_target"),
        (lambda cs: [VoteCall(c.call_id, c.provider, c.model, c.prompt_version, None, None, c.trimmed_evidence) for c in cs],
         "prompt_full_missing"),
    ],
    ids=["4_phieu", "trung_sample_idx", "loi_goi", "nhieu_model", "thieu_prompt_full"],
)  # fmt: skip
def test_rejections(mutate: Any, reason: str) -> None:
    with pytest.raises(Rejected) as e:
        rebuild("t1", mutate(vote_calls()), vote_prompt(), budget_in=BUDGET_IN)
    assert e.value.reason == reason


def test_parse_evidence_requires_header_at_start() -> None:
    with pytest.raises(Rejected):
        parse_evidence("không có đầu khối")


def test_sample_index() -> None:
    calls = vote_calls(order=(0, 1, 2, 3, 4))
    assert [sample_index(vote_prompt(), c) for c in calls] == [0, 1, 2, 3, 4]


def test_fetch_vote_calls_query_and_parse() -> None:
    calls = vote_calls(trimmed=0)
    sql = FakeSql({"tk-1": calls}, {})
    got = fetch_vote_calls(sql, "tk-1")
    assert got == calls
    q = sql.queries[0]
    assert "t.ticket_id = 'tk-1'" in q and "c.prompt_id = 'b14_risk_vote'" in q
    assert "spans s ON s.span_id = c.span_id" in q and "turns t ON t.turn_id = s.turn_id" in q
    assert json.loads(got[0].prompt_full or "[]")[0]["role"] == "system"
