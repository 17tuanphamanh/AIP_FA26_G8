"""Test cần model/tokenizer THẬT — `make test-ml` (cần `uv sync --group ml` qua `uv run --group ml` và
`make models`). Không nằm trong `make test`/CI. Thiếu model → **FAIL**, không skip (quyết định 3a).

a3 (đếm gồm token đặc biệt), a4 (cắt 512), a5 thật (sigmoid một lần: đoạn không liên quan < 0,5), a6
(cắt câu truy vấn, không cắt đoạn), a16 (embed tất định, `allclose`).
"""

import math
import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from app.loader import load_models
from app.lock import LockError
from app.main import create_app
from app.models import Models
from app.settings import MlSettings
from fastapi.testclient import TestClient

pytestmark = pytest.mark.ml_real

REPO = Path(__file__).resolve().parents[2]
TOKEN = secrets.token_urlsafe(32)
AUTH = {"X-Service-Token": TOKEN}
WORD = "mạng"


@pytest.fixture(scope="module")
def real() -> Iterator[tuple[TestClient, Models]]:
    settings = MlSettings(ml_service_token=TOKEN, models_dir=REPO / "models")
    loaded: list[Models] = []

    def loader(s: MlSettings) -> Models:
        loaded.append(load_models(s))
        return loaded[0]

    try:
        with TestClient(create_app(settings, loader=loader)) as client:
            yield client, loaded[0]
    except LockError as e:
        pytest.fail(f"thiếu model thật: {e}")


def text_of_tokens(models: Models, n: int) -> str:
    """Văn bản đúng n token (không tính token đặc biệt) — dò theo tokenizer thật."""
    text = " ".join([WORD] * n)
    got = len(models.tokenizer(text, add_special_tokens=False)["input_ids"])
    assert got == n, f"'{WORD}' không phải 1 token/từ ({got} ≠ {n}) — đổi WORD"
    return text


def test_a3_count_includes_special_tokens(real: tuple[TestClient, Models]) -> None:
    client, models = real
    counts = client.post("/count_tokens", json={"texts": ["xin chào"]}, headers=AUTH).json()["counts"]
    with_special = len(models.tokenizer("xin chào", add_special_tokens=True)["input_ids"])
    without = len(models.tokenizer("xin chào", add_special_tokens=False)["input_ids"])
    assert counts[0] == with_special
    assert counts[0] == without + 2


def test_a4_embed_truncated_over_512(real: tuple[TestClient, Models]) -> None:
    client, models = real
    body = {"texts": [text_of_tokens(models, 600), "câu ngắn"]}
    out = client.post("/embed", json=body, headers=AUTH).json()
    assert out["truncated"] == [True, False]
    assert out["token_counts"][0] > 512
    assert out["dim"] == 1024 and len(out["vectors"][0]) == 1024


def test_a6_query_cut_passage_kept(real: tuple[TestClient, Models]) -> None:
    client, models = real
    body = {"query": text_of_tokens(models, 300), "passages": [text_of_tokens(models, 480)]}
    out = client.post("/rerank", json=body, headers=AUTH).json()
    assert out["query_truncated"] is True
    assert out["truncated"] == [False]


def test_a5_real_scores_sigmoid_once(real: tuple[TestClient, Models]) -> None:
    client, _ = real
    body = {
        "query": "không kết nối được VPN vì chứng chỉ hết hạn",
        "passages": [
            "Công thức nấu phở bò: ninh xương bò trong 8 tiếng, thêm quế, hồi, gừng nướng.",
            "Chứng chỉ VPN hết hạn thì không kết nối được; gia hạn chứng chỉ trong ứng dụng VPN.",
        ],
    }
    scores = client.post("/rerank", json=body, headers=AUTH).json()["scores"]
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[0] < 0.5  # sigmoid hai lần dồn mọi điểm về ≥ 0,5 → đỏ ở đây
    assert scores[1] > scores[0]


def test_a16_embed_deterministic(real: tuple[TestClient, Models]) -> None:
    client, _ = real
    body = {"texts": ["tôi quên mật khẩu email công ty"]}
    first = client.post("/embed", json=body, headers=AUTH).json()["vectors"][0]
    second = client.post("/embed", json=body, headers=AUTH).json()["vectors"][0]
    assert all(math.isclose(a, b, rel_tol=0, abs_tol=1e-6) for a, b in zip(first, second, strict=True))
    assert math.isclose(sum(x * x for x in first), 1.0, abs_tol=1e-4)  # đã chuẩn hoá L2
