"""G7 — chỉ chạy kịch bản khi giờ THẬT cùng loại giờ (trong / ngoài giờ hành chính) với trường `at` của kịch bản (G2-Q10).

**Trong giờ** = `app.domain.policy.within_business_hours(now, get_policy().business_hours)` — đúng hàm + đúng policy backend dùng
lúc chạy, tính TRONG container backend (`HOURS_SCRIPT`, khuôn `runner.INFO_SCRIPT`): máy dev nạp gói luật giả, lúc đo nạp policy
thật. Harness không đọc file policy, không biết giờ bắt đầu / kết thúc / thứ: container chỉ trả danh sách bool. Không xét ngày lễ
(như hàm backend).

**Vùng đệm** `BUFFER` quanh CẢ HAI biên (đầu và cuối giờ, gồm biên thứ Sáu → thứ Bảy): hỏi container ba điểm `now − BUFFER`, `now`,
`now + BUFFER`; khác nhau → `now` ở gần biên → bỏ qua (`bien_gio`). Lấy mẫu như vậy cho vùng nửa mở `[biên − 10′, biên + 10′)`,
cùng kiểu `start ≤ giờ < end` của backend (G7-Q2). Cùng loại giờ nhưng khác `at` → `lech_loai_gio`.

`--resume` (`pending`, `check_no_rerun`, `read_prior`): chỉ chạy lại ca có kết cục MỚI NHẤT là `skipped_hours`; ca đã có bản ghi
chạy thật (kết cục khác `skipped_hours` hoặc có dòng predictions) mà sắp chạy lần 2 → `DuplicateRun` (không ghi trùng).

Mọi hàm ở đây thuần (thời điểm là tham số, không gọi đồng hồ) trừ `read_prior` (đọc file kết quả của lượt trước).
"""

import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from app.eval.predictions import PredictionRecord, load_predictions

BUFFER = timedelta(minutes=10)
SKIPPED = "skipped_hours"
LONG_TIMEOUT_S = 600  # G7-Q3: ca dài hơn vùng đệm có thể vượt biên giữa chừng → chỉ cảnh báo

type HoursClass = Literal["trong", "ngoai", "bien_gio"]
type SkipReason = Literal["lech_loai_gio", "bien_gio"]
HOURS_CLASSES: tuple[HoursClass, ...] = ("trong", "ngoai", "bien_gio")
SKIP_REASONS: tuple[SkipReason, ...] = ("lech_loai_gio", "bien_gio")

# Chạy TRONG container backend: `python -c HOURS_SCRIPT <iso> …` → một dòng `{"in_hours": [bool, …]}` (không giá trị cấu hình).
HOURS_SCRIPT = (
    "import json, sys\nfrom datetime import datetime\nfrom app.domain.policy import within_business_hours\n"
    "from app.settings import get_policy\nh = get_policy().business_hours\n"
    "print(json.dumps({'in_hours': [within_business_hours(datetime.fromisoformat(a), h) for a in sys.argv[1:]]}))\n"
)


class DuplicateRun(ValueError):
    """Kịch bản đã chạy thật mà sắp chạy lần 2 — chữ cố định, không id."""


@dataclass(frozen=True)
class HoursCheck:
    at_in: bool  # `at` trong giờ hành chính
    now_in: bool  # giờ thật trong giờ hành chính
    hours_class: HoursClass  # loại giờ thật
    skip: SkipReason | None  # None → chạy


def parse_at(at: str) -> datetime:
    """`at` → datetime CÓ múi giờ (ISO-8601, vd `2026-09-15T21:10:00+07:00`). Sai / thiếu múi giờ → ValueError chữ cố định."""
    try:
        t = datetime.fromisoformat(at)
    except ValueError:
        raise ValueError("at không phải ISO-8601") from None
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("at thiếu múi giờ")
    return t


def bad_at(ats: Sequence[str]) -> int:
    """Số `at` không hợp lệ (chỉ số đếm — không in giá trị)."""
    n = 0
    for at in ats:
        try:
            parse_at(at)
        except ValueError:
            n += 1
    return n


def probe_times(at: datetime, now: datetime, buffer: timedelta = BUFFER) -> tuple[datetime, datetime, datetime, datetime]:
    """Bốn thời điểm hỏi container: `(at, now − buffer, now, now + buffer)`."""
    return (at, now - buffer, now, now + buffer)


def decide(at_in: bool, before: bool, now_in: bool, after: bool) -> HoursCheck:
    if before != now_in or now_in != after:
        return HoursCheck(at_in=at_in, now_in=now_in, hours_class="bien_gio", skip="bien_gio")
    cls: HoursClass = "trong" if now_in else "ngoai"
    if now_in != at_in:
        return HoursCheck(at_in=at_in, now_in=now_in, hours_class=cls, skip="lech_loai_gio")
    return HoursCheck(at_in=at_in, now_in=now_in, hours_class=cls, skip=None)


