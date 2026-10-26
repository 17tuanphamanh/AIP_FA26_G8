"""Fixture cho test ml-service. Chạy riêng với backend vì cả hai đều là package `app`:
`uv run pytest ml_service/tests -o pythonpath=ml_service -m "not ml_real"` (make test).

Loader giả: không torch, không model. Tokenizer giả tách theo khoảng trắng, mỗi từ một token, và thêm
ĐÚNG 2 token đặc biệt cho một văn bản (`<s> … </s>`), 4 cho một cặp (`<s> a </s></s> b </s>`) — như
XLM-RoBERTa của bge-m3. Test sinh đôi (a3f, a4f, a6f) gọi code thật `tokens.py`, `rerank.py` qua HTTP.

Test `ml_real` (model thật, `make test-ml`) nằm ở `test_real_models.py`.

Model chặn tấn công giả (ML-GAN): `FakeGuardScorer` trả logit sao cho softmax ở vị trí INJECTION = điểm của từ "nóng"
cao nhất trong cửa sổ (`hot`, mặc định `BASE`) — test biết cửa sổ nào chứa câu đáng ngờ mà không cần torch.

Model intent giả (gói 2, D-53): `FakeIntentScorer` trả `IntentRaw` dựng sẵn (`raw`) hoặc ném `error` — phần trộn điểm, lọc token,
cờ cắt chạy code thật `intent.py`. Test cần torch (`B3Model` nhỏ, safetensors) ở `test_intent_model.py` (marker `ml_torch`).
"""

import math
import secrets
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from app.lock import ModelRef
from app.main import create_app
from app.models import Guard, Intent, IntentRaw, Models
from app.settings import MlSettings
from fastapi.testclient import TestClient

CLS, SEP = 0, 2
REV_E = "a" * 40
REV_R = "b" * 40
BASE = 0.01  # điểm INJECTION của cửa sổ không chứa từ "nóng"


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
class FakeGuardScorer:
    """Model 2 lớp giả: lớp INJECTION ở vị trí `inj_pos` của hàng logit (như `id2label` của config.json)."""

    tok: FakeTokenizer
    hot: dict[str, float] = field(default_factory=dict)
    inj_pos: int = 1
    batches: list[list[list[int]]] = field(default_factory=list)

    def logits(self, windows: list[list[int]]) -> list[list[float]]:
        self.batches.append([list(w) for w in windows])
        rows = []
        for w in windows:
            p = max((self.hot.get(self.tok.decode([i]), BASE) for i in w if i not in (CLS, SEP)), default=BASE)
            row = [math.log(1 - p), math.log(p)]  # softmax([log(1-p), log(p)]) = [1-p, p]
            rows.append(row if self.inj_pos == 1 else row[::-1])
        return rows

    @property
    def windows(self) -> list[list[int]]:
        return [w for batch in self.batches for w in batch]


INTENT_LABELS = ("account", "vpn", "software", "access", "out_of_scope")
INTENT_TAGS = (
    "O", *(f"{p}-REQ:{label}" for label in INTENT_LABELS for p in "BI"),
    *(f"{p}-MEN:{label}" for label in INTENT_LABELS for p in "BI"), "B-CTX", "I-CTX",
)  # fmt: skip


def raw_for(text: str, seq_logits: Sequence[float], hot: Mapping[tuple[int, str], float] | None = None,
            full_len: int | None = None) -> IntentRaw:  # fmt: skip
    """`IntentRaw` cho câu tách theo khoảng trắng + `<s>`/`</s>` (offset (0, 0)); `hot[(token, tag)]` = xác suất tag đó."""
    offsets, pos = [(0, 0)], 0
    for word in text.split():
        start = text.index(word, pos)
        offsets.append((start, start + len(word)))
        pos = start + len(word)
    offsets.append((0, 0))
    rows = [[0.0] * len(INTENT_TAGS) for _ in offsets]
    for (t, tag), p in (hot or {}).items():
        rows[t][INTENT_TAGS.index(tag)] = p
    return IntentRaw(seq_logits=list(seq_logits), tok_probs=rows, offsets=offsets,
                     full_len=len(offsets) if full_len is None else full_len)  # fmt: skip


@dataclass
class FakeIntentScorer:
    raw: IntentRaw | None = None  # None → câu nào cũng logit 0, không tag nào
    error: Exception | None = None
    texts: list[str] = field(default_factory=list)

    def score(self, text: str) -> IntentRaw:
        self.texts.append(text)
        if self.error is not None:
            raise self.error
        return self.raw if self.raw is not None else raw_for(text, [0.0] * len(INTENT_LABELS))


def fake_intent(scorer: FakeIntentScorer | None = None, *, max_len: int = 160,
                tau: Mapping[str, tuple[float, float]] | None = None) -> Intent:  # fmt: skip
    """Model intent đã nạp (như INTENT_MODEL_DIR=…/intent-clf/v3.1-seed42-st), trọng số trộn của gói 0,4 / 0,6."""
    taus = tau or {label: (0.75, 0.75) for label in INTENT_LABELS}
    return Intent(
        scorer=scorer or FakeIntentScorer(), labels=INTENT_LABELS,
        b_req=tuple(INTENT_TAGS.index(f"B-REQ:{label}") for label in INTENT_LABELS),
        i_req=tuple(INTENT_TAGS.index(f"I-REQ:{label}") for label in INTENT_LABELS),
        mix=(0.4, 0.6), max_len=max_len, tau_lo={k: lo for k, (lo, _) in taus.items()},
        tau_hi={k: hi for k, (_, hi) in taus.items()}, version="v3.1-seed42-st",
    )  # fmt: skip


@dataclass
class FakeLoader:
    embedder: FakeEmbedder = field(default_factory=FakeEmbedder)
    reranker: FakeReranker = field(default_factory=FakeReranker)
    tok: FakeTokenizer = field(default_factory=FakeTokenizer)
    guard: Guard | None = None  # None = GUARD_MODEL_DIR không đặt
    intent: Intent | None = None  # None = INTENT_MODEL_DIR không đặt
    loads: int = 0

    def __call__(self, settings: MlSettings) -> Models:
        self.loads += 1
        return Models(
            tokenizer=self.tok, rerank_tokenizer=self.tok, embedder=self.embedder, reranker=self.reranker,
            embed=ModelRef("BAAI/bge-m3", REV_E), rerank=ModelRef("BAAI/bge-reranker-v2-m3", REV_R),
            dim=4, guard=self.guard, intent=self.intent,
        )  # fmt: skip


def guarded(
    hot: dict[str, float] | None = None, inj_pos: int = 1, index: int | None = None
) -> tuple[FakeLoader, FakeGuardScorer]:
    """Loader giả CÓ model chặn tấn công (như GUARD_MODEL_DIR=…/injection-clf/v3-seed123 đã nạp). `index` = chỉ số lớp
    INJECTION mà service dùng (mặc định khớp `inj_pos` của model giả)."""
    loader = FakeLoader()
    scorer = FakeGuardScorer(loader.tok, hot or {}, inj_pos)
    loader.guard = Guard(
        tokenizer=loader.tok, scorer=scorer, cls_id=CLS, sep_id=SEP,
        injection_index=inj_pos if index is None else index, version="v3-seed123",
    )  # fmt: skip
    return loader, scorer


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
