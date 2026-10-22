"""G11 — người chấm (`app.eval.groundedness.judge`) qua `LLMClient` THẬT + ScriptedLLM: bằng chứng chỉ gồm đoạn đã dẫn, hợp đồng
verdict, lỗi LLM/hợp đồng thành ca `error` (không phải "không được hỗ trợ"), ca không tốn lời gọi."""

from typing import Any

import pytest
from app.eval.groundedness import judge
from app.eval.groundedness.judge import NO_CITATION, judge_all, judge_answer
from app.eval.groundedness.models import MAX_CLAIMS
from app.llm.providers.scripted import BadJSON, Reply
from app.llm.schemas import ClaimVerdict, GroundednessOut
from pydantic import ValidationError
from tests.unit.eval._g11 import gateway, judge_script, row


@pytest.mark.asyncio
async def test_happy_path_verdicts_and_evidence_only_cited_chunks_in_citation_order() -> None:
    gw = gateway()
    r = row(answer="Mở VPN [S].\nĐây là ý bịa [X].\nCòn ý này [P].", citations=("B", "A"), chunks=("A", "B", "C"))
    ans, meta = await judge_answer(gw.client, r)
    assert ans.status == "judged" and ans.error is None and ans.flags == ()
    assert [(c.claim_id, c.verdict, c.chunk_ids) for c in ans.claims] == [
        (1, "supported", ("B",)), (2, "unsupported", ()), (3, "partial", ("B",)),
    ]  # fmt: skip
    assert meta is not None and meta.prompt_id == "eval_groundedness" and meta.trimmed_evidence == 0
    [call] = gw.llm.calls
    assert call.prompt_id == "eval_groundedness"
    assert [e["anchor_chunk_id"] for e in call.variables["evidence"]] == ["B", "A"]  # đúng thứ tự dẫn, KHÔNG có C
    assert call.variables["claims"] == "1. Mở VPN [S].\n2. Đây là ý bịa [X].\n3. Còn ý này [P]."
    assert "văn bản của B" in call.rendered_messages[1]["content"] and "văn bản của C" not in call.rendered_messages[1]["content"]


@pytest.mark.asyncio
async def test_judge_uses_strong_role_model_of_scripted_backend() -> None:
    gw = gateway()
    _, meta = await judge_answer(gw.client, row(answer="Ý [S]."))
    assert meta is not None and meta.model == "scripted"
    assert judge.ROLE == "strong" and judge.PROMPT_ID == "eval_groundedness"


@pytest.mark.asyncio
async def test_cannot_answer_has_no_claims_and_no_call() -> None:
    gw = gateway()
    ans, meta = await judge_answer(gw.client, row(answer="", citations=(), cannot_answer=True))
    assert (ans.status, ans.claims, meta) == ("cannot_answer", (), None) and gw.llm.calls == []


@pytest.mark.asyncio
async def test_no_claims_has_no_call() -> None:
    gw = gateway()
    ans, _ = await judge_answer(gw.client, row(answer="Làm như sau:"))
    assert ans.status == "no_claims" and gw.llm.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(("citations", "invalid"), [((), ()), (("X",), ("X",)), (("X", "Y"), ("X", "Y"))])
async def test_no_valid_citation_means_all_unsupported_without_a_call(citations: tuple[str, ...], invalid: tuple[str, ...]) -> None:
    gw = gateway()
    ans, meta = await judge_answer(gw.client, row(answer="Ý một [S]. Ý hai [S].", citations=citations))
    assert ans.status == "judged" and ans.flags == (NO_CITATION,) and ans.invalid_citations == invalid
    assert [c.verdict for c in ans.claims] == ["unsupported", "unsupported"] and all(c.chunk_ids == () for c in ans.claims)
    assert meta is None and gw.llm.calls == []


@pytest.mark.asyncio
async def test_invalid_citation_alongside_valid_one_is_listed_and_only_valid_is_judged() -> None:
    gw = gateway()
    ans, _ = await judge_answer(gw.client, row(answer="Ý [S].", citations=("A", "ZZ")))
    assert ans.invalid_citations == ("ZZ",) and ans.flags == ()
    assert [e["anchor_chunk_id"] for e in gw.llm.calls[0].variables["evidence"]] == ["A"]


@pytest.mark.asyncio
async def test_unsupported_verdict_drops_chunk_ids_and_supported_dedupes() -> None:
    def script(variables: Any) -> Any:
        return Reply({"verdicts": [
            {"claim_id": 1, "verdict": "unsupported", "chunk_ids": ["A"]},
            {"claim_id": 2, "verdict": "supported", "chunk_ids": ["A", "A", "B"]},
        ]})  # fmt: skip

    ans, _ = await judge_answer(gateway(script).client, row(answer="Ý một. Ý hai.", citations=("A", "B")))
    assert [(c.verdict, c.chunk_ids) for c in ans.claims] == [("unsupported", ()), ("supported", ("A", "B"))]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("verdicts", "reason"),
    [
        ([{"claim_id": 1, "verdict": "unsupported", "chunk_ids": []}], "claim_ids"),  # thiếu ý 2
        ([{"claim_id": 1, "verdict": "unsupported", "chunk_ids": []}] * 2, "claim_ids"),  # trùng ý 1
        ([{"claim_id": 1, "verdict": "unsupported", "chunk_ids": []}, {"claim_id": 3, "verdict": "unsupported", "chunk_ids": []}], "claim_ids"),
        ([{"claim_id": 1, "verdict": "unsupported", "chunk_ids": []},
          {"claim_id": 2, "verdict": "supported", "chunk_ids": ["C"]}], "chunk_ids_outside_evidence"),  # C không được dẫn
        ([{"claim_id": 1, "verdict": "partial", "chunk_ids": ["ZZ"]},
          {"claim_id": 2, "verdict": "unsupported", "chunk_ids": []}], "chunk_ids_outside_evidence"),
    ],
)  # fmt: skip
async def test_contract_violation_is_an_error_case_not_a_verdict(verdicts: list[dict[str, Any]], reason: str) -> None:
    gw = gateway(lambda v: Reply({"verdicts": verdicts}))
    ans, meta = await judge_answer(gw.client, row(answer="Ý một. Ý hai.", citations=("A",)))
    assert ans.status == "error" and ans.error == f"judge_contract:{reason}" and ans.claims == ()
    assert meta is not None