def parse_probe(data: Mapping[str, Any], n: int) -> list[bool]:
    v = data.get("in_hours")
    if not isinstance(v, list) or len(v) != n or not all(isinstance(x, bool) for x in v):
        raise ValueError("container trả kết quả giờ hành chính không hợp lệ")
    return v


def pending(outcomes: Sequence[Mapping[str, Any]]) -> list[str]:
    """scenario_id có kết cục MỚI NHẤT (dòng sau cùng của id đó) là `skipped_hours`, theo thứ tự xuất hiện đầu tiên."""
    last: dict[str, str] = {}
    for row in outcomes:
        last[row["scenario_id"]] = row["outcome"]
    return [sid for sid, outcome in last.items() if outcome == SKIPPED]


def check_no_rerun(ids: Collection[str], outcomes: Sequence[Mapping[str, Any]], recorded: Collection[str]) -> None:
    for row in outcomes:
        if row["scenario_id"] in ids and row["outcome"] != SKIPPED:
            raise DuplicateRun("kịch bản đã có kết cục chạy thật — không chạy lần 2")
    if any(sid in recorded for sid in ids):
        raise DuplicateRun("kịch bản đã có bản ghi predictions — không chạy lần 2")


def pass_entry(no: int, started_at: str, finished_at: str, checks: Sequence[HoursCheck]) -> dict[str, Any]:
    """Một phần tử `manifest.passes`: khung giờ THẬT của lần chạy + số ca theo lý do / loại giờ (không giá trị cấu hình)."""
    return {
        "pass": no, "started_at": started_at, "finished_at": finished_at, "ran": sum(c.skip is None for c in checks),
        SKIPPED: sum(c.skip is not None for c in checks), **{r: sum(c.skip == r for c in checks) for r in SKIP_REASONS},
        "hours_class": {h: sum(c.hours_class == h for c in checks) for h in HOURS_CLASSES},
    }  # fmt: skip


def merge_counts(prior: Mapping[str, int], now: Mapping[str, int]) -> dict[str, int]:
    """`manifest.counts` sau một lần resume = trạng thái cuối: lần này chạy lại ĐÚNG các ca skipped của lượt trước, nên mọi số cộng
    dồn, trừ `loaded` (cả bộ kịch bản) và `skipped_hours` (chỉ còn số bỏ qua của lần này)."""
    return {k: v if k in ("loaded", SKIPPED) else prior.get(k, 0) + v for k, v in now.items()}


@dataclass(frozen=True)
class Prior:
    """Kết quả của các lần chạy trước trong thư mục `--resume`."""

    manifest: dict[str, Any]
    outcome_lines: tuple[str, ...]  # nguyên văn, mỗi dòng có "\n" — ghi lại y hệt
    outcomes: tuple[dict[str, Any], ...]
    records: tuple[PredictionRecord, ...]


def read_prior(run_dir: Path) -> Prior:
    """Đọc `manifest.json`, `outcomes.jsonl`, `predictions.jsonl` của lượt trước. Thiếu / hỏng → ValueError chữ cố định."""
    paths = [run_dir / f for f in ("predictions.jsonl", "outcomes.jsonl", "manifest.json")]
    if not all(p.is_file() for p in paths):
        raise ValueError("--resume: thư mục thiếu file kết quả của lượt trước")
    pred, outc, man = paths
    try:
        manifest = json.loads(man.read_text(encoding="utf-8"))
        lines = tuple(outc.read_text(encoding="utf-8").splitlines(keepends=True))
        outcomes = tuple(json.loads(x) for x in lines)
    except ValueError:
        raise ValueError("--resume: manifest.json / outcomes.jsonl hỏng") from None
    # ValueError (không TypeError): runner đổi mọi ValueError của file lượt trước thành DỪNG mã 2
    manifest_ok = isinstance(manifest, dict) and all(isinstance(manifest.get(k), t) for k, t in (
        ("run_id", str), ("passes", list), ("counts", dict), ("started_at", str)))  # fmt: skip
    if not manifest_ok:
        raise ValueError("--resume: manifest.json thiếu run_id / passes / counts / started_at")
    outcomes_ok = all(isinstance(o, dict) and isinstance(o.get("scenario_id"), str) and "outcome" in o for o in outcomes)
    if not outcomes_ok:
        raise ValueError("--resume: outcomes.jsonl hỏng")
    try:
        records = tuple(load_predictions(pred)) if pred.read_text(encoding="utf-8") else ()
    except ValueError:
        raise ValueError("--resume: predictions.jsonl không qua hợp đồng v1.1") from None
    return Prior(manifest=manifest, outcome_lines=lines, outcomes=outcomes, records=records)
