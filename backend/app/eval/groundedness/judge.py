"""LLM chấm từng ý (G11): MỘT lần gọi `eval_groundedness` (strong) cho mỗi câu trả lời, qua gateway (`LlmPort`).

Người chấm chỉ thấy các đoạn ĐÃ DẪN có trong `chunks` (theo thứ tự dẫn). Hợp đồng kiểm bằng code sau khi gateway trả:
đủ và không trùng `claim_id` 1..n; mọi `chunk_ids` ∈ đoạn đã đưa; gateway cắt bớt bằng chứng (`trimmed_evidence > 0`) → lỗi
(không chấm trên bằng chứng thiếu, như f1 của B10). Chạy tuần tự (P8: một luồng). Lỗi LLM/hợp đồng ghi vào kết quả của ca
(`status="error"`), KHÔNG làm dừng cả lô và KHÔNG bị tính là "không được hỗ trợ"; lỗi khác (bug) cứ nổi lên.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from app.core.errors import LLMBudgetExceeded, LLMSchemaError, LLMUnavailable
from app.eval.groundedness.models import (
    MAX_CLAIMS,
    AnswerRow,
    Chunk,
    JudgedAnswer,
    JudgedClaim,
)
from app.eval.groundedness.split import split_claims
from app.llm.ports import LLMMeta, LlmPort
from app.llm.schemas import GroundednessOut

PROMPT_ID = "eval_groundedness"
ROLE: Literal["strong"] = "strong"
NO_CITATION = "no_citation"


@dataclass
class JudgeRun:
    answers: list[JudgedAnswer] = field(default_factory=list)
    metas: list[LLMMeta] = field(default_factory=list)


def _title(chunk: Chunk) -> str:
    return chunk.title or chunk.doc_id or chunk.chunk_id


def _evidence(chunks: Sequence[Chunk]) -> list[dict[str, object]]:
    """Khối bằng chứng cho gateway; `score` giảm theo thứ tự dẫn (nếu bị cắt thì cắt đoạn dẫn sau cùng — nhưng cắt = lỗi)."""
    n = len(chunks)
    return [
        {"anchor_chunk_id": c.chunk_id, "title": _title(c), "heading_path": c.heading_path or "", "text": c.text,
         "score": float(n - i)}
        for i, c in enumerate(chunks)
    ]  # fmt: skip


def _numbered(claims: Sequence[str]) -> str:
    return "\n".join(f"{i}. {c}" for i, c in enumerate(claims, 1))


def _answer(row: AnswerRow, status: str, **over: object) -> JudgedAnswer:
    base: dict[str, object] = {"scenario_id": row.scenario_id, "family": row.family_name, "status": status,
                               "citations": row.citations}  # fmt: skip
    return JudgedAnswer.model_validate(base | over)


def _contract_error(out: GroundednessOut, n_claims: int, valid: set[str]) -> str | None:
    ids = [v.claim_id for v in out.verdicts]
    if sorted(ids) != list(range(1, n_claims + 1)):
        return "claim_ids"
    if any(not set(v.chunk_ids) <= valid for v in out.verdicts):
        return "chunk_ids_outside_evidence"
    return None


def _claims(texts: Sequence[str], out: GroundednessOut) -> tuple[JudgedClaim, ...]:
    by_id = {v.claim_id: v for v in out.verdicts}
    claims: list[JudgedClaim] = []
    for i, text in enumerate(texts, 1):
        v = by_id[i]
        ids = () if v.verdict == "unsupported" else tuple(dict.fromkeys(v.chunk_ids))
        claims.append(JudgedClaim(claim_id=i, text=text, verdict=v.verdict, chunk_ids=ids))
    return tuple(claims)


async def judge_answer(llm: LlmPort, row: AnswerRow) -> tuple[JudgedAnswer, LLMMeta | None]:
    if row.cannot_answer:
        return _answer(row, "cannot_answer"), None
    texts = split_claims(row.answer, row.steps)
    if not texts:
        return _answer(row, "no_claims"), None
    if len(texts) > MAX_CLAIMS:
        return _answer(row, "error", error=f"too_many_claims:{len(texts)}"), None
    by_id = {c.chunk_id: c for c in row.chunks}
    valid_cited = [c for c in row.citations if c in by_id]
    invalid = tuple(c for c in row.citations if c not in by_id)
    if not valid_cited:  # không có gì để chấm: mọi ý không được hỗ trợ (không tốn lời gọi)
        claims = tuple(JudgedClaim(claim_id=i, text=t, verdict="unsupported") for i, t in enumerate(texts, 1))
        return _answer(row, "judged", flags=(NO_CITATION,), invalid_citations=invalid, claims=claims), None
    variables = {"claims": _numbered(texts), "evidence": _evidence([by_id[c] for c in valid_cited])}
    try:
        out, meta = await llm.complete(ROLE, PROMPT_ID, variables, GroundednessOut)
    except (LLMSchemaError, LLMUnavailable, LLMBudgetExceeded) as e:
        return _answer(row, "error", error=type(e).__name__, invalid_citations=invalid), None
    if meta.trimmed_evidence > 0:
        return _answer(row, "error", error="evidence_truncated", invalid_citations=invalid), meta
    problem = _contract_error(out, len(texts), set(valid_cited))
    if problem is not None:
        return _answer(row, "error", error=f"judge_contract:{problem}", invalid_citations=invalid), meta
    return _answer(row, "judged", invalid_citations=invalid, claims=_claims(texts, out)), meta


async def judge_all(llm: LlmPort, rows: Sequence[AnswerRow]) -> JudgeRun:
    run = JudgeRun()
    for row in rows:
        answer, meta = await judge_answer(llm, row)
        run.answers.append(answer)
        if meta is not None:
            run.metas.append(meta)
    return run
