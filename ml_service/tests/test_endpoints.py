"""a5 (rerank), a7 (classify 503), a3f/a4f/a6f (sinh đôi với tokenizer giả), health, header, giới hạn.

Test sinh đôi gọi code thật (`tokens.py`, `embed.py`, `rerank.py`) qua HTTP với tokenizer giả thêm đúng 2
token đặc biệt; con số mong đợi suy từ định nghĩa tokenizer giả (conftest), không tính lại bằng code test.
"""

import pytest
from app.main import create_app
from app.schemas import COUNT_MAX_ITEMS, EMBED_MAX_ITEMS, RERANK_MAX_PASSAGES
from app.settings import MlSettings
from fastapi.testclient import TestClient
from tests.conftest import REV_E, REV_R, FakeLoader


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


# ---- a3f / a4f / a6f ------------------------------------------------------------------------------


def test_a3f_count_includes_special_tokens(client: TestClient, auth: dict[str, str]) -> None:
    r = client.post("/count_tokens", json={"texts": ["xin chào", words(10)]}, headers=auth)
    assert r.status_code == 200
    assert r.json()["counts"] == [4, 12]  # 2 từ + 2 token đặc biệt; 10 + 2


def test_a4f_embed_truncated_over_512(client: TestClient, auth: dict[str, str]) -> None:
    body = {"texts": [words(600), "câu ngắn", words(510)]}
    out = client.post("/embed", json=body, headers=auth).json()
    assert out["token_counts"] == [602, 4, 512]
    assert out["truncated"] == [True, False, False]  # 512 vừa khít: không cắt


def test_a6f_rerank_cuts_query_not_passage(
    client: TestClient, auth: dict[str, str], loader: FakeLoader
) -> None:
    body = {"query": words(300, "q"), "passages": [words(480, "p")]}
    out = client.post("/rerank", json=body, headers=auth).json()
    assert out["query_truncated"] is True
    assert out["truncated"] == [False]  # 128 + 480 + 4 = 612 ≤ 640
    sent_query = loader.reranker.pairs[-1][0]
    assert sent_query == words(128, "q")  # model nhận đúng 128 token đầu


def test_short_query_not_truncated(client: TestClient, auth: dict[str, str]) -> None:
    out = client.post("/rerank", json={"query": words(128, "q"), "passages": ["x"]}, headers=auth).json()
    assert out["query_truncated"] is False


def test_passage_over_window_flagged(client: TestClient, auth: dict[str, str]) -> None:
    out = client.post("/rerank", json={"query": "q", "passages": [words(700)]}, headers=auth).json()
    assert out["truncated"] == [True]  # đoạn quá dài thì cờ lên — không âm thầm


# ---- a5: rerank --------------------------------------------------------------------------------------


def test_a5_rerank_scores_in_order_and_unit_interval(client: TestClient, auth: dict[str, str]) -> None:
    passages = ["mfa điện thoại", "vpn lỗi chứng chỉ", "vpn chứng chỉ hết hạn lỗi"]
    out = client.post("/rerank", json={"query": "vpn lỗi chứng chỉ", "passages": passages},
                      headers=auth).json()  # fmt: skip
    scores = out["scores"]
    assert len(scores) == 3 and all(0.0 <= s <= 1.0 for s in scores)
    assert scores[0] < 0.5 < scores[1]  # logit âm → < 0,5: sigmoid áp đúng một lần
    assert scores[1] == scores[2]  # cùng thứ tự passages (2 đoạn cùng 3 từ chung)
    assert out["model"] == "BAAI/bge-reranker-v2-m3"


# ---- a7: classify ----------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/classify", "/classify_intent"])
def test_a7_classifiers_model_missing(client: TestClient, auth: dict[str, str], path: str) -> None:
    r = client.post(path, json={"text": "đặt lại mật khẩu"}, headers=auth)
    assert r.status_code == 503 and r.json() == {"error": "model_missing"}
    assert client.post(path, json={}, headers=auth).status_code == 422  # body kiểm trước 503


def test_a7_classifier_dir_present_still_missing(
    settings: MlSettings, loader: FakeLoader, auth: dict[str, str]
) -> None:
    settings.models_dir.mkdir(parents=True)
    present = settings.model_copy(update={"intent_model_dir": settings.models_dir})
    with TestClient(create_app(present, loader=loader)) as c:
        assert c.post("/classify_intent", json={"text": "x"}, headers=auth).status_code == 503
        assert c.get("/health").json()["models"]["intent"] == "missing"


def test_a7_health_reports_missing_classifiers(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["models"]["injection"] == "missing" and body["models"]["intent"] == "missing"
    assert body["models"]["embed"] == {"repo": "BAAI/bge-m3", "revision": REV_E, "dim": 4}
    assert body["models"]["rerank"]["revision"] == REV_R


# ---- khởi động, header, giới hạn ----------------------------------------------------------------------


def test_health_503_until_loaded(settings: MlSettings, loader: FakeLoader) -> None:
    c = TestClient(create_app(settings, loader=loader))  # không `with` → lifespan chưa chạy
    r = c.get("/health")
    assert r.status_code == 503 and r.json() == {"status": "loading"}
    assert loader.loads == 0


def test_loads_once_and_warms_up(settings: MlSettings, loader: FakeLoader) -> None:
    with TestClient(create_app(settings, loader=loader)):
        assert loader.loads == 1
        assert len(loader.embedder.calls) == 1 and len(loader.reranker.pairs) == 1  # warm-up


def test_loader_failure_blocks_startup(settings: MlSettings) -> None:
    def broken(_: MlSettings) -> None:
        raise RuntimeError("thiếu model — chạy make models")

    app = create_app(settings, loader=broken)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="make models"), TestClient(app):
        pass


def test_model_version_header_on_success_only(client: TestClient, auth: dict[str, str]) -> None:
    ok = client.post("/embed", json={"texts": ["a"]}, headers=auth)
    assert ok.headers["X-Model-Version"] == f"bge-m3@{REV_E[:7]};reranker@{REV_R[:7]}"
    bad = client.post("/embed", json={"texts": ["a"]})
    assert "X-Model-Version" not in bad.headers


@pytest.mark.parametrize(
    ("path", "key", "limit", "extra"),
    [("/embed", "texts", EMBED_MAX_ITEMS, {}), ("/count_tokens", "texts", COUNT_MAX_ITEMS, {}),
     ("/rerank", "passages", RERANK_MAX_PASSAGES, {"query": "q"})],
)  # fmt: skip
def test_item_limits(
    client: TestClient, auth: dict[str, str], path: str, key: str, limit: int, extra: dict[str, str]
) -> None:
    assert client.post(path, json={key: ["x"] * limit, **extra}, headers=auth).status_code == 200
    assert client.post(path, json={key: ["x"] * (limit + 1), **extra}, headers=auth).status_code == 422
    assert client.post(path, json={key: [], **extra}, headers=auth).status_code == 422
