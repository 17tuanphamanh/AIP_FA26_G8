"""R2 (soát 12/11 agent 16 F2): ngưỡng `RETRIEVAL_THRESHOLD` áp cho MỌI đoạn đưa vào bằng chứng, không chỉ đoạn hạng 1.

- Trước: hạng 1 đạt ngưỡng thì cả top-5 (kể cả đoạn 0,02 của bài gây nhiễu) vào `expand_for_answer` và được trích làm nguồn.
- Sau: chỉ đoạn có `score ≥ RETRIEVAL_THRESHOLD` vào bằng chứng; LLM trích đoạn dưới ngưỡng → không còn là anchor hợp lệ → E3
  `invalid_citation` như mọi trích dẫn ngoài bằng chứng. B9 (hạng 1 dưới ngưỡng → E3) không đổi.
"""

from typing import Any

import pytest
from app.domain.states import S_CONFIRMING, S_ESCALATED
from app.domain.ticket_state import ChunkRef
from app.llm.providers.scripted import Reply
from app.rag.models import EvidenceBlock
from tests.fakes.rag import FakeRag
from tests.unit.test_d80_rewrite_query import _env, _node, _result, _state

pytestmark = pytest.mark.asyncio


def _c(doc: str, seq: int, score: float) -> ChunkRef:
    return ChunkRef(chunk_id=f"{doc}#v1#{seq}", doc_id=doc, version=1, seq=seq, title=doc, heading_path=f"Mục {seq}", score=score,
                    excerpt="x")  # fmt: skip


TOP = _c("KB-VPN-001", 1, 0.91)
OK2 = _c("KB-VPN-001", 2, 0.75)
NOISE = _c("KB-GEN-009", 2, 0.02)  # bài gây nhiễu, điểm rất thấp
CHUNKS = [TOP, OK2, NOISE]


def _rag() -> FakeRag:
    return FakeRag(result=_result(CHUNKS), evidence=[
        EvidenceBlock(anchor_chunk_id=c.chunk_id, doc_id=c.doc_id, title=c.title, heading_path=c.heading_path, score=c.score,
                      text="Nội dung.", tokens=10) for c in CHUNKS])  # fmt: skip


def _ans(cite: str) -> Reply:
    return Reply({"answer_markdown": "Làm như sau.", "citations": [cite], "steps": ["Bước 1"], "cannot_answer": False})


async def _run(cite: str) -> tuple[dict[str, Any], FakeRag]:
    rag = _rag()
    h, _gw, _ = _env(rag=rag, b10_answer=[_ans(cite)])
    out = await _node(h, _state(retrieved=list(CHUNKS), retrieval_score=TOP.score))
    return out, rag


async def test_doan_duoi_nguong_khong_vao_bang_chung() -> None:
    out, rag = await _run(TOP.chunk_id)
    assert out["status"] == S_CONFIRMING
    [(sent, _ctx)] = rag.expand_calls
    assert [c.chunk_id for c in sent] == [TOP.chunk_id, OK2.chunk_id]


async def test_trich_doan_duoi_nguong_la_trich_dan_sai() -> None:
    out, _ = await _run(NOISE.chunk_id)
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E3")
    assert out["escalation_reason_detail"] == "invalid_citation"
