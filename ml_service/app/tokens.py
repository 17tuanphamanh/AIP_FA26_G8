"""Đếm token bằng tokenizer bge-m3 (D-21, 3-Q20) — dùng chung cho /count_tokens, /embed, /rerank.

Số đếm GỒM token đặc biệt (`<s>`, `</s>`): đó là thứ chiếm chỗ trong cửa sổ 512 của model. Chunker
của P3 (3b) dùng đúng con số này để không đoạn nào bị cắt.
"""

from app.models import Tokenizer

EMBED_MAX_TOKENS = 512  # bge-m3 dense (P4 mục 3); dài hơn → model cắt, ta báo `truncated`


def count(tokenizer: Tokenizer, text: str) -> int:
    return len(tokenizer(text, add_special_tokens=True)["input_ids"])


def count_pair(tokenizer: Tokenizer, first: str, second: str) -> int:
    return len(tokenizer(first, second, add_special_tokens=True)["input_ids"])
