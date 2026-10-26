"""Kiểm trùng câu thẻ đánh giá với dữ liệu huấn luyện của intent-clf / injection-clf (P11 mục 3.4 bước 2; P8 mục 4.3).

Chạy: python -m training.common.dedup_vs_m8 --cau CAU.jsonl --train DATA [--train DATA ...]
          (--embed-url URL | --no-embed) [--nguong 0.90] --out OUT.csv

Bước A — khớp chính xác sau chuẩn hoá (normalize → bỏ dấu → thường hoá → gộp khoảng trắng).
Bước B — gần trùng: cosine vector bge-m3 ≥ ngưỡng. Vector lấy qua POST <embed-url>/embed của ml-service (không tải model ở đây;
token dịch vụ, nếu cần, lấy từ biến môi trường ML_SERVICE_TOKEN — không đọc .env). `--no-embed` bỏ bước B và báo rõ trong tóm tắt.

Chỉ đọc hai trường `the`, `text` của file câu; stdout/stderr chỉ có số đếm và số dòng lỗi, không bao giờ in nội dung câu.
Mã thoát: 0 không trùng, 3 có trùng, 2 lỗi đầu vào.
"""

import argparse
import csv
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np

# `python -m training.common.dedup_vs_m8` từ gốc repo: `app` nằm ở backend/ (pytest đã đặt pythonpath riêng).
_BACKEND = str(Path(__file__).resolve().parents[2] / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

from app.core.textnorm import fold_diacritics, normalize

DEFAULT_NGUONG = 0.90
EMBED_BATCH = 64  # EMBED_MAX_ITEMS của ml-service
EMBED_TIMEOUT_S = 60.0
_SIM_CHUNK = 512
_TRAIN_SUFFIXES = (".jsonl", ".csv", ".txt")
_SPACES = re.compile(r"\s+")
_FIELDS = ("the", "text", "kieu", "diem", "cau_train_gan_nhat", "nguon_file")


class InputError(Exception):
    """Lỗi đầu vào / dịch vụ embed. Thông điệp chỉ có tên file, số dòng, mã lỗi — không có nội dung câu."""


@dataclass(frozen=True)
class Cau:
    the: str
    text: str


@dataclass(frozen=True)
class Row:
    the: str
    text: str
    kieu: str  # "exact" | "cosine"
    diem: float
    gan_nhat: str
    nguon: str


def canon(text: str) -> str:
    return _SPACES.sub(" ", fold_diacritics(normalize(text)).lower()).strip()


def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise InputError(f"{path}: không đọc được ({type(e).__name__})") from None


def _json_obj(path: Path, n: int, line: str) -> dict[str, object]:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        raise InputError(f"{path}: dòng {n} không phải JSON") from None
    if not isinstance(obj, dict):
        raise InputError(f"{path}: dòng {n} không phải đối tượng JSON")
    return obj


def read_cau(path: Path) -> list[Cau]:
    out: list[Cau] = []
    for n, line in enumerate(_read_lines(path), 1):
        if not line.strip():
            continue
        obj = _json_obj(path, n, line)
        the, text = obj.get("the"), obj.get("text")
        if not (isinstance(the, str) and the and isinstance(text, str) and text.strip()):
            raise InputError(f"{path}: dòng {n} thiếu `the` hoặc `text` (chuỗi không rỗng)")
        out.append(Cau(the, text))
    return out


def _train_files(paths: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in _TRAIN_SUFFIXES)
        elif p.is_file():
            if p.suffix.lower() not in _TRAIN_SUFFIXES:
                raise InputError(f"{p}: định dạng không hỗ trợ (jsonl/csv/txt)")
            files.append(p)
        else:
            raise InputError(f"{p}: không tồn tại")
    return files


def _read_train_file(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return [ln for ln in _read_lines(path) if ln.strip()]
    if suffix == ".jsonl":
        texts: list[str] = []
        for n, line in enumerate(_read_lines(path), 1):
            if not line.strip():
                continue
            text = _json_obj(path, n, line).get("text")
            if not isinstance(text, str):
                raise InputError(f"{path}: dòng {n} thiếu khoá `text`")
            if text.strip():
                texts.append(text)
        return texts
    try:
        with path.open(encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "text" not in reader.fieldnames:
                raise InputError(f"{path}: thiếu cột `text`")
            return [r["text"] for r in reader if isinstance(r.get("text"), str) and r["text"].strip()]
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        raise InputError(f"{path}: không đọc được ({type(e).__name__})") from None


def read_train(paths: Sequence[Path]) -> list[tuple[str, str]]:
    """[(câu huấn luyện, nguồn file)] theo thứ tự đọc."""
    return [(t, str(f)) for f in _train_files(paths) for t in _read_train_file(f)]


def exact_pass(cau: Sequence[Cau], train: Sequence[tuple[str, str]]) -> list[Row]:
    index: dict[str, tuple[str, str]] = {}
    for text, nguon in train:
        index.setdefault(canon(text), (text, nguon))
    rows = []
    for c in cau:
        hit = index.get(canon(c.text))
        if hit is not None:
            rows.append(Row(c.the, c.text, "exact", 1.0, hit[0], hit[1]))
    return rows


def _embed_batch(url: str, texts: list[str], token: str | None) -> list[list[float]]:
    """Điểm gọi HTTP duy nhất (test thay bằng bản giả). Hợp đồng: ml_service/app/schemas.py EmbedIn/EmbedOut."""
    headers = {"X-Service-Token": token} if token else {}
    r = httpx.post(url.rstrip("/") + "/embed", json={"texts": texts}, headers=headers, timeout=EMBED_TIMEOUT_S)
    r.raise_for_status()
    return r.json()["vectors"]  # type: ignore[no-any-return]


def embed_all(url: str, texts: Sequence[str]) -> np.ndarray:
    token = os.environ.get("ML_SERVICE_TOKEN") or None
    vectors: list[list[float]] = []
    try:
        for i in range(0, len(texts), EMBED_BATCH):
            batch = list(texts[i : i + EMBED_BATCH])
            got = _embed_batch(url, batch, token)
            if len(got) != len(batch):
                raise InputError("embed trả sai số vector")
            vectors += got
        arr = np.asarray(vectors, dtype=np.float64)
    except InputError:
        raise
    except httpx.HTTPStatusError as e:
        raise InputError(f"gọi embed lỗi HTTP {e.response.status_code}") from None
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        raise InputError(f"gọi embed lỗi ({type(e).__name__})") from None
    if arr.ndim != 2 or arr.shape[0] != len(texts):
        raise InputError("embed trả vector sai dạng")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return arr / np.where(norms == 0, 1.0, norms)  # type: ignore[no-any-return]


def cosine_pass(cau: Sequence[Cau], train: Sequence[tuple[str, str]], url: str, nguong: float) -> list[Row]:
    if not cau or not train:
        return []
    uniq: dict[str, tuple[str, str]] = {}
    for text, nguon in train:
        uniq.setdefault(canon(text), (text, nguon))
    refs = list(uniq.values())
    vecs = embed_all(url, [normalize(c.text) for c in cau] + [normalize(t) for t, _ in refs])
    cv, tv = vecs[: len(cau)], vecs[len(cau) :]
    if cv.shape[1] != tv.shape[1]:
        raise InputError("embed trả vector sai dạng")
    rows = []
    for start in range(0, len(cau), _SIM_CHUNK):
        sims = cv[start : start + _SIM_CHUNK] @ tv.T
        best = sims.argmax(axis=1)
        for k, j in enumerate(best):
            score = float(sims[k, j])
            if score >= nguong:
                c = cau[start + k]
                rows.append(Row(c.the, c.text, "cosine", score, refs[j][0], refs[j][1]))
    return rows


def write_csv(rows: Sequence[Row], out: Path) -> None:
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(_FIELDS)
            for r in rows:
                w.writerow([r.the, r.text, r.kieu, f"{r.diem:.6f}", r.gan_nhat, r.nguon])
    except OSError as e:
        raise InputError(f"{out}: không ghi được ({type(e).__name__})") from None


def find_dups(
    cau: Sequence[Cau], train: Sequence[tuple[str, str]], embed_url: str | None, nguong: float
) -> tuple[list[Row], list[Row]]:
    """(trùng chính xác, gần trùng). Câu đã trùng chính xác không xét lại ở bước B; embed_url=None → bỏ bước B."""
    exact = exact_pass(cau, train)
    if embed_url is None:
        return exact, []
    hit = {(r.the, r.text) for r in exact}
    return exact, cosine_pass([c for c in cau if (c.the, c.text) not in hit], train, embed_url, nguong)


def _summary(n_cau: int, exact: Sequence[Row], near: Sequence[Row], embed: bool, nguong: float, out: Path) -> str:
    the = {r.the for r in (*exact, *near)}
    b = f"Gần trùng (cosine ≥ {nguong:g}): {len(near)}" if embed else "Bước B (cosine): BỎ QUA (--no-embed) — chưa đủ điều kiện P11 mục 3.4"
    return "\n".join(
        [
            f"Số câu thẻ: {n_cau}",
            f"Trùng chính xác: {len(exact)}",
            b,
            f"Số thẻ bị ảnh hưởng: {len(the)}",
            f"CSV: {out}",
        ]
    )


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m training.common.dedup_vs_m8", description=__doc__.split("\n")[0])  # type: ignore[union-attr]
    p.add_argument("--cau", type=Path, required=True, help='JSONL {"the","text"} — câu thẻ đánh giá')
    p.add_argument("--train", type=Path, action="append", required=True, help="file/thư mục jsonl|csv|txt; lặp được")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--embed-url", help="gốc URL ml-service (POST <url>/embed)")
    g.add_argument("--no-embed", action="store_true", help="chỉ khớp chính xác, bỏ bước cosine")
    p.add_argument("--nguong", type=float, default=DEFAULT_NGUONG, help="ngưỡng cosine (mặc định 0.90)")
    p.add_argument("--out", type=Path, required=True, help="CSV kết quả")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if not 0.0 < args.nguong <= 1.0:
            raise InputError("--nguong phải trong (0, 1]")
        cau = read_cau(args.cau)
        train = read_train(args.train)
        exact, near = find_dups(cau, train, None if args.no_embed else args.embed_url, args.nguong)
        write_csv([*exact, *near], args.out)
    except InputError as e:
        print(f"Lỗi đầu vào: {e}", file=sys.stderr)
        return 2
    print(_summary(len(cau), exact, near, not args.no_embed, args.nguong, args.out))
    return 3 if exact or near else 0


if __name__ == "__main__":
    sys.exit(main())
