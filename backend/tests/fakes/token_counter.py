"""`WordCounter` — bộ đếm token giả cho test chunker không cần tokenizer thật: số từ (tách theo khoảng trắng) + 2
(như 2 token đặc biệt của bge-m3). Tất định, dễ tính tay khi dựng ca biên của b5/b6/b7."""


class WordCounter:
    def __init__(self) -> None:
        self.calls = 0  # số lời gọi `count` (mỗi lời gọi ≤ COUNT_BATCH văn bản)

    async def count(self, texts: list[str]) -> list[int]:
        self.calls += 1
        return [len(t.split()) + 2 for t in texts]
