"""Chia đoạn theo token (D-21 + 3-Q17; thiết kế Phase 3 mục 5.5; PLAN-3b mục 5).

Làm sạch → chia mục theo `##`/`###` → khối (dòng trống; fence là một khối; danh sách liên tiếp là một khối) → gom
tham lam trong một mục (nội dung ≤ `CHUNK_TOKENS_MAX`) → gộp đoạn nhỏ trong cùng H2 → văn bản đoạn
`"{title} › {heading_path}\n\n{content}"` (≤ `CHUNK_TEXT_MAX`). Mọi số đếm qua `TokenCounter` theo lô — không bao giờ
đếm bằng từ/ký tự; đếm CHÍNH XÁC chuỗi ghép chứ không cộng dồn số đếm lẻ. Không có gì bị cắt âm thầm: câu đơn vượt
trần → `IngestError` kèm dòng file.
"""

import re
from dataclasses import dataclass

from app.rag.ingest.config import (
    CHUNK_TEXT_MAX,
    CHUNK_TOKENS_MAX,
    CHUNK_TOKENS_MIN,
    COUNT_BATCH,
)
from app.rag.ingest.loader import fence_mask
from app.rag.models import Block, Chunk, Doc, IngestError
from app.rag.token_counter import TokenCounter

OVERVIEW = "Tổng quan"
PATH_SEP = " › "
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_HTML_TAG = re.compile(r"<[^>\n]+>")
_H2 = re.compile(r"^## +(.*?)\s*$")
_H3 = re.compile(r"^### +(.*?)\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_SENTENCE_SEP = re.compile(r"(?<=[.!?…])\s+|\n")


@dataclass(frozen=True)
class _Line:
    no: int  # số dòng file
    text: str
    in_fence: bool


@dataclass(frozen=True)
class _Section:
    h2: str
    path: str
    lines: list[_Line]


@dataclass(frozen=True)
class _Piece:
    """Đoạn trước khi gắn tiền tố: nội dung + số token nội dung."""

    h2: str
    path: str
    content: str
    tokens: int
    start_line: int


async def _count(counter: TokenCounter, texts: list[str]) -> list[int]:
    out: list[int] = []
    for i in range(0, len(texts), COUNT_BATCH):
        out.extend(await counter.count(texts[i : i + COUNT_BATCH]))
    return out


# ---- 1–2. Làm sạch, chia mục -------------------------------------------------------------------


def _clean(doc: Doc) -> list[_Line]:
    """Bỏ chú thích/thẻ HTML ngoài code fence; giữ nguyên số dòng (chú thích nhiều dòng để lại dòng trống)."""
    raw = doc.body.split("\n")
    mask = fence_mask(raw)
    out: list[_Line] = []
    i = 0
    while i < len(raw):
        if mask[i]:
            out.append(_Line(doc.body_start_line + i, raw[i], True))
            i += 1
            continue
        j = i
        while j < len(raw) and not mask[j]:
            j += 1
        segment = "\n".join(raw[i:j])
        segment = _HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), segment)
        segment = _HTML_TAG.sub("", segment)
        for k, text in enumerate(segment.split("\n")):
            out.append(_Line(doc.body_start_line + i + k, text, False))
        i = j
    return out


def _sections(lines: list[_Line]) -> list[_Section]:
    sections: list[_Section] = []
    h2 = path = OVERVIEW
    current: list[_Line] = []
    for line in lines:
        m = None if line.in_fence else (_H2.match(line.text) or _H3.match(line.text))
        if m is None:
            current.append(line)
            continue
        sections.append(_Section(h2, path, current))
        current = []
        if m.re is _H2:
            h2 = path = m.group(1)
        else:
            path = f"{h2}{PATH_SEP}{m.group(1)}"
    sections.append(_Section(h2, path, current))
    return [s for s in sections if any(line.text.strip() for line in s.lines)]


# ---- 3. Khối -------------------------------------------------------------------------------------


def _text(lines: list[_Line]) -> str:
    return "\n".join(line.text for line in lines).strip("\n")


def _raw_blocks(section: _Section) -> list[list[_Line]]:
    blocks: list[list[_Line]] = []
    current: list[_Line] = []
    for line in section.lines:
        if not line.in_fence and not line.text.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _blocks(section: _Section) -> list[Block]:
    """Khối theo dòng trống; các khối liên tiếp bắt đầu bằng mục danh sách gộp thành MỘT khối danh sách."""
    out: list[Block] = []
    raw = _raw_blocks(section)
    i = 0
    while i < len(raw):
        first = raw[i]
        if not first[0].in_fence and _LIST_ITEM.match(first[0].text):
            j = i + 1
            while j < len(raw) and not raw[j][0].in_fence and _LIST_ITEM.match(raw[j][0].text):
                j += 1
            span = [line for line in section.lines if first[0].no <= line.no <= raw[j - 1][-1].no]
            out.append(Block(_text(span), first[0].no, is_list=True))
            i = j
        else:
            out.append(Block(_text(first), first[0].no))
            i += 1
    return out


