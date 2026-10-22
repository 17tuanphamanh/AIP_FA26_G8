"""Mẫu cho người soát (30 ca, có seed) và độ đồng thuận LLM–người (G11; huong-dan 17.4 "người soát 30 mẫu").

- **Đơn vị mẫu = ca** (mọi ý của ca vào bản soát). Chỉ ca `judged` có ≥ 1 ý. Mặc định PHÂN TẦNG: nửa số ca có ≥ 1 ý không được hỗ trợ
  theo LLM (`partial`/`unsupported`), nửa còn lại; thiếu tầng nào thì bù từ tầng kia. `--random`: rút ngẫu nhiên thuần. RNG =
  `random.Random(seed)` trên danh sách sắp theo `scenario_id` → cùng đầu vào + seed = cùng mẫu.
- **Mù**: `review_sample.jsonl` KHÔNG chứa verdict LLM (người soát không bị neo); verdict ở `review_key.jsonl`.
- **Nhãn người** = chính `review_sample.jsonl` đã điền `human_supported` (true/false). Thiếu nhãn, nhãn thừa, trùng, null, không
  phải bool → `ValueError` (không bỏ qua im lặng).
- **Đồng thuận** (mức ý, nhị phân; LLM dương = `supported`, `partial` là âm): tỉ lệ khớp, Cohen κ (+ khoảng tin cậy bootstrap
  rút lại CA), ma trận nhầm, và số ý/ca "LLM hỗ trợ / người không" — lỗi làm tỉ lệ groundedness bị thổi phồng. κ không xác định
  (pe = 1) → `null` kèm lý do. Giới hạn của mẫu phân tầng: xem docstring `app.eval.groundedness`.
"""

import json
import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from app.eval.groundedness.models import AnswerRow, JudgedAnswer
from app.eval.stats import BOOTSTRAP_N, LEVEL, SEED, percentile_interval

SAMPLE_N = 30

type ClaimKey = tuple[str, int]


def _not_supported(answer: JudgedAnswer) -> bool:
    return any(c.verdict != "supported" for c in answer.claims)


