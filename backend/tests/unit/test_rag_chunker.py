"""b4–b7 — chia đoạn theo token (D-21 + 3-Q17; PLAN-3b mục 5).

Số đo bằng tokenizer bge-m3 thật (`models/BAAI/bge-m3@5617a9f…/tokenizer.json`, 27/09/2026) trên fixture:
- KB-VPN-004, mục "## Thời hạn và quy định gia hạn chứng chỉ VPN" (3 đoạn văn p1, p2, p3):
  n(p1) = 175, n(p2) = 171, n(p3) = 70; n(p1 + "\n\n" + p2) = 344 ≤ 380; n(p1 + p2 + p3) = 412 ∈ [390, 440]
  → với trần 380: đoạn 344 + đoạn 70 (không gộp được: 412 > 380). Trần 480 (M-3b-3): một đoạn 412 → b4 đỏ ở
  `content_tokens <= 380`, không ở IngestError (text 412 + tiền tố ≈ 431 ≤ 480).
- KB-VPN-003, ba mục bước: "Bước 1–2" 185, "Bước 3–4" 185, "Bước 5–6" 161 token nội dung (∈ [130, 350]).
- Mọi mục H2 khác của fixture ≤ 191 token → đột biến trần 480 không sinh đoạn > 480 ở tài liệu khác.
"""

from pathlib import Path

import pytest
from app.core.clock import FakeClock
from app.rag.ingest.chunker import chunk_doc
from app.rag.ingest.loader import load_kb
from app.rag.models import Chunk, Doc, FrontMatter, IngestError
from app.rag.token_counter import LocalTokenizerCounter
from tests.fakes.kb import FIXTURE_KB, FRONT, KB_TEST_NOW
from tests.fakes.token_counter import WordCounter
from tests.fakes.tokenizer import require_bge_tokenizer

SPEC_KB = Path(__file__).resolve().parents[3] / "docs" / "spec" / "build" / "kb-mau"
FM = FrontMatter.model_validate({**FRONT, "enabled": True, "version": 1, "title": "Tài liệu thử"})


def _doc(body: str, start: int = 13) -> Doc:
    return Doc(FM, Path("x.md"), "kb/vpn/KB-VPN-901.md", body, start)


def words(n: int, w: str = "từ") -> str:
    return " ".join([w] * n)


async def _chunks(body: str) -> list[Chunk]:
    return await chunk_doc(_doc(body), WordCounter())


def test_fixture_vpn_001_is_spec_sample_verbatim() -> None:
    assert (FIXTURE_KB / "vpn" / "KB-VPN-001.md").read_bytes() == (SPEC_KB / "KB-VPN-001.md").read_bytes()


# ---- b4: fixture với tokenizer thật -----------------------------------------------------------


@pytest.mark.tokenizer_real
@pytest.mark.asyncio
async def test_b4_fixture_chunks_within_limits_real_tokenizer() -> None:
    counter = LocalTokenizerCounter(require_bge_tokenizer())
    docs, issues = load_kb(FIXTURE_KB, FakeClock(KB_TEST_NOW))
    assert issues == []
    enabled = [d for d in docs if d.fm.enabled]
    assert len(enabled) == 5
    for doc in enabled:
        chunks = await chunk_doc(doc, counter)
        assert [c.seq for c in chunks] == list(range(len(chunks)))
        for c in chunks:
            assert c.text_tokens <= 480
            assert c.content_tokens <= 380
            assert c.heading_path
            assert c.chunk_id == f"{doc.fm.doc_id}#v{doc.fm.version}#{c.seq}"
            assert c.text == f"{doc.fm.title} › {c.heading_path}\n\n{c.content}"


@pytest.mark.tokenizer_real
@pytest.mark.asyncio
async def test_b4_fixture_step_sections_are_separate_chunks() -> None:
    counter = LocalTokenizerCounter(require_bge_tokenizer())
    docs, _ = load_kb(FIXTURE_KB, FakeClock(KB_TEST_NOW))
    by_id = {d.fm.doc_id: d for d in docs}
    vpn003 = await chunk_doc(by_id["KB-VPN-003"], counter)
    steps = [c for c in vpn003 if c.heading_path.startswith("Bước ")]
    assert [c.heading_path[:8] for c in steps] == ["Bước 1–2", "Bước 3–4", "Bước 5–6"]
    assert all(130 <= c.content_tokens <= 350 for c in steps)
    vpn004 = await chunk_doc(by_id["KB-VPN-004"], counter)
    first_h2 = [c.content_tokens for c in vpn004 if c.h2.startswith("Thời hạn")]
    assert first_h2 == [344, 70]


# ---- b5: gộp đoạn nhỏ (WordCounter: số từ + 2) -------------------------------------------------


@pytest.mark.asyncio
async def test_b5_merge_into_next_across_h3_keeps_h2_only() -> None:
    chunks = await _chunks(f"## A\n\n{words(50)}\n\n### Y\n\n{words(200)}\n")
    assert [(c.heading_path, c.content_tokens) for c in chunks] == [("A", 252)]


