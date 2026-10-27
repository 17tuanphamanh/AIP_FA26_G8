"""Chia kiểm tra chéo k phần theo HỌ (P8 v1.5 §4.3) — `make_folds` + hai đầu ra từ CÙNG một lần chia.

- Đơn vị = họ (`Scenario.family`); MỌI kịch bản của một họ vào CÙNG một phần.
- Phân tầng theo (nhãn đại diện họ, intent họ) rồi chia vòng tròn theo `seed`:
  - nhãn đại diện = `gold.expected_route` chiếm đa số (đếm theo kịch bản trong họ); hoà → chặt hơn (ESCALATE_L2 > HITL > AUTO);
  - intent họ = intent đầu (`gold.intents[0]`) chiếm đa số; hoà → theo thứ tự chữ (tất định);
  - tầng xếp theo (nhãn chặt hơn trước, intent); trong mỗi tầng họ sắp theo tên rồi xáo bằng `random.Random(seed)`; một bộ đếm CHUNG
    cho mọi tầng gán phần `(đếm mod k) + 1` → số họ mỗi phần chênh nhau tối đa 1, nhãn hiếm (L2) rải đều các phần.
- Kịch bản chưa nhãn (`expected_route = null`) → `SplitError` (không chia trên nhãn thiếu). Kịch bản bộ phát triển D1/D2 (id dạng
  `HBxx-vN`) → `SplitError`: D-59 — chỉ để phát triển, không vào kiểm tra chéo; thư mục chia chỉ được chứa thẻ đo.
- Ít họ hơn k → `SplitError` (có phần rỗng — `check_split.py` từ chối).

Hai đầu ra (cùng `folds`): `eval/SPLIT.md` đúng schema `scripts/eval/check_split.py` (G9) đọc — `seed`, `k`, `dataset_sha256`,
`files` (sha từng file), `families` (họ → phần), `locked` — và CSV `family,fold` mà `offline.load_folds` đọc. Băm bằng ĐÚNG hàm của
`app.eval.dataset` (`scenario_files`, `file_sha256`, `dataset_sha256`), không viết lại công thức.

Lỗi và log CHỈ nêu số đếm — không tên họ, không id kịch bản, không nhãn của từng họ (D-43: chưa khoá nhãn thì không lộ nhãn).
"""

import random
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.eval.dataset import (
    Scenario,
    dataset_sha256,
    file_sha256,
    load_scenarios,
    load_seed_users,
    scenario_files,
)
from app.eval.predictions import CV_K
from app.eval.stats import SEED
from app.risk.decision_math import Route

STRICTNESS: Mapping[Route, int] = {
    "AUTO": 0,
    "HITL": 1,
    "ESCALATE_L2": 2,
}  # hoà nhãn → chặt hơn thắng
DEV_ID = re.compile(r"^HB\d{2}-v\d+$")  # id kịch bản bộ phát triển D1/D2 (D-59)
CSV_HEADER = "family,fold"


class SplitError(ValueError):
    """Dữ liệu không chia được. Thông điệp chỉ có số đếm."""


@dataclass(frozen=True)
class FamilyProfile:
    family: str
    label: Route
    intent: str
    n: int


def _majority_label(labels: Sequence[Route]) -> Route:
    counts = Counter(labels)
    return max(counts, key=lambda r: (counts[r], STRICTNESS[r]))


def _majority_intent(intents: Sequence[str]) -> str:
    counts = Counter(intents)
    return min(counts, key=lambda i: (-counts[i], i))


def family_profiles(scenarios: Sequence[Scenario]) -> dict[str, FamilyProfile]:
    if not scenarios:
        raise SplitError("không có kịch bản nào")
    dev = sum(1 for s in scenarios if DEV_ID.match(s.id))
    if dev:
        raise SplitError(
            f"{dev} kịch bản thuộc bộ phát triển D1/D2 (D-59) — chuyển ra khỏi thư mục chia trước khi chia"
        )
    unlabelled = sum(1 for s in scenarios if s.gold.expected_route is None)
    if unlabelled:
        raise SplitError(
            f"{unlabelled} kịch bản chưa nhãn (gold.expected_route null) — chỉ chia sau khi khoá nhãn"
        )
    by_family: dict[str, list[Scenario]] = {}
    for s in scenarios:
        by_family.setdefault(s.family, []).append(s)
    out: dict[str, FamilyProfile] = {}
    for fam, members in by_family.items():
        labels = [
            s.gold.expected_route for s in members if s.gold.expected_route is not None
        ]
        out[fam] = FamilyProfile(
            fam,
            _majority_label(labels),
            _majority_intent([s.gold.intents[0] for s in members]),
            len(members),
        )
    return out