def draw_sample(
    answers: Sequence[JudgedAnswer], *, n: int = SAMPLE_N, seed: int = SEED, stratify: bool = True
) -> tuple[list[JudgedAnswer], dict[str, Any]]:
    if n < 1:
        raise ValueError("n phải ≥ 1")
    pool = sorted((a for a in answers if a.status == "judged" and a.claims), key=lambda a: a.scenario_id)
    meta: dict[str, Any] = {"mode": "stratified" if stratify else "random", "seed": seed, "n_requested": n,
                            "n_pool": len(pool)}  # fmt: skip
    rng = random.Random(seed)
    if n >= len(pool):
        chosen = list(pool)
    elif not stratify:
        chosen = rng.sample(pool, n)
    else:
        weak = [a for a in pool if _not_supported(a)]
        solid = [a for a in pool if not _not_supported(a)]
        take_weak = min(n // 2, len(weak))
        take_solid = min(n - take_weak, len(solid))
        chosen = rng.sample(weak, take_weak) + rng.sample(solid, take_solid)
        short = n - len(chosen)
        if short > 0:  # một tầng cạn → bù từ tầng còn dư
            rest = [a for a in weak if a not in chosen] + [a for a in solid if a not in chosen]
            chosen += rng.sample(rest, short)
        meta |= {"n_pool_weak": len(weak), "n_pool_solid": len(solid)}
    chosen.sort(key=lambda a: a.scenario_id)
    meta["n_answers"] = len(chosen)
    meta["n_claims"] = sum(len(a.claims) for a in chosen)
    meta["scenario_ids"] = [a.scenario_id for a in chosen]
    return chosen, meta


def review_rows(sample: Sequence[JudgedAnswer], rows: Mapping[str, AnswerRow]) -> list[dict[str, Any]]:
    """Bản cho người soát: ý + đoạn được dẫn (chữ đầy đủ) + ô nhãn trống. KHÔNG có verdict LLM."""
    out: list[dict[str, Any]] = []
    for a in sample:
        row = rows.get(a.scenario_id)
        if row is None:
            raise ValueError(f"answers không có scenario_id của mẫu: {a.scenario_id}")
        by_id = {c.chunk_id: c for c in row.chunks}
        cited = [by_id[c] for c in a.citations if c in by_id]
        for claim in a.claims:
            out.append({
                "scenario_id": a.scenario_id, "claim_id": claim.claim_id, "claim": claim.text,
                "cited_chunks": [{"chunk_id": c.chunk_id, "text": c.text} for c in cited],
                "human_supported": None, "note": None,
            })  # fmt: skip
    return out


def key_rows(sample: Sequence[JudgedAnswer]) -> list[dict[str, Any]]:
    return [
        {"scenario_id": a.scenario_id, "claim_id": c.claim_id, "llm_verdict": c.verdict, "llm_chunk_ids": list(c.chunk_ids)}
        for a in sample for c in a.claims
    ]  # fmt: skip


def load_labels(path: Path) -> dict[ClaimKey, bool]:
    labels: dict[ClaimKey, bool] = {}
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except ValueError:
            raise ValueError(f"{path.name}: dòng {no} không phải JSON") from None
        record = data if isinstance(data, dict) else {}
        sid, cid, human = record.get("scenario_id"), record.get("claim_id"), record.get("human_supported")
        if not isinstance(sid, str) or not isinstance(cid, int) or isinstance(cid, bool):
            raise ValueError(f"{path.name}: dòng {no} thiếu scenario_id/claim_id hợp lệ")  # noqa: TRY004 — lỗi dữ liệu = ValueError
        if not isinstance(human, bool):
            raise ValueError(f"{path.name}: dòng {no} ({sid}#{cid}) human_supported phải là true/false")  # noqa: TRY004
        if (sid, cid) in labels:
            raise ValueError(f"{path.name}: nhãn trùng ở dòng {no} ({sid}#{cid})")
        labels[(sid, cid)] = human
    return labels


def load_key(path: Path) -> dict[ClaimKey, str]:
    """`review_key.jsonl` → (scenario_id, claim_id) → verdict của LLM."""
    key: dict[ClaimKey, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            key[(d["scenario_id"], int(d["claim_id"]))] = d["llm_verdict"]
    return key


def _kappa(a: int, b: int, c: int, d: int) -> tuple[float | None, str | None]:
    """a = cả hai dương, b = LLM dương/người âm, c = LLM âm/người dương, d = cả hai âm."""
    n = a + b + c + d
    po = (a + d) / n
    pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    if pe == 1:
        return None, "pe = 1: cả hai chỉ dùng một lớp nên κ không xác định"
    return (po - pe) / (1 - pe), None


def agreement(
    key: Mapping[ClaimKey, str], labels: Mapping[ClaimKey, bool], *, n_boot: int = BOOTSTRAP_N, seed: int = SEED,
    level: float = LEVEL,
) -> dict[str, Any]:
    missing = sorted(set(key) - set(labels))
    extra = sorted(set(labels) - set(key))
    if missing or extra:
        raise ValueError(
            f"nhãn người không khớp mẫu: thiếu {len(missing)} ý {missing[:5]}, thừa {len(extra)} ý {extra[:5]}"
        )
    if not key:
        raise ValueError("mẫu rỗng")
    cells = {"a": 0, "b": 0, "c": 0, "d": 0}
    per_answer: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    inflated: list[dict[str, Any]] = []
    deflated: list[dict[str, Any]] = []
    for (sid, cid), verdict in sorted(key.items()):
        llm_pos, human_pos = verdict == "supported", labels[(sid, cid)]
        cell = "a" if llm_pos and human_pos else "b" if llm_pos else "c" if human_pos else "d"
        cells[cell] += 1
        per_answer[sid]["abcd".index(cell)] += 1
        if cell == "b":
            inflated.append({"scenario_id": sid, "claim_id": cid, "llm_verdict": verdict})
        elif cell == "c":
            deflated.append({"scenario_id": sid, "claim_id": cid, "llm_verdict": verdict})
    a, b, c, d = cells["a"], cells["b"], cells["c"], cells["d"]
    n = a + b + c + d
    kappa, why = _kappa(a, b, c, d)
    names = sorted(per_answer)
    table = np.array([per_answer[s] for s in names], dtype=np.int64)
    rng = np.random.default_rng(seed)
    boots: list[float] = []
    undefined = 0
    for _ in range(n_boot):
        tot = table[rng.integers(0, len(names), size=len(names))].sum(axis=0)
        k, _ = _kappa(int(tot[0]), int(tot[1]), int(tot[2]), int(tot[3]))
        if k is None:
            undefined += 1
        else:
            boots.append(k)
    lo, hi = percentile_interval(boots, level) if boots else (None, None)
    return {
        "n_claims": n, "n_answers": len(names),
        "agreement": (a + d) / n, "kappa": kappa, "kappa_undefined_reason": why,
        "kappa_ci": {"lo": lo, "hi": hi, "n_boot": n_boot, "n_used": len(boots), "n_undefined": undefined,
                     "seed": seed, "level": level, "unit": "answer"},
        "confusion": {"llm_supported_human_supported": a, "llm_supported_human_not": b,
                      "llm_not_human_supported": c, "llm_not_human_not": d},
        "llm_supported_human_not": {
            "n_claims": b, "n_answers": len({x["scenario_id"] for x in inflated}),
            "share_of_llm_supported": (b / (a + b)) if a + b else None, "items": inflated,
        },
        "llm_not_human_supported": {"n_claims": c, "n_answers": len({x["scenario_id"] for x in deflated}), "items": deflated},
        "llm_supported_rate_on_sample": (a + b) / n,
        "human_supported_rate_on_sample": (a + c) / n,
    }
