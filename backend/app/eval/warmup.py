"""Làm nóng rerank trước lượt đo (G2, plan mục 5) — chạy TRONG container backend:

    docker compose exec -T backend python -m app.eval.warmup --rounds 3

ml-service lúc lên chỉ warm 1 cặp (ml_service/app/main.py:59-62), còn lô thật có `rag_rerank_k` đoạn → vài request đầu chậm, làm lệch
hạn lượt của kịch bản đầu. Mỗi vòng: `POST /embed {texts: [1 câu]}` + `POST /rerank {query, passages: min(rag_rerank_k, 32)}`
(`RERANK_MAX_PASSAGES`, ml_service/app/schemas.py:10), header `X-Service-Token`. Chữ TỔNG HỢP cố định — không lấy từ kịch bản; không
tạo ticket, không ghi DB → không vào số đo. In ĐÚNG một dòng JSON `{rounds, first_ms, last_ms}`; lỗi → một dòng lý do cố định, mã 2
(không chép thân trả về).

TODO(G2-Q9): chỉ đi ml-service, không đi cả retriever (Qdrant/BM25).
"""

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from app.eval.stack import Clock

PASSAGE_MAX = 32  # = RERANK_MAX_PASSAGES (ml_service/app/schemas.py:10)
WARM_QUERY = "Không kết nối được VPN công ty từ máy làm việc ở nhà"
_TOPICS = ("kết nối VPN", "đặt lại mật khẩu", "mở khoá tài khoản", "cài phần mềm", "cấp quyền thư mục chia sẻ",
           "gia hạn chứng chỉ VPN", "đổi máy làm việc", "lỗi đăng nhập hai lớp")  # fmt: skip
TIMEOUT_S = 60.0

type Post = Callable[[str, dict[str, Any]], None]


class _Settings(Protocol):
    ml_service_url: str
    ml_service_token: SecretStr | None
    rag_rerank_k: int


def passages(n: int) -> list[str]:
    return [f"Đoạn hướng dẫn mẫu số {i + 1}: các bước {_TOPICS[i % len(_TOPICS)]} theo quy trình bộ phận IT, "
            "kiểm tra thiết bị, ghi lại mã lỗi và liên hệ L1 nếu không làm được." for i in range(n)]  # fmt: skip


def warm(post: Post, k: int, rounds: int, clock: Clock) -> dict[str, int]:
    if rounds < 1:
        raise ValueError("rounds phải ≥ 1")
    batch = passages(max(1, min(k, PASSAGE_MAX)))
    ms: list[int] = []
    for _ in range(rounds):
        start = clock.monotonic()
        post("/embed", {"texts": [WARM_QUERY]})
        post("/rerank", {"query": WARM_QUERY, "passages": batch})
        ms.append(max(1, round((clock.monotonic() - start) * 1000)))
    return {"rounds": rounds, "first_ms": ms[0], "last_ms": ms[-1]}


def make_client(url: str, token: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(base_url=url, headers={"X-Service-Token": token}, timeout=TIMEOUT_S, transport=transport)


def _default_settings() -> _Settings:
    from app.settings import get_settings

    return get_settings()


def main(argv: Sequence[str], *, settings_factory: Callable[[], _Settings] = _default_settings,
         transport: httpx.BaseTransport | None = None, out: Callable[[str], None] = print) -> int:  # fmt: skip
    parser = argparse.ArgumentParser(prog="python -m app.eval.warmup")
    parser.add_argument("--rounds", type=int, default=3)
    args = parser.parse_args(list(argv))
    if args.rounds < 1:
        out("warmup lỗi: --rounds phải ≥ 1")
        return 2
    s = settings_factory()
    if s.ml_service_token is None:
        out("warmup lỗi: container không có ML_SERVICE_TOKEN")
        return 2
    with make_client(s.ml_service_url, s.ml_service_token.get_secret_value(), transport) as http:

        def post(path: str, body: dict[str, Any]) -> None:
            r = http.post(path, json=body)
            if r.status_code != 200:
                raise httpx.HTTPStatusError(f"{path}: HTTP {r.status_code}", request=r.request, response=r)

        try:
            result = warm(post, s.rag_rerank_k, args.rounds, Clock())
        except httpx.HTTPStatusError as e:
            out(f"warmup lỗi: HTTP {e.response.status_code}")
            return 2
        except httpx.HTTPError as e:
            out(f"warmup lỗi: {type(e).__name__}")
            return 2
    out(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
