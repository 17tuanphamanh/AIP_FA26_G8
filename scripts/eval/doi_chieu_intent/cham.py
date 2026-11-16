"""Đối chiếu model intent với LLM — bước 2: chấm 100 câu bằng `/classify_intent` của ml-service trên máy demo.

Chỉ gọi model của nhóm (tất định), không gọi LLM, không ghi DB, không đổi cấu hình. Chạy TRONG container backend để dùng
sẵn `ML_SERVICE_URL`, `ML_SERVICE_TOKEN` của container (script không in token). Cần ml-service đã nạp `intent-clf`
(`INTENT_MODEL_DIR` đặt; thiếu model → 503 và script dừng):

  docker compose cp eval/doi-chieu-intent/dau-vao.jsonl backend:/tmp/dau-vao.jsonl
  docker compose cp scripts/eval/doi_chieu_intent/cham.py backend:/tmp/cham.py
  docker compose exec -T backend python /tmp/cham.py /tmp/dau-vao.jsonl > eval/doi-chieu-intent/model-ra.jsonl

Chỉ dùng thư viện chuẩn. Lỗi bất kỳ (HTTP khác 200, sha câu lệch) → dừng, không ghi kết quả dở.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

Post = Callable[[str, dict[str, Any] | None], dict[str, Any]]


def http_call(base: str, token: str, timeout: float = 30.0) -> Post:
    def call(path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            base.rstrip("/") + path, data=data, method="GET" if body is None else "POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("X-Service-Token", token)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                out: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
                return out
        except urllib.error.HTTPError as e:
            raise SystemExit(
                f"{path}: HTTP {e.code} — dừng (503 = ml-service chưa nạp intent-clf)"
            ) from None

    return call


def score(lines: Sequence[str], post: Post) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in lines if line.strip()]
    if not rows or rows[0].get("kind") != "header":
        raise SystemExit("dau-vao.jsonl: thiếu dòng header")
    head, items = rows[0], rows[1:]
    out: list[dict[str, Any]] = [{
        "kind": "header", "dau_vao_header": head, "health": post("/health", None),
        "dau_vao_sha256": hashlib.sha256("".join(line + "\n" for line in lines if line.strip()).encode("utf-8")).hexdigest(),
        "started_at": datetime.now(UTC).isoformat(),
    }]  # fmt: skip
    for it in items:
        if hashlib.sha256(it["text"].encode("utf-8")).hexdigest() != it["text_sha256"]:
            raise SystemExit(f"{it['id']}: sha câu lệch — file đầu vào bị sửa")
        r = post("/classify_intent", {"text": it["text"]})
        out.append({
            "id": it["id"], "text_sha256": it["text_sha256"], "probs": r["probs"], "truncated": r["truncated"],
            "model": r["model"], "version": r["version"],
        })  # fmt: skip
    out[0]["finished_at"] = datetime.now(UTC).isoformat()
    return out


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        raise SystemExit("cách dùng: python cham.py <dau-vao.jsonl> > model-ra.jsonl")
    base, token = (
        os.environ.get("ML_SERVICE_URL", ""),
        os.environ.get("ML_SERVICE_TOKEN", ""),
    )
    if not base or not token:
        raise SystemExit(
            "thiếu ML_SERVICE_URL hoặc ML_SERVICE_TOKEN — chạy trong container backend"
        )
    with open(args[0], encoding="utf-8") as f:
        lines = f.read().splitlines()
    rows = score(lines, http_call(base, token))
    for r in rows:
        sys.stdout.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    print(f"đã chấm {len(rows) - 1} câu", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