@pytest.mark.asyncio
async def test_llm_schema_failure_is_error_case() -> None:
    bad = Reply({"verdicts": []})  # min_length=1 → sai schema; gateway sửa một lần rồi bỏ
    ans, _ = await judge_answer(gateway([bad, bad]).client, row(answer="Ý [S]."))
    assert (ans.status, ans.error) == ("error", "LLMSchemaError")
    bad_json = [BadJSON("không phải json"), BadJSON("vẫn không")]
    ans2, _ = await judge_answer(gateway(bad_json).client, row(answer="Ý [S]."))
    assert (ans2.status, ans2.error) == ("error", "LLMSchemaError")


@pytest.mark.asyncio
async def test_evidence_trimmed_by_gateway_is_error_not_a_verdict() -> None:
    big = "x" * 9000  # ~3000 token mỗi đoạn; hai đoạn vượt budget_in 6000 của strong → gateway cắt một khối
    r = row(answer="Ý [S].", citations=("A", "B"))
    r = r.model_copy(update={"chunks": tuple(c.model_copy(update={"text": big}) for c in r.chunks)})
    gw = gateway()
    ans, meta = await judge_answer(gw.client, r)
    assert meta is not None and meta.trimmed_evidence >= 1
    assert (ans.status, ans.error) == ("error", "evidence_truncated") and ans.claims == ()


@pytest.mark.asyncio
async def test_single_oversized_chunk_is_also_evidence_truncated() -> None:
    r = row(answer="Ý [S].", citations=("A",))
    r = r.model_copy(update={"chunks": tuple(c.model_copy(update={"text": "x" * 60000}) for c in r.chunks)})
    ans, meta = await judge_answer(gateway().client, r)
    assert (ans.status, ans.error) == ("error", "evidence_truncated") and meta is not None and meta.trimmed_evidence == 1


@pytest.mark.asyncio
async def test_claims_alone_over_budget_is_llm_budget_error() -> None:
    ans, meta = await judge_answer(gateway().client, row(answer="Ý rất dài " + "y" * 60000 + " [S]."))
    assert (ans.status, ans.error, meta) == ("error", "LLMBudgetExceeded", None)


@pytest.mark.asyncio
async def test_too_many_claims_is_error_without_a_call() -> None:
    gw = gateway()
    text = "\n".join(f"{i}. Ý số {i}" for i in range(1, MAX_CLAIMS + 2))
    ans, _ = await judge_answer(gw.client, row(answer=text))
    assert ans.status == "error" and ans.error == f"too_many_claims:{MAX_CLAIMS + 1}" and gw.llm.calls == []


@pytest.mark.asyncio
async def test_other_exceptions_are_bugs_and_propagate() -> None:
    def boom(variables: Any) -> Any:
        raise RuntimeError("bug trong kịch bản")

    with pytest.raises(RuntimeError):
        await judge_answer(gateway(boom).client, row(answer="Ý [S]."))


@pytest.mark.asyncio
async def test_judge_all_is_sequential_keeps_order_and_collects_metas() -> None:
    gw = gateway(cache_mode="eval")
    rows = [row(f"S{i}-v1", "Ý [S].") for i in range(3)] + [row("CA-v1", "", (), cannot_answer=True)]
    run = await judge_all(gw.client, rows)
    assert [a.scenario_id for a in run.answers] == ["S0-v1", "S1-v1", "S2-v1", "CA-v1"]
    assert len(run.metas) == 3 and len(gw.llm.calls) == 1  # 3 ca cùng nội dung → 1 lời gọi thật + 2 lần trúng cache (cache eval)
    assert [m.cache_hit for m in run.metas] == [False, True, True]
    assert {a.family for a in run.answers} == {"S0", "S1", "S2", "CA"}


def test_groundedness_schema_contract() -> None:
    with pytest.raises(ValidationError):
        ClaimVerdict(claim_id=1, verdict="supported", chunk_ids=[])  # supported phải kèm đoạn
    ClaimVerdict(claim_id=1, verdict="partial", chunk_ids=[])
    with pytest.raises(ValidationError):
        GroundednessOut(verdicts=[])
    with pytest.raises(ValidationError):
        GroundednessOut.model_validate({"verdicts": [{"claim_id": 1, "verdict": "unsupported", "extra": 1}]})
    with pytest.raises(ValidationError):
        GroundednessOut(verdicts=[ClaimVerdict(claim_id=i, verdict="unsupported") for i in range(1, 26)])
    assert judge_script is not None
