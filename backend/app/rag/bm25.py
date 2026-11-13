"""BM25 tiếng Việt — DÙNG CHUNG ingest và truy vấn (thiết kế Phase 3 mục 5.6; PLAN-3b mục 4.5).

`tokenize_vi`: normalize + chữ thường → gộp kiểu dấu thanh oa/oe/uy (R3, `fold_tone_marks`) → giữ mã (mã lỗi, mã máy, số ≥ 3 chữ số) bằng placeholder TRƯỚC (Q-3b-9) →
mở viết tắt theo NGUYÊN TỪ (`config/vi_abbrev.yaml`) → tách từ bằng pyvi ("mật khẩu" → "mật_khẩu") → khôi phục mã
(kể cả khi pyvi nối placeholder bằng "_") → bỏ dấu câu và stopword (`config/vi_stopwords.txt`, không có "không").
`to_sparse`: băm token bằng mmh3 (không dấu, mod 2^31); va chạm băm được CỘNG DỒN — Qdrant đòi chỉ số duy nhất.
Collection dùng `Modifier.IDF`: Qdrant tự nhân IDF, ta chỉ gửi tần suất.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import mmh3
import yaml
from qdrant_client.models import SparseVector

from app.core import textnorm
from app.settings import get_settings

CODE_RE = re.compile(r"(?i)\b(0x[0-9a-f]+|\d{3,}|[a-z]{2,4}-\d{3,5})\b")
PUNCT = ".,;:!?()[]{}\"'“”‘’…–—-/\\*`<>|=+#~^%&@$"
HASH_NAME = "mmh3-u32-mod2^31"  # vào pipeline_sha — đổi cách băm là đổi collection
# R3 (soát 12/11, agent 16 F5): phiên bản LOGIC tách từ — vào pipeline_sha; đổi `tokenize_vi`/`fold_tone_marks` thì tăng số này.
# 1 = gộp kiểu dấu thanh cũ/mới ở âm tiết mở (13/11).
TOKENIZER_VERSION = 1

_TONE_BASE = {"o": "òóỏõọ", "u": "ùúủũụ"}
_TONE_SECOND = {"a": "àáảãạ", "e": "èéẻẽẹ", "y": "ỳýỷỹỵ"}
_PAIRS = {"o": "ae", "u": "y"}  # oa, oe, uy
_NEW_TONE = re.compile(r"(?<!q)([ou])([àáảãạèéẻẽẹỳýỷỹỵ])(?!\w)")


def fold_tone_marks(text: str) -> str:
    """"hoà"→"hòa", "khoá"→"khóa", "khoẻ"→"khỏe", "thuỷ"→"thủy": cụm oa/oe/uy ở CUỐI âm tiết (không phụ âm cuối) đặt dấu trên nguyên
    âm đầu (kiểu cũ, kiểu KB dùng nhiều nhất). Âm tiết có phụ âm cuối ("hoàn", "khoản") và "qu" ("quý") giữ nguyên. Chữ thường, NFC."""

    def _swap(m: re.Match[str]) -> str:
        first, marked = m.group(1), m.group(2)
        for base, row in _TONE_SECOND.items():
            if marked in row and base in _PAIRS[first]:
                return _TONE_BASE[first][row.index(marked)] + base
        return m.group(0)

    return _NEW_TONE.sub(_swap, text)


@dataclass(frozen=True)
class ViLexicon:
    abbrev: Mapping[str, str]
    abbrev_re: re.Pattern[str]
    stopwords: frozenset[str]


@lru_cache
def load_lexicon(config_dir: Path) -> ViLexicon:
    raw = yaml.safe_load((config_dir / "vi_abbrev.yaml").read_text(encoding="utf-8")) or {}
    abbrev = {str(k).lower(): str(v).lower() for k, v in raw.items()}
    keys = sorted(abbrev, key=len, reverse=True)  # khoá dài trước: "ktra" không bị "k" ăn mất
    abbrev_re = re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)")
    lines = (config_dir / "vi_stopwords.txt").read_text(encoding="utf-8").splitlines()
    stopwords = frozenset(w.strip().lower() for w in lines if w.strip() and not w.lstrip().startswith("#"))
    return ViLexicon(abbrev, abbrev_re, stopwords)


@cache
def _vi() -> Any:
    from pyvi import ViTokenizer  # nạp muộn: nạp model tách từ ~0,8 s lần đầu

    return ViTokenizer


def tokenize_vi(text: str, *, lexicon: ViLexicon | None = None) -> list[str]:
    lx = lexicon or load_lexicon(get_settings().config_dir)
    t = fold_tone_marks(textnorm.normalize(text).lower())  # R3: "khoá" và "khóa" là một token
    codes: dict[str, str] = {}

    def _hold(m: re.Match[str]) -> str:
        key = f"zzcode{len(codes)}zz"  # chỉ a–z + số: pyvi không tách
        codes[key] = m.group(0).lower()
        return f" {key} "

    t = CODE_RE.sub(_hold, t)  # Q-3b-9: giữ mã TRƯỚC khi mở viết tắt
    t = lx.abbrev_re.sub(lambda m: lx.abbrev[m.group(0)], t)
    out: list[str] = []
    for word in _vi().tokenize(t).split():
        parts = word.split("_") if "zzcode" in word else [word]  # pyvi có thể nối placeholder với từ bên cạnh
        for part in parts:
            piece = codes.get(part, part).strip(PUNCT)
            if piece and piece not in lx.stopwords and not piece.isspace():
                out.append(piece)
    return out


def _token_hash(tok: str) -> int:
    return mmh3.hash(tok, signed=False) % 2**31


def to_sparse(tokens: Iterable[str]) -> SparseVector:
    c = Counter(_token_hash(t) for t in tokens)  # gộp va chạm băm
    idx = sorted(c)
    return SparseVector(indices=idx, values=[float(c[i]) for i in idx])
