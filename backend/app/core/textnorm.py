"""Chuẩn hoá văn bản tiếng Việt dùng chung (thiết kế Phase 3 mục 5.2; PLAN-3b mục 4.1).

`normalize` — một dạng chuẩn duy nhất cho thân bài KB (ingest), câu truy vấn (rag) và guard: NFC, xoá ký tự vô
hình, NBSP → space, gộp khoảng trắng TRONG dòng. Giữ nguyên xuống dòng và phần thụt đầu dòng (danh sách lồng,
code block cần chúng). `fold_diacritics` — bản không dấu (so khớp mẫu ở guard, 3e).

Chỉ stdlib: core không import module nghiệp vụ (hợp đồng import-linter 4).
"""

import re
import unicodedata

_INVISIBLE = re.compile("[\u200b-\u200f\ufeff]")
_INLINE_SPACE = re.compile(r"[ \t]+")


def normalize(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = unicodedata.normalize("NFC", t)
    t = _INVISIBLE.sub("", t).replace("\u00a0", " ")
    lines = []
    for line in t.split("\n"):
        body = line.lstrip(" \t")
        rest = _INLINE_SPACE.sub(" ", body).rstrip(" \t")
        lines.append(line[: len(line) - len(body)] + rest if rest else "")
    return "\n".join(lines)


def fold_diacritics(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return unicodedata.normalize("NFC", stripped.replace("đ", "d").replace("Đ", "D"))