def make_folds(
    scenarios: Sequence[Scenario], k: int = CV_K, seed: int = SEED
) -> dict[str, int]:
    """Họ → phần 1..k (P8 §4.3). Tất định theo (tập kịch bản, k, seed); không phụ thuộc thứ tự đầu vào."""
    if k < 2:
        raise SplitError("k phải ≥ 2")
    profiles = family_profiles(scenarios)
    if len(profiles) < k:
        raise SplitError(f"chỉ có {len(profiles)} họ, ít hơn k = {k} — sẽ có phần rỗng")
    strata: dict[tuple[Route, str], list[str]] = {}
    for p in profiles.values():
        strata.setdefault((p.label, p.intent), []).append(p.family)
    rng = random.Random(seed)
    folds: dict[str, int] = {}
    counter = 0
    for key in sorted(strata, key=lambda t: (-STRICTNESS[t[0]], t[1])):
        members = sorted(strata[key])
        rng.shuffle(members)
        for fam in members:
            folds[fam] = counter % k + 1
            counter += 1
    return dict(sorted(folds.items()))


def file_hashes(directory: Path) -> dict[str, str]:
    """Tên file kịch bản (cấp 1) → sha256 nội dung — cùng tập file và cùng hàm băm với `Dataset.sha256`."""
    return {p.name: file_sha256(p.read_bytes()) for p in scenario_files(directory)}


def split_md(
    files: Mapping[str, str],
    folds: Mapping[str, int],
    *,
    k: int,
    seed: int,
    locked: bool,
) -> str:
    data = {
        "seed": seed, "k": k, "dataset_sha256": dataset_sha256(files.items()), "files": dict(sorted(files.items())),
        "families": dict(sorted(folds.items())), "locked": locked,
    }  # fmt: skip
    body = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    return (
        "# SPLIT — kiểm tra chéo theo họ (P8 §4.3)\n\n"
        "Sinh bằng `scripts/eval/make_split.py` (`app.eval.split.make_folds`). Không sửa tay — CI (`scripts/eval/check_split.py`) "
        "kiểm mã băm từng file kịch bản.\n\n"
        f"```yaml\n{body}```\n"
    )


def folds_csv(folds: Mapping[str, int]) -> str:
    return (
        CSV_HEADER
        + "\n"
        + "".join(f"{fam},{fold}\n" for fam, fold in sorted(folds.items()))
    )


@dataclass(frozen=True)
class SplitResult:
    folds: Mapping[str, int]
    split_md: str
    csv: str
    n_scenarios: int
    n_files: int
    fold_sizes: Mapping[int, int]  # phần → số kịch bản


def build_split(
    scenarios_dir: Path,
    seed_file: Path,
    *,
    k: int = CV_K,
    seed: int = SEED,
    locked: bool = False,
) -> SplitResult:
    """Nạp kịch bản (đúng `load_scenarios` của harness) → `make_folds` → SPLIT.md + CSV từ CÙNG `folds`."""
    dataset = load_scenarios(scenarios_dir, users=load_seed_users(seed_file))
    files = file_hashes(scenarios_dir)
    if (
        dataset_sha256(files.items()) != dataset.sha256
    ):  # cùng tập file + cùng công thức → phải bằng
        raise SplitError("mã băm dữ liệu không khớp giữa lần nạp và lần băm file")
    folds = make_folds(dataset.scenarios, k=k, seed=seed)
    sizes = Counter(folds[s.family] for s in dataset.scenarios)
    return SplitResult(folds, split_md(files, folds, k=k, seed=seed, locked=locked), folds_csv(folds), len(dataset.scenarios),
                       len(files), dict(sorted(sizes.items())))  # fmt: skip
