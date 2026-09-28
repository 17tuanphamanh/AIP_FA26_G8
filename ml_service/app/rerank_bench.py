"""`make rerank-bench` — đo tốc độ + độ lệch int8 của reranker TRONG TIẾN TRÌNH (không qua HTTP), để chọn cấu
hình theo Q-3a-16 (PLAN-3c mục 6). Nạp model bằng `app.loader.load_models` (dùng lại lock như service thật).

    python -m app.rerank_bench --kb /kb [--k 10,20] [--threads 3,4] [--int8] [--passage-tokens 380] [--n 10]

1. Câu truy vấn: `query` của mọi mục trong `<kb>/eval/retrieval_set.yaml`.
2. Đoạn văn: mọi `*.md` **enabled** dưới `<kb>/<type>/`, bỏ front matter, tách theo mục `##` (mỗi mục một đoạn).
3. Tốc độ: ghép mọi đoạn văn rồi cắt đúng `--passage-tokens` token (tokenizer của reranker, không token đặc
   biệt) làm MỘT đoạn đo cố định; với mỗi `(threads, K)`: 1 lượt làm nóng + `--n` lượt `predict(K cặp)` (câu
   truy vấn lặp vòng nếu `K > 14`) → in p50/p95 (ms).
4. `--int8`: lượng tử hoá động (`torch.quantization.quantize_dynamic`) một bản sao model CrossEncoder, chấm lại
   TOÀN BỘ 14 câu × mọi đoạn văn thật (không phải đoạn đo tốc độ) bằng cả hai bản → in max|Δscore| (thang
   sigmoid, khớp `RETRIEVAL_THRESHOLD`), tỉ lệ câu có top-1 trùng, số câu mà phán quyết `max score ≥ 0,6` đổi.
5. KHÔNG in văn bản KB (chỉ số đo).
"""

import argparse
import re
import statistics
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.models import Models, Reranker, Tokenizer
from app.rerank import sigmoid
from app.settings import MlSettings, default_threads

_FRONT_MATTER_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
_H2_RE = re.compile(r"(?m)^## ")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.rerank_bench",
                                description="Đo tốc độ + độ lệch int8 của reranker (Q-3a-16)")  # fmt: skip
    p.add_argument("--kb", type=Path, required=True, help="thư mục KB (có eval/retrieval_set.yaml)")
    p.add_argument("--k", default="10,20", help="số cặp mỗi lô, phẩy cách (mặc định 10,20)")
    p.add_argument("--threads", default=str(default_threads()), help="số luồng torch, phẩy cách")
    p.add_argument("--int8", action="store_true", help="đo thêm bản lượng tử hoá dynamic int8")
    p.add_argument("--passage-tokens", type=int, default=380, help="độ dài đoạn đo tốc độ, theo token")
    p.add_argument("--n", type=int, default=10, help="số lượt predict mỗi cấu hình (sau 1 lượt làm nóng)")
    return p


def parse_ints(csv: str) -> list[int]:
    return [int(x) for x in csv.split(",") if x.strip()]


def load_queries(kb_dir: Path) -> list[str]:
    raw = yaml.safe_load((kb_dir / "eval" / "retrieval_set.yaml").read_text(encoding="utf-8"))
    return [str(item["query"]) for item in raw["items"]]


def _front_matter(text: str) -> tuple[dict[str, object], str] | None:
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return None
    fm = yaml.safe_load(m.group(1))
    return (fm if isinstance(fm, dict) else {}), m.group(2)


def load_passages(kb_dir: Path) -> list[str]:
    """Mọi `*.md` enabled dưới `<kb>/<type>/`, tách theo mục `##` (mục đầu — trước `##` đầu tiên — bỏ nếu rỗng
    sau khi strip, ví dụ chỉ có tiêu đề `#`)."""
    out: list[str] = []
    for md in sorted(kb_dir.glob("*/*.md")):
        parsed = _front_matter(md.read_text(encoding="utf-8"))
        if parsed is None:
            continue
        fm, body = parsed
        if fm.get("enabled") is False:
            continue
        out.extend(section.strip() for section in _H2_RE.split(body) if section.strip())
    return out


def measurement_passage(tokenizer: Tokenizer, passages: Sequence[str], length: int) -> str:
    """Ghép mọi đoạn rồi cắt đúng `length` token (không token đặc biệt) — MỘT đoạn đo cố định."""
    joined = " ".join(passages)
    ids = list(tokenizer(joined, add_special_tokens=False)["input_ids"])[:length]
    return tokenizer.decode(ids)


