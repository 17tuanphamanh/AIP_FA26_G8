"""Chỉ số groundedness (định nghĩa [Đề xuất] ở docstring `app.eval.groundedness`) + khoảng tin cậy bootstrap theo họ.

Mẫu số: ca `status == "judged"`. Tỉ lệ ý được hỗ trợ (gộp) = Σ ý `supported` ÷ Σ ý; trung bình theo ca = trung bình tỉ lệ từng ca có ≥ 1
ý. Citation precision = cặp (ca, đoạn được dẫn) có đoạn đó là bằng chứng `supported` của ≥ 1 ý trong ca ÷ tổng cặp. Khoảng tin cậy:
rút lại HỌ (P8 6.4, `BOOTSTRAP_N`/`SEED`/`LEVEL` của `app.eval.stats`), mỗi họ mang mọi ca của nó; thống kê = tỉ số của hai tổng.
Lần rút mẫu số 0 → bỏ, đếm `n_undefined` (không coi là 0).
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from app.eval.groundedness.models import JudgedAnswer
from app.eval.stats import BOOTSTRAP_N, LEVEL, SEED, percentile_interval

type Pair = tuple[int, int]  # (tử, mẫu) của một họ


def _supported_chunks(answer: JudgedAnswer) -> set[str]:
    return {c for claim in answer.claims if claim.verdict == "supported" for c in claim.chunk_ids}


def answer_pairs(answer: JudgedAnswer) -> tuple[int, int]:
    """(số cặp được dẫn chính xác, số cặp được dẫn) của một ca. Đoạn dẫn không có trong `chunks` không chính xác."""
    supporting = _supported_chunks(answer)
    return sum(1 for c in answer.citations if c in supporting), len(answer.citations)


def _ratio_ci(units: Mapping[str, Pair], n_boot: int, seed: int, level: float) -> dict[str, Any]:
    names = sorted(units)
    nums = np.array([units[n][0] for n in names], dtype=np.int64)
    dens = np.array([units[n][1] for n in names], dtype=np.int64)
    k = len(names)
    out: dict[str, Any] = {"lo": None, "hi": None, "n_boot": n_boot, "n_used": 0, "n_undefined": 0, "n_families": k,
                           "seed": seed, "level": level}  # fmt: skip
    if k == 0 or dens.sum() == 0:
        return out
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, k, size=k)
        den = int(dens[idx].sum())
        if den == 0:
            out["n_undefined"] += 1
        else:
            values.append(float(nums[idx].sum()) / den)
    if values:
        out["lo"], out["hi"] = percentile_interval(values, level)
    out["n_used"] = len(values)
    return out


def _rate(num: int, den: int) -> float | None:
    return None if den == 0 else num / den


def score(
    answers: Sequence[JudgedAnswer], *, n_boot: int = BOOTSTRAP_N, seed: int = SEED, level: float = LEVEL
) -> dict[str, Any]:
    by_status: dict[str, int] = defaultdict(int)
    for a in answers:
        by_status[a.status] += 1
    judged = [a for a in answers if a.status == "judged"]
    claims = [c for a in judged for c in a.claims]
    n_supported = sum(c.verdict == "supported" for c in claims)
    n_partial = sum(c.verdict == "partial" for c in claims)
    n_unsupported = sum(c.verdict == "unsupported" for c in claims)
    per_answer = [
        sum(c.verdict == "supported" for c in a.claims) / len(a.claims) for a in judged if a.claims
    ]  # fmt: skip
    pairs = [answer_pairs(a) for a in judged]
    n_precise, n_pairs = sum(p[0] for p in pairs), sum(p[1] for p in pairs)
    support_units: dict[str, Pair] = defaultdict(lambda: (0, 0))
    precision_units: dict[str, Pair] = defaultdict(lambda: (0, 0))
    for a, (precise, total) in zip(judged, pairs, strict=True):
        s = sum(c.verdict == "supported" for c in a.claims)
        n0, d0 = support_units[a.family]
        support_units[a.family] = (n0 + s, d0 + len(a.claims))
        n1, d1 = precision_units[a.family]
        precision_units[a.family] = (n1 + precise, d1 + total)
    return {
        "n_answers": len(answers),
        "n_judged": len(judged),
        "n_cannot_answer": by_status["cannot_answer"],
        "n_no_claims": by_status["no_claims"],
        "n_errors": by_status["error"],
        "n_no_citation": sum("no_citation" in a.flags for a in judged),
        "n_claims": len(claims),
        "n_supported": n_supported,
        "n_partial": n_partial,
        "n_unsupported": n_unsupported,
        "supported_rate": _rate(n_supported, len(claims)),
        "partial_rate": _rate(n_partial, len(claims)),
        "unsupported_rate": _rate(n_unsupported, len(claims)),
        "supported_rate_macro": float(np.mean(per_answer)) if per_answer else None,
        "supported_rate_ci": _ratio_ci(support_units, n_boot, seed, level),
        "n_citation_pairs": n_pairs,
        "n_citation_pairs_precise": n_precise,
        "n_invalid_citation_pairs": sum(len(a.invalid_citations) for a in judged),
        "citation_precision": _rate(n_precise, n_pairs),
        "citation_precision_ci": _ratio_ci(precision_units, n_boot, seed, level),
    }
