"""Fixture cho test ml-service. Chạy riêng với backend vì cả hai đều là package `app`:
`uv run pytest ml_service/tests -o pythonpath=ml_service -m "not ml_real"` (make test).

Loader giả: không torch, không model. Tokenizer giả tách theo khoảng trắng, mỗi từ một token, và thêm
ĐÚNG 2 token đặc biệt cho một văn bản (`<s> … </s>`), 4 cho một cặp (`<s> a </s></s> b </s>`) — như
XLM-RoBERTa của bge-m3. Test sinh đôi (a3f, a4f, a6f) gọi code thật `tokens.py`, `rerank.py` qua HTTP.

Test `ml_real` (model thật, `make test-ml`) nằm ở `test_real_models.py`.
"""

import secrets
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from app.lock import ModelRef
from app.main import create_app
from app.models import Models
from app.settings import MlSettings
from fastapi.testclient import TestClient

CLS, SEP = 0, 2
REV_E = "a" * 40
REV_R = "b" * 40


class FakeTokenizer:
    def __init__(self) -> None:
        self._ids: dict[str, int] = {}
        self._words: dict[int, str] = {}

    def _encode(self, text: str) -> list[int]:
        out = []
        for word in text.split():
            if word not in self._ids:
                self._ids[word] = len(self._ids) + 10  # 0..9 dành cho token đặc biệt
                self._words[self._ids[word]] = word
            out.append(self._ids[word])
        return out

    def __call__(
        self, text: str, text_pair: str | None = None, *, add_special_tokens: bool = True
    ) -> Mapping[str, Any]:
        ids = self._encode(text)
        if text_pair is not None:
            pair = self._encode(text_pair)
            ids = [CLS, *ids, SEP, SEP, *pair, SEP] if add_special_tokens else ids + pair
        elif add_special_tokens:
            ids = [CLS, *ids, SEP]
        return {"input_ids": ids}

    def decode(self, token_ids: Sequence[int]) -> str:
        return " ".join(self._words[i] for i in token_ids if i in self._words)


@dataclass
class FakeEmbedder:
    calls: list[list[str]] = field(default_factory=list)

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[1.0, 0.0, 0.0, 0.0] for _ in texts]


@dataclass
class FakeReranker:
    """Logit = (số từ chung với câu truy vấn − 1) × 3: đoạn không liên quan có logit âm."""

    pairs: list[tuple[str, str]] = field(default_factory=list)

    def logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.pairs.extend(pairs)
        return [(len(set(q.split()) & set(p.split())) - 1) * 3.0 for q, p in pairs]


@dataclass
class FakeLoader:
    embedder: FakeEmbedder = field(default_factory=FakeEmbedder)
    reranker: FakeReranker = field(default_factory=FakeReranker)
    loads: int = 0

    def __call__(self, settings: MlSettings) -> Models:
        self.loads += 1
        tok = FakeTokenizer()
        return Models(
            tokenizer=tok, rerank_tokenizer=tok, embedder=self.embedder, reranker=self.reranker,
            embed=ModelRef("BAAI/bge-m3", REV_E), rerank=ModelRef("BAAI/bge-reranker-v2-m3", REV_R),
            dim=4,
        )  # fmt: skip


@pytest.fixture(scope="session")
def token() -> str:
    return secrets.token_urlsafe(32)


@pytest.fixture
def settings(token: str, tmp_path: Path) -> MlSettings:
    return MlSettings(ml_service_token=token, models_dir=tmp_path / "models")


@pytest.fixture
def loader() -> FakeLoader:
    return FakeLoader()


@pytest.fixture
def client(settings: MlSettings, loader: FakeLoader) -> Iterator[TestClient]:
    with TestClient(create_app(settings, loader=loader)) as c:
        yield c


@pytest.fixture
def auth(token: str) -> dict[str, str]:
    return {"X-Service-Token": token}
