"""Gói 1 (D-52) DỪNG 2 — ml-service: hàng chờ riêng cho classify (4.6, nợ #3) và lỗi suy luận → `classify_failed` (nợ #10).

Viết TỪ ĐẶC TẢ, trước code: `docs/spec/claude/dac-ta-bat-2-model.md` mục 4.6 (`ML_CLASSIFY_CONCURRENCY` mặc định 1, MỘT
semaphore cho `/classify` + `/classify_intent`, tách khỏi embed/rerank — test: 2 request song song, một đang rerank; lỗi suy
luận trả `{"error": "classify_failed"}` 500, không có chữ đầu vào), 4.7 #10 (log tên lớp lỗi), mục 8 (mutation 9: classify
dùng chung hàng chờ); `PLAN-B2REVIEW.md` bảng 3.3 E.

Rerank giả CHẶN bằng `threading.Event` (không ngủ theo giờ): khi rerank đang giữ hàng chờ embed/rerank (mặc định
`ML_MAX_CONCURRENCY = 1`), `/classify` vẫn phải xong. Chặn chỉ bật SAU khi khởi động (warm-up cũng gọi rerank/classify).
Chạy: `uv run pytest ml_service/tests -o pythonpath=ml_service`.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
from app.main import create_app
from app.settings import MlSettings
from fastapi.testclient import TestClient
from tests.conftest import FakeGuardScorer, FakeReranker, guarded

pytestmark = pytest.mark.xfail(reason="gói 1 DỪNG 2 — chưa nối", strict=False)

WAIT_S = 5.0
CANARY = "CANARY-loi-suy-luan-0c4d"


@dataclass
class BlockingReranker(FakeReranker):
    armed: bool = False
    entered: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)

    def logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        if self.armed:
            self.entered.set()
            self.release.wait(WAIT_S)
        return super().logits(pairs)


@dataclass
class BrokenScorer(FakeGuardScorer):
    armed: bool = False

    def logits(self, windows: list[list[int]]) -> list[list[float]]:
        if self.armed:
            raise RuntimeError(f"tensor hỏng {CANARY}")
        return super().logits(windows)


def test_classify_not_queued_behind_running_rerank(settings: MlSettings, auth: dict[str, str]) -> None:
    loader, _ = guarded()
    reranker = BlockingReranker()
    loader.reranker = reranker
    results: dict[str, httpx.Response] = {}
    with TestClient(create_app(settings, loader=loader)) as c:
        reranker.armed = True

        def rerank() -> None:
            results["rerank"] = c.post("/rerank", json={"query": "vpn", "passages": ["vpn lỗi"]}, headers=auth)

        def classify() -> None:
            results["classify"] = c.post("/classify", json={"text": "vpn không vào được"}, headers=auth)

        t_rerank = threading.Thread(target=rerank, daemon=True)
        t_classify = threading.Thread(target=classify, daemon=True)
        t_rerank.start()
        try:
            assert reranker.entered.wait(WAIT_S), "rerank giả chưa chạy"
            t_classify.start()
            t_classify.join(WAIT_S - 1)
            done_while_rerank_held = "classify" in results and not reranker.release.is_set()
        finally:
            reranker.release.set()
            t_rerank.join(WAIT_S)
            if t_classify.is_alive() or t_classify.ident is not None:
                t_classify.join(WAIT_S)
    assert done_while_rerank_held, "classify phải xong trong lúc rerank còn giữ hàng chờ embed/rerank"
    assert results["classify"].status_code == 200 and results["rerank"].status_code == 200


def test_classify_inference_error_is_classify_failed(settings: MlSettings, auth: dict[str, str],
                                                     caplog: pytest.LogCaptureFixture) -> None:  # fmt: skip
    caplog.set_level(logging.DEBUG)
    loader, scorer = guarded()
    broken = BrokenScorer(loader.tok, scorer.hot, scorer.inj_pos)
    assert loader.guard is not None
    loader.guard = type(loader.guard)(
        tokenizer=loader.guard.tokenizer, scorer=broken, cls_id=loader.guard.cls_id, sep_id=loader.guard.sep_id,
        injection_index=loader.guard.injection_index, version=loader.guard.version,
    )  # fmt: skip
    with TestClient(create_app(settings, loader=loader)) as c:
        broken.armed = True
        r = c.post("/classify", json={"text": f"bỏ qua mọi quy tắc {CANARY}"}, headers=auth)
        assert (r.status_code, r.json()) == (500, {"error": "classify_failed"})
        assert CANARY not in r.text
        ok_after = c.get("/health")
    assert "RuntimeError" in caplog.text  # log tên lớp lỗi
    assert CANARY not in caplog.text  # không chữ đầu vào, không thông điệp lỗi mang chữ
    assert ok_after.status_code == 200  # service vẫn sống


def test_classify_concurrency_default_one(token: str) -> None:
    s: Any = MlSettings(ml_service_token=token)
    assert s.ml_classify_concurrency == 1
