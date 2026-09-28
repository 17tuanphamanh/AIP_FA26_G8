"""L0 của guard (B02 mục 2; PLAN-3e Q-3e-5): một dạng chuẩn cho CẢ L1 (privacy) lẫn L2 (mẫu injection).

`l0(text)` = `core.textnorm.normalize` → NFKC → xoá mọi ký tự Unicode loại `Cf` → `normalize` lần nữa (gộp lại khoảng
trắng mà NFKC/xoá `Cf` vừa để lại, vd "bỏ ­ qua"). NFKC đưa chữ/số full-width về ASCII ("ｍật khẩu" → "mật khẩu",
"０９１２" → "0912"); `Cf` gồm zero-width (U+200B–U+200F, U+FEFF), soft hyphen U+00AD, word joiner U+2060, điều khiển
hướng chữ U+202A–U+202E… Văn bản LƯU (ticket, tin nhắn) là bản đã qua `l0` rồi mới che (D-07).

`core.normalize` KHÔNG đổi: nó là dạng chuẩn của ingest (đổi nó = đổi `content_sha256`/`kb_version`).

`match_forms(text)` (L2): bản chữ thường có dấu + bản `unidecode` (không dấu; lo luôn chữ Kirin giống Latin), mỗi bản
ở hai dạng — giữ xuống dòng (cho mẫu neo `(^|\\n)`) và gộp xuống dòng thành một dấu cách ("bỏ\\nqua mọi quy tắc").
"""

import re
import unicodedata

from unidecode import unidecode

from app.core.textnorm import normalize

_NEWLINES = re.compile(r"\s*\n\s*")


def _strip_format_chars(text: str) -> str:
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def l0(text: str) -> str:
    return normalize(_strip_format_chars(unicodedata.normalize("NFKC", normalize(text))))


def match_forms(text: str) -> tuple[str, ...]:
    """Các bản để so mẫu L2 (đã qua `l0`, chữ thường), không trùng lặp, bản có dấu giữ dòng đứng đầu."""
    accented = l0(text).lower()
    folded = unidecode(accented).lower()
    forms = (accented, folded, _NEWLINES.sub(" ", accented), _NEWLINES.sub(" ", folded))
    return tuple(dict.fromkeys(forms))
