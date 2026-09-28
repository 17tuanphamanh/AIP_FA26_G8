"""Trần thời gian của `retrieve`/`expand_for_answer` (Q-3c-4, c32): `rag_deadline_s` bọc toàn bộ lượt truy hồi
bằng `asyncio.timeout` — phải nhỏ hơn nửa `worker_stale_turn_seconds`, cùng biên với `test_ml_timeouts.py`, để
lượt treo hết deadline vẫn xong trước khi worker coi lượt là dở dang. Riêng biên Qdrant (3 lời gọi: alias,
metadata, search — mỗi lời gọi timeout `rag_qdrant_timeout_s`, cộng dư 3 giây cho phần xử lý) cũng phải nằm
dưới cùng ngưỡng đó. `rag_rerank_k` không được vượt một lô rerank (`ml.client.RERANK_MAX_PASSAGES`)."""

import pytest
from app.ml.client import RERANK_MAX_PASSAGES
from app.settings import Settings
from pydantic import ValidationError


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg, arg-type]


def test_default_rag_deadline_below_half_stale_turn() -> None:
    s = _settings()
    assert s.rag_deadline_s < s.worker_stale_turn_seconds / 2


def test_default_qdrant_retry_margin_below_half_stale_turn() -> None:
    s = _settings()
    assert 3 * s.rag_qdrant_timeout_s + 3 < s.worker_stale_turn_seconds / 2


def test_default_rag_rerank_k_within_one_rerank_batch() -> None:
    s = _settings()
    assert s.rag_rerank_k <= min(s.rag_prefetch_k, RERANK_MAX_PASSAGES)


@pytest.mark.parametrize(
    "field,value",
    [
        ("rag_rerank_k", 0),  # < 1
        ("rag_rerank_k", 33),  # > RERANK_MAX_PASSAGES (32) và > rag_prefetch_k mặc định (20)
        ("rag_top_n", 21),  # > rag_rerank_k mặc định (10, Q-3a-16/S9)
    ],
)
def test_rag_rerank_bounds_validator_rejects_bad_config(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        _settings(**{field: value})


def test_rag_rerank_k_above_prefetch_k_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(rag_prefetch_k=5, rag_rerank_k=10)


def test_rag_deadline_validator_rejects_too_large() -> None:
    with pytest.raises(ValidationError):
        _settings(rag_deadline_s=1000.0, worker_stale_turn_seconds=120.0)
