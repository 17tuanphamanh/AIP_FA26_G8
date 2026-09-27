"""b29 — `MlTokenCounter` qua `FakeMlService` (MlClient thật); `LocalTokenizerCounter` với tokenizer bge-m3 thật."""

import pytest
from app.rag.ingest.config import COUNT_BATCH
from app.rag.models import IngestMlError
from app.rag.token_counter import LocalTokenizerCounter, MlTokenCounter
from tests.fakes.fake_ml import FakeMlService, count_tokens
from tests.fakes.tokenizer import bge_m3_tokenizer_path, require_bge_tokenizer


@pytest.mark.asyncio
async def test_b29_ml_error_raises_ingest_ml_error() -> None:
    fake = FakeMlService().fail_next("count_tokens", "http_500", 3)
    with pytest.raises(IngestMlError, match="count_tokens lỗi: http_5xx sau 3 lần"):
        await MlTokenCounter(fake.client()).count(["mật khẩu vpn"])


@pytest.mark.asyncio
async def test_b29_batches_of_256() -> None:
    fake = FakeMlService()
    texts = [f"đoạn số {i}" for i in range(300)]
    counts = await MlTokenCounter(fake.client()).count(texts)
    assert COUNT_BATCH == 256
    assert fake.calls["count_tokens"] == 2
    assert counts == [count_tokens(t) for t in texts]


@pytest.mark.asyncio
async def test_empty_input_no_call() -> None:
    fake = FakeMlService()
    assert await MlTokenCounter(fake.client()).count([]) == []
    assert fake.calls["count_tokens"] == 0


@pytest.mark.tokenizer_real
@pytest.mark.asyncio
async def test_local_tokenizer_counts_special_tokens() -> None:
    counter = LocalTokenizerCounter(require_bge_tokenizer())
    empty, one = await counter.count(["", "vpn"])
    assert empty == 2  # <s> </s>
    assert one >= 3


def test_tokenizer_path_found_on_dev_machine_or_none() -> None:
    path = bge_m3_tokenizer_path()
    assert path is None or path.name == "tokenizer.json"
