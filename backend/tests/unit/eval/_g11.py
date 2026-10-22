"""Dựng dữ liệu + người chấm giả cho test groundedness (G11). Người chấm = `LLMClient` THẬT + ScriptedLLM (tests.fakes.llm).

Quy ước ý giả: câu chứa "[S]" → `supported` (đoạn đầu tiên trong bằng chứng), "[S2]" → supported bởi đoạn thứ hai, "[P]" → partial
(đoạn đầu), còn lại → unsupported. Người chấm giả đọc `variables["claims"]` và `variables["evidence"]` như gateway thật nhận.
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from app.eval.groundedness.models import AnswerRow, Chunk, JudgedAnswer, JudgedClaim
from app.llm.providers.scripted import Reply, Step
from tests.fakes.llm import Gateway, make_gateway


def chunk(chunk_id: str, text: str = "nội dung đoạn") -> dict[str, Any]:
    return {"chunk_id": chunk_id, "text": text}


def family_of(scenario_id: str) -> str:
    """Chỉ cho DỮ LIỆU TEST: họ của kịch bản giả = phần trước `-v`. Code thật KHÔNG suy họ — `family` bắt buộc trong answers.jsonl."""
    return scenario_id.rsplit("-v", 1)[0]


def row(
    scenario_id: str = "TC04-v1", answer: str = "", citations: tuple[str, ...] = ("A",), *, chunks: tuple[str, ...] = ("A", "B", "C"),
    steps: tuple[str, ...] | None = None, family: str | None = None, cannot_answer: bool = False,
) -> AnswerRow:  # fmt: skip
    return AnswerRow.model_validate({
        "scenario_id": scenario_id, "family": family or family_of(scenario_id), "answer": answer, "steps": steps, "citations": citations,
        "chunks": [chunk(c, f"văn bản của {c}") for c in chunks], "cannot_answer": cannot_answer,
    })  # fmt: skip


def judge_script(variables: Mapping[str, Any]) -> Step:
    ids = [e["anchor_chunk_id"] for e in variables["evidence"]]
    verdicts: list[dict[str, Any]] = []
    for line in str(variables["claims"]).splitlines():
        no, _, text = line.partition(". ")
        if "[S2]" in text and len(ids) > 1:
            verdicts.append({"claim_id": int(no), "verdict": "supported", "chunk_ids": [ids[1]]})
        elif "[S]" in text:
            verdicts.append({"claim_id": int(no), "verdict": "supported", "chunk_ids": [ids[0]]})
        elif "[P]" in text:
            verdicts.append({"claim_id": int(no), "verdict": "partial", "chunk_ids": [ids[0]]})
        else:
            verdicts.append({"claim_id": int(no), "verdict": "unsupported", "chunk_ids": []})
    return Reply({"verdicts": verdicts})


def gateway(script: Any = judge_script, **kw: Any) -> Gateway:
    return make_gateway({"eval_groundedness": script}, **kw)


def factory(run_id: str, **_: Any) -> Any:
    """`--llm-factory tests.unit.eval._g11:factory` — gateway mới mỗi lần gọi (`fn(run_id[, max_usd=…])`, như `eval_gateway`)."""
    return gateway().client


def claim(cid: int, verdict: str, *chunk_ids: str, text: str | None = None) -> JudgedClaim:
    return JudgedClaim.model_validate({"claim_id": cid, "text": text or f"ý {cid}", "verdict": verdict,
                                       "chunk_ids": chunk_ids})  # fmt: skip


def judged(
    scenario_id: str, claims: tuple[JudgedClaim, ...], citations: tuple[str, ...] = (), *, family: str | None = None,
    status: str = "judged", flags: tuple[str, ...] = (), invalid: tuple[str, ...] = (), error: str | None = None,
) -> JudgedAnswer:  # fmt: skip
    return JudgedAnswer.model_validate({
        "scenario_id": scenario_id, "family": family or family_of(scenario_id), "status": status, "flags": flags,
        "citations": citations, "invalid_citations": invalid, "error": error, "claims": claims,
    })  # fmt: skip


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")


def answers_file(path: Path, n_weak: int = 6, n_solid: int = 6) -> list[dict[str, Any]]:
    """`answers.jsonl` giả: `n_weak` ca có ý không được hỗ trợ (hai họ), `n_solid` ca mọi ý được hỗ trợ."""
    records: list[dict[str, Any]] = []
    for i in range(n_weak):
        records.append({
            "scenario_id": f"W{i % 2}-v{i}", "family": f"W{i % 2}", "answer": "Mở ứng dụng VPN [S]. Đây là ý bịa [X].", "steps": ["Bấm Connect [S2]"],
            "citations": ["A", "B"], "chunks": [chunk("A", "bước A"), chunk("B", "bước B")],
        })  # fmt: skip
    for i in range(n_solid):
        records.append({
            "scenario_id": f"S{i % 3}-v{i}", "family": f"S{i % 3}", "answer": "VPN dùng cổng 443 [S].", "citations": ["A"],
            "chunks": [chunk("A", "cổng 443")],
        })  # fmt: skip
    write_jsonl(path, records)
    return records


__all__ = ["Chunk", "answers_file", "chunk", "claim", "factory", "family_of", "gateway", "judge_script", "judged", "row", "write_jsonl"]
