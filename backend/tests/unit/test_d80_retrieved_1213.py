"""R1 (CLI-5, soát 12/11 agent 16 F4): D-80 viết lại câu hỏi và truy hồi lại ĐẠT ngưỡng → state `retrieved`, `retrieval_score`,
`kb_version` phải là kết quả MỚI (bài đã dùng để trả lời), không giữ kết quả cũ dưới ngưỡng — ghi chú bàn giao L2 đọc state (nếu sau đó
ra E8/E3 thì L2 thấy đúng bài, không thấy câu "KB còn thiếu"). Viết lại thất bại → state giữ nguyên như cũ.
"""

from typing import Any

import pytest
from app.audit.handoff import build_handoff
from app.domain.states import S_CONFIRMING
from app.domain.ticket_state import ChunkRef
from app.llm.providers.scripted import Reply, Unavailable
from app.settings import get_escalation_templates
from tests.unit.test_d80_rewrite_query import HIGH, REWRITTEN, _env, _node, _state

pytestmark = pytest.mark.asyncio

OLD = [ChunkRef(chunk_id="KB-GEN-014#v1#1", doc_id="KB-GEN-014", version=1, seq=1, title="Khác", heading_path="Mục 1", score=0.12,
                excerpt="x")]  # fmt: skip


async def test_viet_lai_dat_nguong_cap_nhat_retrieved() -> None:
    h, _gw, _rag = _env(b09_rewrite_query=[Reply({"query": REWRITTEN})], b10_answer=[Reply({
        "answer_markdown": "Bạn kiểm tra máy in như sau.", "citations": [HIGH[0].chunk_id], "steps": ["Bật máy in"],
        "cannot_answer": False})])  # fmt: skip
    out = await _node(h, _state(retrieved=list(OLD), retrieval_score=0.12))
    assert out["status"] == S_CONFIRMING
    assert [c.doc_id for c in out["retrieved"]] == ["KB-GEN-002", "KB-GEN-002"]
    assert out["retrieval_score"] == pytest.approx(HIGH[0].score)
    state: dict[str, Any] = {**_state(), **out, "exit_code": "E8", "escalation_reason_detail": None}
    note = build_handoff(state, get_escalation_templates(), retrieval_threshold=0.6)
    assert "KB-GEN-002" in note.done_so_far and "KB-GEN-014" not in note.done_so_far
    assert "dưới ngưỡng" not in note.done_so_far


async def test_viet_lai_that_bai_giu_state_cu() -> None:
    h, _gw, _rag = _env(b09_rewrite_query=[Unavailable(), Unavailable(), Unavailable()])
    out = await _node(h, _state(retrieved=list(OLD), retrieval_score=0.12))
    assert out["exit_code"] == "E3"
    assert "retrieved" not in out and "retrieval_score" not in out  # không ghi đè kết quả cũ