@pytest.mark.asyncio
async def test_b5_merge_into_previous_when_last_of_h2() -> None:
    chunks = await _chunks(f"## A\n\n### X\n\n{words(200)}\n\n### Y\n\n{words(50)}\n\n## B\n\n{words(200)}\n")
    assert [(c.heading_path, c.content_tokens) for c in chunks] == [("A", 252), ("B", 202)]


@pytest.mark.asyncio
async def test_b5_merge_into_previous_when_next_too_big() -> None:
    body = f"## A\n\n### X\n\n{words(200)}\n\n### Y\n\n{words(50)}\n\n### Z\n\n{words(340)}\n"
    chunks = await _chunks(body)
    assert [(c.heading_path, c.content_tokens) for c in chunks] == [("A", 252), ("A › Z", 342)]


@pytest.mark.asyncio
async def test_b5_keep_small_when_no_merge_fits() -> None:
    chunks = await _chunks(f"## A\n\n{words(300)}\n\n{words(100)}\n\n## B\n\n{words(50)}\n")
    assert [(c.heading_path, c.content_tokens) for c in chunks] == [("A", 302), ("A", 102), ("B", 52)]


@pytest.mark.asyncio
async def test_b5_whole_doc_under_120_is_one_chunk() -> None:
    chunks = await _chunks(f"## A\n\n{words(30)}\n\n{words(20)}\n")
    assert [(c.heading_path, c.content_tokens, c.seq) for c in chunks] == [("A", 52, 0)]


@pytest.mark.asyncio
async def test_b5_two_small_h3_merge_to_h2() -> None:
    chunks = await _chunks(f"## A\n\n### X\n\n{words(60)}\n\n### Y\n\n{words(60)}\n")
    assert [(c.heading_path, c.content_tokens) for c in chunks] == [("A", 122)]
    assert chunks[0].start_line == 17  # dòng đầu nội dung của ### X (body từ dòng 13)


# ---- b6: câu quá dài ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b6_long_sentence() -> None:
    body = f"## A\n\nCâu mở đầu ngắn.\n{words(400)} không có dấu chấm nào\n"
    with pytest.raises(IngestError) as e:
        await _chunks(body)
    assert e.value.line == 16  # ## A 13, trống 14, câu ngắn 15, câu dài 16
    assert "câu quá dài" in str(e.value) and "> 380" in str(e.value)
    assert str(e.value).startswith("kb/vpn/KB-VPN-901.md:16: ")


@pytest.mark.asyncio
async def test_long_paragraph_split_by_sentences() -> None:
    sentence = words(90) + "."
    chunks = await _chunks("## A\n\n" + " ".join([sentence] * 6) + "\n")
    assert [c.content_tokens for c in chunks] == [4 * 90 + 2, 2 * 90 + 2]  # câu = 90 từ
    assert chunks[0].content == " ".join([sentence] * 4)


@pytest.mark.asyncio
async def test_long_list_split_by_items() -> None:
    items = "\n".join(f"{i}. {words(100)}" for i in range(1, 6))
    chunks = await _chunks(f"## A\n\n{items}\n")
    assert [c.content_tokens for c in chunks] == [3 * 101 + 2, 2 * 101 + 2]
    assert chunks[0].content.split("\n")[0].startswith("1. ") and chunks[1].content.startswith("4. ")
    assert chunks[1].start_line == 18


# ---- b7: code fence -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b7_heading_in_code_fence() -> None:
    body = "## A\n\nTrước fence.\n\n```\n## không phải mục\n\nvẫn trong fence\n```\n\nSau fence.\n"
    chunks = await _chunks(body)
    assert len(chunks) == 1 and chunks[0].heading_path == "A"
    assert chunks[0].content == "Trước fence.\n\n```\n## không phải mục\n\nvẫn trong fence\n```\n\nSau fence."


@pytest.mark.asyncio
async def test_html_removed_overview_and_list_block() -> None:
    body = "Lời dẫn <b>đậm</b>.\n<!-- ghi chú\nnhiều dòng -->\n## A\n\n- một\n\n- hai\n- ba\n"
    chunks = await _chunks(body)
    assert [(c.heading_path, c.content) for c in chunks] == [
        ("Tổng quan", "Lời dẫn đậm."),
        ("A", "- một\n\n- hai\n- ba"),
    ]
    assert chunks[1].start_line == 18


@pytest.mark.asyncio
async def test_text_over_480_is_error() -> None:
    long_title = FM.model_copy(update={"title": words(100)})
    doc = Doc(long_title, Path("x.md"), "kb/vpn/KB-VPN-901.md", f"## {words(50)}\n\n{words(350)}\n", 13)
    with pytest.raises(IngestError, match="token > 480"):
        await chunk_doc(doc, WordCounter())