def make_pairs(queries: Sequence[str], passage: str, k: int) -> list[tuple[str, str]]:
    return [(queries[i % len(queries)], passage) for i in range(k)]


def percentiles(samples_ms: Sequence[float]) -> tuple[float, float]:
    """(p50, p95) THUẦN — tách khỏi việc đo thời gian thật để test không cần chờ (mục 5)."""
    if not samples_ms:
        raise ValueError("cần ít nhất 1 mẫu")
    p50 = statistics.median(samples_ms)
    p95 = statistics.quantiles(samples_ms, n=20)[18] if len(samples_ms) >= 2 else samples_ms[0]
    return p50, p95


def measure_speed(reranker: Reranker, pairs: list[tuple[str, str]], n: int) -> tuple[float, float]:
    """Đo thời gian thật — KHÔNG unit test (mục 5); `percentiles` ở trên mới là phần thuần được kiểm."""
    reranker.logits(pairs)  # 1 lượt làm nóng, không tính
    samples = []
    for _ in range(n):
        started = time.perf_counter()
        reranker.logits(pairs)
        samples.append((time.perf_counter() - started) * 1000)
    return percentiles(samples)


@dataclass(frozen=True)
class Int8Report:
    max_abs_delta: float
    top1_match_rate: float
    verdict_changes: int  # số câu mà phán quyết `max score ≥ 0,6` đổi giữa fp32 và int8


def int8_deviation(
    fp32: Reranker, int8: Reranker, queries: Sequence[str], passages: Sequence[str], threshold: float = 0.6
) -> Int8Report:
    if not passages:
        raise ValueError("cần ít nhất 1 đoạn văn")
    max_delta = 0.0
    top1_match = 0
    changes = 0
    for q in queries:
        pairs = [(q, p) for p in passages]
        s32 = [sigmoid(x) for x in fp32.logits(pairs)]
        s8 = [sigmoid(x) for x in int8.logits(pairs)]
        max_delta = max(max_delta, max(abs(a - b) for a, b in zip(s32, s8, strict=True)))
        if s32.index(max(s32)) == s8.index(max(s8)):
            top1_match += 1
        if (max(s32) >= threshold) != (max(s8) >= threshold):
            changes += 1
    return Int8Report(max_delta, top1_match / len(queries) if queries else 1.0, changes)


def _quantized_reranker(models: Models) -> Reranker:
    """Lượng tử hoá động một BẢN SAO model CrossEncoder — chỉ gọi khi `--int8` (torch nạp muộn)."""
    # Nạp muộn: cùng lý do với app.loader (test không cần torch).
    import copy

    import torch

    from app.loader import _CeReranker

    assert isinstance(models.reranker, _CeReranker)
    quantized = copy.deepcopy(models.reranker._model)  # bench nội bộ, không phải API công khai của loader
    quantized = torch.quantization.quantize_dynamic(quantized, {torch.nn.Linear}, dtype=torch.qint8)
    return _CeReranker(quantized)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    import torch

    from app.loader import load_models

    settings = MlSettings()  # type: ignore[call-arg]  # token bắt buộc lấy từ env (compose), như main.py
    models = load_models(settings)
    queries = load_queries(args.kb)
    passages = load_passages(args.kb)
    if not passages:
        print(f"{args.kb}: không có đoạn văn enabled nào", file=sys.stderr)
        return 1
    passage = measurement_passage(models.rerank_tokenizer, passages, args.passage_tokens)
    int8_reranker = _quantized_reranker(models) if args.int8 else None
    for threads in parse_ints(args.threads):
        torch.set_num_threads(threads)
        for k in parse_ints(args.k):
            pairs = make_pairs(queries, passage, k)
            p50, p95 = measure_speed(models.reranker, pairs, args.n)
            print(f"threads={threads} k={k} fp32   p50={p50:8.0f} ms  p95={p95:8.0f} ms")
            if int8_reranker is not None:
                p50_8, p95_8 = measure_speed(int8_reranker, pairs, args.n)
                print(f"threads={threads} k={k} int8   p50={p50_8:8.0f} ms  p95={p95_8:8.0f} ms")
    if int8_reranker is not None:
        report = int8_deviation(models.reranker, int8_reranker, queries, passages)
        print(
            f"int8 deviation: max|Δ|={report.max_abs_delta:.4f}  "
            f"top1_match={report.top1_match_rate:.1%}  verdict_changes(0.6)={report.verdict_changes}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