def _list_items(block: Block) -> list[Block]:
    """Tách khối danh sách thành từng mục (dòng khớp mục danh sách ở mức thụt ngoài cùng + các dòng sau nó)."""
    lines = block.text.split("\n")
    indent = len(lines[0]) - len(lines[0].lstrip())
    starts = [
        k for k, line in enumerate(lines)
        if _LIST_ITEM.match(line) and len(line) - len(line.lstrip()) <= indent
    ]  # fmt: skip
    items: list[Block] = []
    for n, k in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        text = "\n".join(lines[k:end]).strip("\n").rstrip()
        sep = block.sep if n == 0 else ("\n\n" if not lines[k - 1].strip() else "\n")
        items.append(Block(text, block.start_line + k, sep=sep))
    return items


def _sentences(block: Block) -> list[Block]:
    """Tách một khối theo câu (`(?<=[.!?…])\\s+` và xuống dòng). Câu nối lại bằng "\\n" nếu giữa hai câu có xuống
    dòng, không thì bằng " " — như văn bản gốc. Câu đầu giữ `sep` của khối."""
    text = block.text
    out: list[Block] = []
    pos = 0
    sep: str | None = block.sep
    for m in [*_SENTENCE_SEP.finditer(text), None]:
        end = m.start() if m else len(text)
        piece = text[pos:end].strip()
        if piece:
            line = block.start_line + text.count("\n", 0, pos)
            out.append(Block(piece, line, sep=sep or " ", atomic=True))
            sep = None
        if m is None:
            break
        if sep is None or sep == " ":
            sep = "\n" if "\n" in m.group(0) else " "
        pos = m.end()
    return out


# ---- 4. Gom tham lam trong một mục -------------------------------------------------------------


def _join(blocks: list[Block]) -> str:
    return blocks[0].text + "".join(b.sep + b.text for b in blocks[1:])


async def _greedy(section: _Section, counter: TokenCounter, rel_path: str) -> list[_Piece]:
    blocks = _blocks(section)
    pieces: list[_Piece] = []
    s = 0
    while s < len(blocks):
        prefixes = [_join(blocks[s : e + 1]) for e in range(s, len(blocks))]
        counts = await _count(counter, prefixes)
        best = -1
        for k, n in enumerate(counts):
            if n > CHUNK_TOKENS_MAX:
                break
            best = k
        if best >= 0:
            pieces.append(_Piece(section.h2, section.path, prefixes[best], counts[best], blocks[s].start_line))
            s += best + 1
            continue
        block = blocks[s]  # khối đơn vượt trần → tách mục danh sách / câu; câu đơn vượt trần → lỗi
        if block.atomic:
            raise IngestError(f"câu quá dài ({counts[0]} token > {CHUNK_TOKENS_MAX})", rel_path, block.start_line)
        blocks[s : s + 1] = _list_items(block) if block.is_list else _sentences(block)
    return pieces


# ---- 5. Gộp đoạn nhỏ trong cùng H2 -------------------------------------------------------------


def _merged(a: _Piece, b: _Piece, tokens: int) -> _Piece:
    path = a.path if a.path == b.path else a.h2
    return _Piece(a.h2, path, f"{a.content}\n\n{b.content}", tokens, min(a.start_line, b.start_line))


async def _merge_small(pieces: list[_Piece], counter: TokenCounter) -> list[_Piece]:
    out = list(pieces)
    i = 0
    while i < len(out):
        cur = out[i]
        if cur.tokens >= CHUNK_TOKENS_MIN:
            i += 1
            continue
        if i + 1 < len(out) and out[i + 1].h2 == cur.h2:  # 1. vào đoạn kế tiếp cùng H2
            text = f"{cur.content}\n\n{out[i + 1].content}"
            (n,) = await counter.count([text])
            if n <= CHUNK_TOKENS_MAX:
                out[i : i + 2] = [_merged(cur, out[i + 1], n)]
                continue  # xét lại đoạn vừa gộp
        if i > 0 and out[i - 1].h2 == cur.h2:  # 2. vào đoạn trước cùng H2
            text = f"{out[i - 1].content}\n\n{cur.content}"
            (n,) = await counter.count([text])
            if n <= CHUNK_TOKENS_MAX:
                out[i - 1 : i + 1] = [_merged(out[i - 1], cur, n)]
                i -= 1
                continue
        i += 1  # 3. giữ nguyên — đoạn ngắn hợp lệ
    return out


# ---- 6–7. Văn bản đoạn, định danh ----------------------------------------------------------------


async def chunk_doc(doc: Doc, counter: TokenCounter) -> list[Chunk]:
    pieces: list[_Piece] = []
    for section in _sections(_clean(doc)):
        pieces.extend(await _greedy(section, counter, doc.rel_path))
    pieces = await _merge_small(pieces, counter)
    texts = [f"{doc.fm.title}{PATH_SEP}{p.path}\n\n{p.content}" for p in pieces]
    text_counts = await _count(counter, texts)
    chunks: list[Chunk] = []
    for seq, (p, text, n) in enumerate(zip(pieces, texts, text_counts, strict=True)):
        if n > CHUNK_TEXT_MAX:
            raise IngestError(
                f"đoạn {n} token > {CHUNK_TEXT_MAX} (tiền tố/heading quá dài?)", doc.rel_path, p.start_line
            )
        chunk_id = f"{doc.fm.doc_id}#v{doc.fm.version}#{seq}"
        chunks.append(Chunk(seq, chunk_id, p.path, p.h2, p.content, p.tokens, text, n, p.start_line))
    return chunks

