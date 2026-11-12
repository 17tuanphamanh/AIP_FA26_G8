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


# E1 soát 12/11 (agent 15 L3, D-92): đồng hình theo HÌNH (unidecode chuyển theo CÁCH ĐỌC: Kirin "р" → "r", "у" → "u", "х" → "kh") — áp
# TRƯỚC unidecode trong bản "khung xương"; leetspeak là bản riêng (không đè bản gốc: mã máy/số liệu không bị đổi ở các bản kia).
_SHAPE = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "һ": "h", "ԁ": "d", "ԛ": "q",
    "ԝ": "w", "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "ё": "e", "ї": "i",
    "α": "a", "ο": "o", "ε": "e", "ι": "i", "κ": "k", "ν": "v", "ρ": "p", "τ": "t", "υ": "u", "χ": "x", "η": "n", "μ": "u", "β": "b",
    "ω": "w", "γ": "y", "ς": "s", "σ": "o",
})  # fmt: skip
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_NON_WORD = re.compile(r"[\W_]+")  # dấu câu, markdown, emoji, U+2800, "_", "." chen giữa từ → một dấu cách


def match_forms(text: str) -> tuple[str, ...]:
    """Các bản để so mẫu L2 (đã qua `l0`, chữ thường), không trùng lặp, bản có dấu giữ dòng đứng đầu. E1 (D-92) thêm: bản "khung xương"
    (đồng hình theo hình → unidecode), bản bỏ ký tự không phải chữ/số (gộp thành một dấu cách) và bản leetspeak của khung xương."""
    accented = l0(text).lower()
    folded = unidecode(accented).lower()
    shaped = accented.translate(_SHAPE)
    skeleton = unidecode(shaped).lower()
    # bỏ ký tự không phải chữ/số TRƯỚC unidecode (unidecode xoá emoji → hai từ dính liền)
    words = " ".join(unidecode(_NON_WORD.sub(" ", shaped)).lower().split())
    leet = " ".join(_NON_WORD.sub(" ", unidecode(shaped.translate(_LEET)).lower()).split())
    # ký hiệu (emoji, U+2800 "chữ nổi trống", …) chen GIỮA từ: xoá hẳn (không thay bằng dấu cách)
    joined = " ".join(unidecode("".join(ch for ch in shaped if not unicodedata.category(ch).startswith("S"))).lower().split())
    forms = (accented, folded, _NEWLINES.sub(" ", accented), _NEWLINES.sub(" ", folded), skeleton, _NEWLINES.sub(" ", skeleton),
             words, leet, joined)  # fmt: skip
    return tuple(dict.fromkeys(forms))
