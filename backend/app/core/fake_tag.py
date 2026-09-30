"""Thẻ `[fake:<preset>]` trong câu người dùng — chỉ dev/test: gate2 chọn kịch bản node giả (`graph.fakes.StackScenario`), gate3
chọn preset ScriptedLLM (`llm.providers.scripted`). MỘT nguồn cho mọi nơi đọc hoặc bỏ thẻ; nằm ở `core` để tầng dưới (`rag`)
dùng được mà không import `llm`/`graph` (import-linter hợp đồng 7).

`strip_fake_tag` (Q-3h-11 a, 3h DỪNG 3b): thẻ nằm trong `redacted_request`, và câu truy hồi dựng từ đó — không bỏ thì reranker
thật chấm câu có thẻ (vd "vpn không vào được" 0,677 → 0,073 khi có thẻ). Câu không có thẻ giữ NGUYÊN.
"""

import re

FAKE_TAG = re.compile(r"\[fake:([a-z0-9_]+)\]")
_TAG_WITH_SPACE = re.compile(r"[ \t]*" + FAKE_TAG.pattern)  # cùng mẫu; nuốt khoảng trắng ngay trước thẻ


def strip_fake_tag(text: str) -> str:
    """Bỏ mọi thẻ `[fake:…]` (kèm khoảng trắng ngay trước) — đầu, giữa hay cuối câu. Không có thẻ → trả nguyên `text`."""
    return _TAG_WITH_SPACE.sub("", text) if FAKE_TAG.search(text) else text
