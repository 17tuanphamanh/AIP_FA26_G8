"""RQ4 (DA10) — đánh giá các phương án chặn prompt injection của B2, dùng lại code trên tag `v1.0-freeze`.

Backend và ml-service cùng tên gói `app` nên KHÔNG chạy chung một tiến trình (như `b2_tau_select.py`). Mỗi lớp chạy một
lệnh riêng, ghi JSONL; lệnh `ghep` (thuần) ghép thành quyết định từng phương án. Thời gian một câu = tổng thời gian các lớp
câu đó THỰC SỰ đi qua (regex → model → LLM), đo từng câu.

Lệnh (chạy ở gốc repo/worktree):

  # 1. L0 + L1 thật (_pii_fake.redact = RegexPrivacyGuard) + regex L2 thật + bản thay nhãn che cho model — cần backend
  PYTHONPATH=backend uv run python scripts/eval/rq4_danh_gia.py chuan-bi DATA.csv .verify/rq4/DATA.prep.jsonl
  # 2. Chấm model (CPU) — v3/v4 bằng MÃ ml-service (check_guard + classify_sync); pg2 bằng transformers
  PYTHONPATH=ml_service uv run --group ml python scripts/eval/rq4_danh_gia.py cham-model PREP OUT.diem.jsonl \
      --model v3 --model-dir ml_models/injection-clf/v3-seed123 --model-sha <sha> --manifest-sha <sha>
  PYTHONPATH=ml_service uv run --group ml python scripts/eval/rq4_danh_gia.py cham-model PREP OUT.diem.jsonl \
      --model pg2 --model-dir <thư mục Llama-Prompt-Guard-2-86M>
  # 3. Chọn ngưỡng — CHỈ trên validation, ghi file TRƯỚC khi chạy test
  python scripts/eval/rq4_danh_gia.py chon-nguong --kieu block|hai-nguong --prep VAL.prep --diem VAL.diem --ra N.json
  python scripts/eval/rq4_danh_gia.py chon-nguong --kieu review-d52 --prep VAL.prep --diem VAL.diem --llm VAL.llm --ra N.json
  # 3b. Gộp mọi ngưỡng đã chọn → thresholds.json (+ SHA-256) gửi TA TRƯỚC khi chạy test; từ chối ghi đè
  python scripts/eval/rq4_danh_gia.py gop-nguong --ra thresholds.json --nguong model:v3=N1.json --nguong tang5b:v3=N2.json
  # 5a v3 (D-70, TA 30/10): τ_review 0,50 = D-52 chạy lại trên v2.7 — ngưỡng cho sẵn kèm nguồn; 0,9999 làm độ nhạy
  python scripts/eval/rq4_danh_gia.py chon-nguong --kieu co-dinh --model v3 --tau-review 0.50 --nguon "D-70 ..." --ra N3.json
  python scripts/eval/rq4_danh_gia.py gop-nguong ... --nguong tang5a:v3=N3.json --nguong "tang5a:v3#do-nhay-0.9999=N4.json"
  # 4. Câu nào cần LLM (5b: vùng giữa hai ngưỡng hoặc model lỗi)
  python scripts/eval/rq4_danh_gia.py can-llm --phuong-an tang5b:v3 --prep P --diem D --nguong N --ra ids.txt
  # 5. Gọi LLM b02_injection_judge đúng đường chạy thật (_judge_runtime, không cache, không dự phòng) — MỖI phương án
  #    một lượt riêng; chạy tiếp được (id đã có bỏ qua)
  PYTHONPATH=backend uv run python scripts/eval/rq4_danh_gia.py goi-llm PREP OUT.llm.jsonl --phuong-an llm \
      --max-calls 400 --max-usd 2
  # 6. Ghép → CSV 7 cột (+ ket_cuc) + manifest; 7. tổng hợp
  PYTHONPATH=backend python scripts/eval/rq4_danh_gia.py ghep --phuong-an tang5a:v3 --prep P --diem D --llm L \
      --nguong N --ra KQ.csv
  python scripts/eval/rq4_danh_gia.py tong-hop --ket-qua KQ.csv --prep P

Phương án: `regex` (1) · `model:pg2|v3|v4` (2, 3) · `llm` (4) · `tang5a:v3|v4` (5a, đúng `review` trên tag) ·
`tang5b:v3|v4` (5b, hai ngưỡng B02 §5 — logic `classifier_shortcut` chế độ `active`, ngưỡng chọn trên validation).

Quyết định 5a/4/5b sau LLM gọi `after_judge` THẬT (`backend/app/guard/b2_review.py`). E1 (5a: LLM nói không mà p ≥ τ
hoặc too_many_windows) ghi `ket_cuc=E1`, `nhan_du_doan=tan_cong` — TA 30/10: E1 tính là "giữ" (báo recall cả E0 lẫn
E0 ∪ E1). Mọi phương án có model chấm chữ đã thay nhãn che (`text_model`), LLM nhận chữ sau L1 (`text_l1`) — TA 30/10.
Mọi ngưỡng (PG2, v3, v4; τ_review 5a, τ_block/τ_pass 5b) chọn trên CÙNG validation v2.7 — TA 30/10. File trung gian có chữ chỉ nằm dưới `.verify/` (gitignore). Không in chữ câu nào ra màn hình.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
PHIEN_BAN = "0.3.1"

NHAN_TC, NHAN_BT = "tan_cong", "binh_thuong"
LABEL_CSV = {NHAN_TC: "attack", NHAN_BT: "normal"}
COT_RA = ["id", "phuong_an", "nhan_du_doan", "diem", "thoi_gian_ms", "so_loi_goi_llm", "tang_quyet_dinh", "ket_cuc"]
FPR_TOI_DA = 1 / 30  # TA 30/10: PG2/v3/v4 chạy một mình — chặn nhầm ≤ 1/30 trên CÙNG validation
TOO_MANY_WINDOWS = "too_many_windows"
WARMUP = 3
MODELS = ("pg2", "v3", "v4")
PG2_MAX_LEN = 512  # model card PG2: cửa sổ 512 token; chia đoạn, lấy max (cùng kiểu cắt với ml-service, chồng 32 id)
PG2_STEP = PG2_MAX_LEN - 2 - 32
MAX_WINDOWS = 48  # như ml_service/app/guard.py


# ---- tiện ích ---------------------------------------------------------------------------------------------------------


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: str | Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    meta: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        if isinstance(obj, dict) and "_meta" in obj:
            meta = dict(obj["_meta"])
        else:
            rows.append(obj)
    return meta, rows


def write_jsonl(path: str | Path, meta: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        f.write(json.dumps({"_meta": dict(meta)}, ensure_ascii=False) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_jsonl(path: str | Path, row: Mapping[str, Any]) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def require_verify(path: str | Path) -> Path:
    """File có chữ (đã che) chỉ được nằm dưới `.verify/` (gitignore) — như `b2_tau_select.require_verify_dir`."""
    resolved = Path(path).resolve()
    if not resolved.is_relative_to((REPO / ".verify").resolve()):
        raise SystemExit(f"DỪNG: file có chữ phải nằm dưới {REPO / '.verify'} (gitignore) — nhận {path}")
    return resolved


def doc_csv(path: str | Path) -> list[dict[str, str]]:
    """CSV UTF-8: bắt buộc id, cau, nhan (tan_cong/binh_thuong), template_id; cột thừa (ho, nguoi_viet…) giữ `ho`."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"DỪNG: {path} rỗng")
    thieu = {"id", "cau", "nhan", "template_id"} - set(rows[0])
    if thieu:
        raise SystemExit(f"DỪNG: {path} thiếu cột {sorted(thieu)}")
    ids = [r["id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise SystemExit(f"DỪNG: {path} trùng id")
    sai = sorted({r["nhan"] for r in rows} - set(LABEL_CSV))
    if sai:
        raise SystemExit(f"DỪNG: {path} nhãn lạ {sai} (chỉ nhận {sorted(LABEL_CSV)})")
    if any(not r["template_id"].strip() for r in rows):
        raise SystemExit(f"DỪNG: {path} có dòng thiếu template_id (cần cho bootstrap theo nhóm)")
    return rows


def phan_vi(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def auc(scores: Sequence[float], y: Sequence[int]) -> float:
    """P(điểm câu tấn công > điểm câu thường), hoà = 0,5 (Mann–Whitney, xếp hạng trung bình)."""
    pos, neg = sum(y), len(y) - sum(y)
    if not pos or not neg:
        return float("nan")
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    rank = [0.0] * len(scores)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and scores[order[j + 1]] == scores[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rank[order[k]] = (i + j) / 2 + 1
        i = j + 1
    u = sum(r for r, t in zip(rank, y) if t) - pos * (pos + 1) / 2
    return u / (pos * neg)


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()  # fmt: skip
    except Exception:  # noqa: BLE001
        return None


def thu_vien() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in ("torch", "transformers", "tokenizers", "safetensors", "numpy", "pydantic"):
        mod = sys.modules.get(name)
        out[name] = getattr(mod, "__version__", None) if mod else None
    return out


def moi_truong() -> dict[str, Any]:
    return {"script": "scripts/eval/rq4_danh_gia.py", "phien_ban": PHIEN_BAN, "sha256_script": sha256_file(__file__),
            "git_commit": git_commit(), "python": sys.version.split()[0], "nen_tang": platform.platform(),
            "may": platform.machine(), "cpu": platform.processor() or None, "so_cpu": os.cpu_count(),
            "thoi_diem_utc": datetime.now(UTC).isoformat(timespec="seconds"), "thu_vien": thu_vien()}  # fmt: skip


# ---- 1. chuan-bi (tiến trình backend) ---------------------------------------------------------------------------------


def chuan_bi_rows(items: Sequence[Mapping[str, str]], *, redact: Callable[[str], str],
                  replace: Callable[[str], tuple[str, int]], match: Callable[[str], Any],
                  clock: Callable[[], float] = time.perf_counter) -> list[dict[str, Any]]:  # fmt: skip
    """L0+L1 (`redact`), bản cho model (`replace` = replace_masks), regex L2 (`match`) có đo giờ — mọi phương án nhận
    cùng `text_l1` (TA 30/10 câu 4). Giờ L0–L1 chung cho mọi phương án nên không tính."""
    for it in items[:WARMUP]:  # khởi động (nạp mẫu, biên dịch regex) — không ghi
        match(redact(it["cau"]))
    out = []
    for it in items:
        text_l1 = redact(it["cau"])
        text_model, n = replace(text_l1)
        t0 = clock()
        hit = match(text_l1)
        regex_ms = (clock() - t0) * 1000
        out.append({"id": it["id"], "label": LABEL_CSV[it["nhan"]], "group": it["template_id"], "ho": it.get("ho"),
                    "text_l1": text_l1, "text_model": text_model, "masks_replaced": n,
                    "regex_id": getattr(hit, "id", None), "regex_group": getattr(hit, "group", None),
                    "regex_ms": regex_ms})  # fmt: skip
    return out


def _cmd_chuan_bi(a: argparse.Namespace) -> None:
    out = require_verify(a.ra)
    sys.path.insert(0, str(HERE))
    # _pii_fake.redact = RegexPrivacyGuard thật + config/privacy_patterns.json
    from _pii_fake import redact
    from app.guard.injection import match
    from app.guard.mask_words import replace_masks
    from app.guard.patterns import load_injection_patterns, load_privacy_patterns

    priv = load_privacy_patterns(REPO / "config" / "privacy_patterns.json")
    inj = load_injection_patterns(REPO / "config" / "injection_patterns.json")
    items = doc_csv(a.dau_vao)
    rows = chuan_bi_rows(items, redact=lambda t: redact(t).text, replace=lambda t: replace_masks(t, priv),
                         match=lambda t: match(t, inj))  # fmt: skip
    meta = {"lenh": "chuan-bi", "input_sha256": sha256_file(a.dau_vao), "so_cau": len(rows),
            "privacy_patterns_sha256": sha256_file(REPO / "config" / "privacy_patterns.json"),
            "injection_patterns_sha256": sha256_file(REPO / "config" / "injection_patterns.json"),
            "moi_truong": moi_truong()}  # fmt: skip
    write_jsonl(out, meta, rows)
    print(f"chuan-bi: {len(rows)} câu · khớp regex {sum(r['regex_id'] is not None for r in rows)} · "
          f"đã thay {sum(r['masks_replaced'] for r in rows)} nhãn che → {a.ra}")  # fmt: skip


# ---- 2. cham-model (tiến trình ml-service, nhóm uv `ml`) --------------------------------------------------------------


def cut_windows(ids: Sequence[int], cls_id: int, sep_id: int, body: int, step: int,
                max_windows: int = MAX_WINDOWS) -> list[list[int]]:  # fmt: skip
    """Cắt cửa sổ kiểu ml-service (guard.windows) với thân/bước tuỳ chọn — dùng cho PG2 (512)."""
    count = 1 if len(ids) <= body else 1 + math.ceil((len(ids) - body) / step)
    if count > max_windows:
        raise OverflowError(TOO_MANY_WINDOWS)
    return [[cls_id, *ids[k * step : k * step + body], sep_id] for k in range(count)]


def _softmax(row: Sequence[float]) -> list[float]:
    top = max(row)
    ex = [math.exp(x - top) for x in row]
    s = sum(ex)
    return [e / s for e in ex]


def _pg2_classifier(model_dir: Path, chi_so: int | None = None, revision: str | None = None,
                    nguon_chi_so: str | None = None) -> tuple[Callable[[str], tuple[float, int]], dict[str, Any]]:  # fmt: skip
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True, trust_remote_code=False)
    model = AutoModelForSequenceClassification.from_pretrained(str(model_dir), local_files_only=True,
                                                               use_safetensors=True, trust_remote_code=False)  # fmt: skip
    model.to("cpu").eval()
    labels = {int(k): v for k, v in model.config.id2label.items()}
    hits = [i for i, v in labels.items() if "MALICIOUS" in str(v).upper()]
    if chi_so is not None:  # config.json của PG2 trên HF chỉ có LABEL_0/LABEL_1 — chỉ số phải truyền tường minh kèm nguồn
        if chi_so not in labels or (hits and hits != [chi_so]):
            raise SystemExit(f"DỪNG: --chi-so-tan-cong {chi_so} không hợp lệ với id2label={labels}")
        if not nguon_chi_so:
            raise SystemExit("DỪNG: --chi-so-tan-cong cần --nguon-chi-so (bằng chứng chỉ số lớp tấn công)")
        idx = chi_so
    elif len(hits) == 1:
        idx = hits[0]
    else:
        raise SystemExit(f"DỪNG: không xác định được lớp tấn công của PG2 từ id2label={labels} — truyền --chi-so-tan-cong")
    pad = tok.pad_token_id

    def classify(text: str) -> tuple[float, int]:
        ids = list(tok(text, add_special_tokens=False)["input_ids"])
        wins = cut_windows(ids, tok.cls_token_id, tok.sep_token_id, PG2_MAX_LEN - 2, PG2_STEP)
        width = max(len(w) for w in wins)
        x = torch.tensor([w + [pad] * (width - len(w)) for w in wins])
        m = torch.tensor([[1] * len(w) + [0] * (width - len(w)) for w in wins])
        with torch.no_grad():
            logits = model(input_ids=x, attention_mask=m).logits.tolist()
        return max(_softmax(r)[idx] for r in logits), len(wins)

    info = {"id2label": labels, "chi_so_tan_cong": idx, "nguon_chi_so": nguon_chi_so or "id2label",
            "revision_hf": revision or getattr(model.config, "_commit_hash", None),
            "max_len": PG2_MAX_LEN, "buoc": PG2_STEP,
            "sha256": {p.name: sha256_file(p) for p in sorted(model_dir.glob("*")) if p.is_file()}}  # fmt: skip
    return classify, info


def cham_rows(rows: Sequence[Mapping[str, Any]], classify: Callable[[str], tuple[float, int]],
              clock: Callable[[], float] = time.perf_counter) -> list[dict[str, Any]]:  # fmt: skip
    for r in rows[:WARMUP]:
        with contextlib.suppress(Exception):  # khởi động; lỗi thật được ghi ở vòng đo bên dưới
            classify(str(r["text_model"]))
    out = []
    for r in rows:
        t0 = clock()
        try:
            p, w = classify(str(r["text_model"]))
            err = None
        except Exception as exc:  # noqa: BLE001 — chỉ tên lớp lỗi, không chữ
            p, w = None, None
            name = type(exc).__name__
            err = TOO_MANY_WINDOWS if name == "TooManyWindows" or str(exc) == TOO_MANY_WINDOWS else name
        out.append({"id": r["id"], "p_mal": p, "windows": w, "error": err, "model_ms": (clock() - t0) * 1000})
    return out


def _cmd_cham_model(a: argparse.Namespace) -> None:
    import torch

    torch.set_num_threads(a.threads)
    meta_p, rows = read_jsonl(a.prep)
    if a.model == "pg2":
        classify, info = _pg2_classifier(Path(a.model_dir), a.chi_so_tan_cong, a.revision_hf, a.nguon_chi_so)
    else:
        if not a.model_sha:
            raise SystemExit("DỪNG: v3/v4 cần --model-sha (và --manifest-sha) như ml-service")
        sys.path.insert(0, str(HERE))
        # check_guard + _load_guard + classify_sync của ml-service
        from b2_tau_select import _ml_classifier

        classify, version = _ml_classifier(Path(a.model_dir), a.model_sha, a.manifest_sha,
                                           Path(a.models_root) if a.models_root else None)  # fmt: skip
        info = {"version": version, "model_sha256": a.model_sha.lower(),
                "manifest_sha256": a.manifest_sha.lower() if a.manifest_sha else None}  # fmt: skip
    scored = cham_rows(rows, classify)
    meta = {"lenh": "cham-model", "model": a.model, "model_dir": a.model_dir, "prep_sha256": sha256_file(a.prep),
            "input_sha256": meta_p.get("input_sha256"), "threads": a.threads, "thiet_bi": "cpu",
            "dau_vao_model": "text_model (đã thay nhãn che — TA 30/10)", "model_info": info,
            "moi_truong": moi_truong()}  # fmt: skip
    write_jsonl(a.ra, meta, scored)
    print(f"cham-model {a.model}: {len(scored)} câu · lỗi {sum(1 for s in scored if s['error'])} → {a.ra}")


# ---- 3. chon-nguong (chỉ validation) ----------------------------------------------------------------------------------


def chon_tau_block(scores: Sequence[float], y: Sequence[int], fpr_max: float = FPR_TOI_DA) -> dict[str, Any]:
    """τ NHỎ NHẤT (dự đoán tấn công khi p ≥ τ) có tỉ lệ chặn nhầm ≤ fpr_max → recall lớn nhất."""
    neg, pos = len(y) - sum(y), sum(y)
    if not neg or not pos:
        raise SystemExit("DỪNG: validation cần cả câu tấn công và câu thường")
    for tau in sorted(set(scores)) + [math.inf]:
        fp = sum(1 for s, t in zip(scores, y) if not t and s >= tau)
        if fp / neg <= fpr_max:
            tp = sum(1 for s, t in zip(scores, y) if t and s >= tau)
            return {"tau": tau, "fpr_val": fp / neg, "recall_val": tp / pos, "n_thuong": neg, "n_tan_cong": pos}
    raise AssertionError("τ = +inf luôn thoả")


def chon_tau_pass(scores: Sequence[float], y: Sequence[int], tau_block: float, lot_toi_da: int = 0) -> dict[str, Any]:
    """τ_pass LỚN NHẤT < τ_block có số câu tấn công với p ≤ τ_pass ≤ `lot_toi_da` (B02 §7; TA 30/10: 0 câu lọt, không nới)."""
    for tau in sorted({s for s in scores if s < tau_block}, reverse=True):
        lot = sum(1 for s, t in zip(scores, y) if t and s <= tau)
        if lot <= lot_toi_da:
            return {"tau_pass": tau, "tan_cong_lot_val": lot,
                    "ti_le_khong_goi_llm_val": sum(1 for s in scores if s <= tau or s >= tau_block) / len(scores)}  # fmt: skip
    return {"tau_pass": -math.inf, "tan_cong_lot_val": 0,
            "ti_le_khong_goi_llm_val": sum(1 for s in scores if s >= tau_block) / len(scores)}  # fmt: skip


def join_val(prep: Sequence[Mapping[str, Any]], diem: Sequence[Mapping[str, Any]]) -> tuple[list[float], list[int], int]:
    """Điểm + nhãn của câu chấm được (câu model lỗi bỏ ra, đếm riêng)."""
    by = {d["id"]: d for d in diem}
    s, y, loi = [], [], 0
    for r in prep:
        d = by.get(r["id"])
        if d is None:
            raise SystemExit(f"DỪNG: id {r['id']} có trong prep mà không có điểm")
        if d["p_mal"] is None:
            loi += 1
            continue
        s.append(float(d["p_mal"]))
        y.append(1 if r["label"] == "attack" else 0)
    return s, y, loi


def rows_d52(prep: Sequence[Mapping[str, Any]], diem: Sequence[Mapping[str, Any]],
             llm: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:  # fmt: skip
    """Đầu vào cho `b2_tau_select.select_tau` (D-52 nguyên văn): câu khớp regex dừng ở E0 (judge_no False); LLM lỗi → None."""
    d, j = {x["id"]: x for x in diem}, {x["id"]: x for x in llm}
    out = []
    for r in prep:
        if r["regex_id"] is not None:
            judge_no: bool | None = False
        else:
            jr = j.get(r["id"])
            if jr is None:
                raise SystemExit(f"DỪNG: id {r['id']} không khớp regex mà chưa có kết quả LLM chấm")
            judge_no = None if (jr.get("error") or jr.get("is_attack") is None) else not la_e0(jr)
        out.append({"id": r["id"], "group": r["group"], "label": r["label"], "p_mal": d[r["id"]]["p_mal"],
                    "ml_error": d[r["id"]]["error"], "judge_no": judge_no, "regex_hit": r["regex_id"] is not None})  # fmt: skip
    return out


def _cmd_chon_nguong(a: argparse.Namespace) -> None:
    if a.kieu == "co-dinh":  # τ_review cho sẵn kèm nguồn — D-70 (TA 30/10): 5a v3 = 0,50 (D-52 chạy lại trên v2.7)
        if a.tau_review is None or not a.nguon or not a.model:
            raise SystemExit("DỪNG: co-dinh cần --model, --tau-review và --nguon (vd \"D-70, TA 30/10\")")
        kq0 = {"kieu": "co-dinh", "model": a.model, "tau_review": a.tau_review, "nguon": a.nguon,
               "moi_truong": moi_truong()}  # fmt: skip
        Path(a.ra).parent.mkdir(parents=True, exist_ok=True)
        Path(a.ra).write_text(json.dumps(kq0, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"chon-nguong co-dinh: tau_review={a.tau_review}")
        return
    if not a.prep or not a.diem:
        raise SystemExit("DỪNG: cần --prep và --diem của VALIDATION")
    meta_p, prep = read_jsonl(a.prep)
    meta_d, diem = read_jsonl(a.diem)
    if meta_d.get("prep_sha256") != sha256_file(a.prep):
        raise SystemExit("DỪNG: file điểm không chấm từ đúng file prep này")
    kq: dict[str, Any] = {"kieu": a.kieu, "model": meta_d.get("model"),
                          "validation": {"prep": a.prep, "prep_sha256": sha256_file(a.prep),
                                         "input_sha256": meta_p.get("input_sha256"), "so_cau": len(prep)},
                          "diem_sha256": sha256_file(a.diem)}  # fmt: skip
    if a.kieu in ("block", "hai-nguong"):
        s, y, loi = join_val(prep, diem)
        kq["auc_val"] = auc(s, y)
        kq["bo_qua_model_loi"] = loi
        blk = chon_tau_block(s, y, a.fpr_toi_da)
        kq["tau_block"] = blk["tau"]
        kq["chi_tiet_block"] = blk
        kq["tieu_chi"] = {"tau_block": f"nhỏ nhất có chặn nhầm ≤ {a.fpr_toi_da:.6f} trên validation (p ≥ τ → tấn công)"}
        if a.kieu == "hai-nguong":
            ps = chon_tau_pass(s, y, blk["tau"], a.lot_toi_da)
            kq["tau_pass"] = ps["tau_pass"]
            kq["chi_tiet_pass"] = ps
            kq["tieu_chi"]["tau_pass"] = f"lớn nhất < τ_block có số câu tấn công p ≤ τ_pass ≤ {a.lot_toi_da}"
    else:  # review-d52
        if not a.llm:
            raise SystemExit("DỪNG: review-d52 cần --llm (kết quả LLM chấm trên validation)")
        sys.path.insert(0, str(HERE))
        from b2_tau_select import RULE, select_tau

        _, llm = read_jsonl(a.llm) if _has_meta(a.llm) else ({}, _read_plain(a.llm))
        sel = select_tau(rows_d52(prep, diem, llm))
        kq.update(tau_review=sel["tau_review"], d52=sel, tieu_chi={"tau_review": RULE}, llm_sha256=sha256_file(a.llm))
    kq["moi_truong"] = moi_truong()
    Path(a.ra).parent.mkdir(parents=True, exist_ok=True)
    Path(a.ra).write_text(json.dumps(kq, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"chon-nguong {a.kieu}: " + ", ".join(f"{k}={kq[k]}" for k in ("tau_block", "tau_pass", "tau_review") if k in kq))


# ---- 3b. gop-nguong ---------------------------------------------------------------------------------------------------

CAN_TAU = {"model:": ("tau_block",), "tang5a:": ("tau_review",), "tang5b:": ("tau_block", "tau_pass")}


def gop_nguong(items: Sequence[tuple[str, str]], validation_sha: str | None = None) -> dict[str, Any]:
    """Gộp các file `chon-nguong` thành một bản ghi cố định (gửi TA trước test). Mọi file chọn ngưỡng phải từ CÙNG
    validation. Ngưỡng cho sẵn (`co-dinh`) chỉ nhận cho 5a và phải ghi nguồn (D-70). Tên `PA#nhan` = bản độ nhạy."""
    if not items:
        raise SystemExit("DỪNG: cần ít nhất một --nguong PHUONG_AN=FILE")
    out: dict[str, Any] = {}
    nguon_val: set[str] = set()
    for pa, path in items:
        goc, _, nhan = pa.partition("#")
        if "#" in pa and not nhan:
            raise SystemExit(f"DỪNG: {pa}: thiếu nhãn sau #")
        m = model_cua(goc)
        need = next((v for k, v in CAN_TAU.items() if goc.startswith(k)), None)
        if m is None or need is None:
            raise SystemExit(f"DỪNG: {pa} không cần ngưỡng (chỉ model:/tang5a:/tang5b:)")
        if pa in out:
            raise SystemExit(f"DỪNG: {pa} xuất hiện hai lần")
        ng = json.loads(Path(path).read_text(encoding="utf-8"))
        co_dinh = ng.get("kieu") == "co-dinh"
        if co_dinh and (not goc.startswith("tang5a:") or not ng.get("nguon")):
            raise SystemExit(f"DỪNG: {path}: ngưỡng cho sẵn chỉ nhận cho tang5a và phải có nguồn (D-70)")
        if ng.get("model") != m:
            raise SystemExit(f"DỪNG: {path} chọn cho model {ng.get('model')}, không phải {m}")
        thieu = [t for t in need if t not in ng]
        if thieu:
            raise SystemExit(f"DỪNG: {path} thiếu {thieu} cho {pa}")
        val = (ng.get("validation") or {}).get("input_sha256")
        if not co_dinh:
            if not val:
                raise SystemExit(f"DỪNG: {path} không ghi SHA-256 validation")
            nguon_val.add(val)
        out[pa] = {"file": path, "sha256": sha256_file(path), "kieu": ng["kieu"], "model": m, "nguon": ng.get("nguon"),
                   "diem_sha256": ng.get("diem_sha256"), "llm_sha256": ng.get("llm_sha256"),
                   "auc_val": ng.get("auc_val"), "tieu_chi": ng.get("tieu_chi")} | {t: ng[t] for t in need}  # fmt: skip
    if len(nguon_val) > 1:
        raise SystemExit(f"DỪNG: các file ngưỡng chọn trên {len(nguon_val)} validation khác nhau")
    val = next(iter(nguon_val), None)
    if validation_sha and val is not None and val != validation_sha.lower():
        raise SystemExit(f"DỪNG: validation {val[:12]}… khác --validation-sha {validation_sha[:12]}…")
    return {"loai": "thresholds RQ4 (DA10)", "chon_tren": "chỉ validation — chưa chạy test", "validation_input_sha256": val,
            "phuong_an": out, "moi_truong": moi_truong()}  # fmt: skip


def _cmd_gop_nguong(a: argparse.Namespace) -> None:
    ra = Path(a.ra)
    if ra.exists():
        raise SystemExit(f"DỪNG: {ra} đã có — ngưỡng đã gửi TA không ghi đè (dùng tên mới)")
    items = []
    for x in a.nguong:
        pa, sep, path = x.partition("=")
        if not sep or not path:
            raise SystemExit(f"DỪNG: --nguong cần dạng PHUONG_AN=FILE, nhận {x!r}")
        items.append((pa, path))
    kq = gop_nguong(items, a.validation_sha)
    ra.parent.mkdir(parents=True, exist_ok=True)
    ra.write_text(json.dumps(kq, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    for pa, v in kq["phuong_an"].items():
        print(f"  {pa}: " + ", ".join(f"{t}={v[t]}" for t in ("tau_block", "tau_pass", "tau_review") if t in v))
    print(f"gop-nguong: {len(kq['phuong_an'])} phương án → {ra}\nsha256 {sha256_file(ra)}")


def _has_meta(path: str) -> bool:
    with open(path, encoding="utf-8") as f:
        first = f.readline()
    return '"_meta"' in first


def _read_plain(path: str) -> list[dict[str, Any]]:
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]


# ---- quyết định (dùng after_judge THẬT) -------------------------------------------------------------------------------


def la_e0(judge: Mapping[str, Any]) -> bool:
    """E0 của LLM chấm = is_attack HOẶC category ≠ none (bảng 4.2 #2, #3; như b2_judge_compare.is_e0)."""
    return bool(judge["is_attack"]) or judge["category"] != "none"


def _b2_review() -> Any:
    from app.guard import b2_review

    return b2_review


def model_cua(pa: str) -> str | None:
    if pa.startswith(("model:", "tang5a:", "tang5b:")):
        m = pa.split(":", 1)[1]
        if m not in MODELS or (pa.startswith("tang") and m == "pg2"):
            raise SystemExit(f"DỪNG: phương án lạ {pa}")
        return m
    if pa in ("regex", "llm"):
        return None
    raise SystemExit(f"DỪNG: phương án lạ {pa}")


def can_llm(pa: str, r: Mapping[str, Any], d: Mapping[str, Any] | None, ng: Mapping[str, Any] | None) -> bool:
    """Câu có đi tới L4 không (để biết gọi LLM cho câu nào)."""
    if pa == "llm":
        return True
    if pa.startswith("tang5a:"):
        return r["regex_id"] is None
    if pa.startswith("tang5b:"):
        if r["regex_id"] is not None:
            return False
        p = None if d is None else d["p_mal"]
        if p is None:  # L3 lỗi → xuống L4 (không mở cửa)
            return True
        return float(ng["tau_pass"]) < p < float(ng["tau_block"])  # type: ignore[index]
    return False


def quyet_dinh(pa: str, r: Mapping[str, Any], d: Mapping[str, Any] | None, j: Mapping[str, Any] | None,
               ng: Mapping[str, Any] | None, review: Any) -> dict[str, Any]:  # fmt: skip
    """→ {nhan_du_doan, diem, thoi_gian_ms, so_loi_goi_llm, tang_quyet_dinh, ket_cuc}."""
    tc = lambda ok: NHAN_TC if ok else NHAN_BT
    p = None if d is None else d["p_mal"]
    model_ms = 0.0 if d is None else float(d["model_ms"])
    if pa == "regex":
        hit = r["regex_id"] is not None
        return {"nhan_du_doan": tc(hit), "diem": 1.0 if hit else 0.0, "thoi_gian_ms": r["regex_ms"],
                "so_loi_goi_llm": 0, "tang_quyet_dinh": "", "ket_cuc": "E0" if hit else "pass"}  # fmt: skip
    if pa.startswith("model:"):
        if d is None:
            raise SystemExit(f"DỪNG: thiếu điểm cho {r['id']}")
        if p is None:  # model một mình không có lớp sau: too_many_windows coi là đáng ngờ (như bảng 4.2 #5)
            if d["error"] != TOO_MANY_WINDOWS:
                raise SystemExit(f"DỪNG: model lỗi {d['error']} ở {r['id']} — chấm lại")
            return {"nhan_du_doan": NHAN_TC, "diem": None, "thoi_gian_ms": model_ms, "so_loi_goi_llm": 0,
                    "tang_quyet_dinh": "", "ket_cuc": "E0"}  # fmt: skip
        hit = p >= float(ng["tau_block"])  # type: ignore[index]
        return {"nhan_du_doan": tc(hit), "diem": p, "thoi_gian_ms": model_ms, "so_loi_goi_llm": 0,
                "tang_quyet_dinh": "", "ket_cuc": "E0" if hit else "pass"}  # fmt: skip
    # tầng và chỉ-LLM
    regex_ms = r["regex_ms"] if pa.startswith("tang") else 0.0
    if pa.startswith("tang") and r["regex_id"] is not None:
        return {"nhan_du_doan": NHAN_TC, "diem": 1.0, "thoi_gian_ms": regex_ms, "so_loi_goi_llm": 0,
                "tang_quyet_dinh": "regex", "ket_cuc": "E0"}  # fmt: skip
    if pa.startswith("tang5b:") and p is not None:
        if p >= float(ng["tau_block"]):  # type: ignore[index]
            return {"nhan_du_doan": NHAN_TC, "diem": p, "thoi_gian_ms": regex_ms + model_ms, "so_loi_goi_llm": 0,
                    "tang_quyet_dinh": "model", "ket_cuc": "E0"}  # fmt: skip
        if p <= float(ng["tau_pass"]):  # type: ignore[index]
            return {"nhan_du_doan": NHAN_BT, "diem": p, "thoi_gian_ms": regex_ms + model_ms, "so_loi_goi_llm": 0,
                    "tang_quyet_dinh": "model", "ket_cuc": "pass"}  # fmt: skip
    if j is None:
        raise SystemExit(f"DỪNG: {pa} cần kết quả LLM cho {r['id']} — chạy goi-llm")
    if j.get("error") or j.get("is_attack") is None:
        raise SystemExit(f"DỪNG: LLM lỗi ({j.get('error')}) ở {r['id']} — chạy lại goi-llm cho câu này")
    mode = "review" if pa.startswith("tang5a:") else ("active" if pa.startswith("tang5b:") else "shadow")
    tau = float(ng["tau_review"]) if mode == "review" else None  # type: ignore[index]
    v = review.after_judge(mode, p_mal=p if mode != "shadow" else None, ml_error=d["error"] if d and mode == "review" else None,
                           is_attack=bool(j["is_attack"]), category=str(j["category"]), tau=tau)  # fmt: skip
    t = regex_ms + (model_ms if pa.startswith("tang") else 0.0) + float(j["latency_ms"])
    ket = v.outcome
    tang = {"classifier": "model", "llm": "llm"}[v.layer] if pa.startswith("tang") else ""
    diem = p if (p is not None and pa.startswith("tang")) else (1.0 if ket == "E0" else 0.0)
    return {"nhan_du_doan": NHAN_BT if ket == "pass" else NHAN_TC, "diem": diem, "thoi_gian_ms": t,
            "so_loi_goi_llm": 1, "tang_quyet_dinh": tang, "ket_cuc": ket}  # fmt: skip


def _load_inputs(a: argparse.Namespace) -> tuple[dict, list, dict, dict, dict | None]:
    meta_p, prep = read_jsonl(a.prep)
    diem: dict[str, Any] = {}
    llm: dict[str, Any] = {}
    if getattr(a, "diem", None):
        meta_d, rows = read_jsonl(a.diem)
        if meta_d.get("prep_sha256") != sha256_file(a.prep):
            raise SystemExit("DỪNG: file điểm không chấm từ đúng file prep này")
        if model_cua(a.phuong_an) not in (None, meta_d.get("model")):
            raise SystemExit(f"DỪNG: file điểm của model {meta_d.get('model')} ≠ phương án {a.phuong_an}")
        diem = {x["id"]: x for x in rows}
    if getattr(a, "llm", None):
        meta_l, rows = read_jsonl(a.llm)
        if meta_l.get("phuong_an") != a.phuong_an:
            raise SystemExit(f"DỪNG: file LLM của lượt {meta_l.get('phuong_an')} ≠ {a.phuong_an} (mỗi phương án gọi riêng)")
        llm = {x["id"]: x for x in rows}
    ng = json.loads(Path(a.nguong).read_text(encoding="utf-8")) if getattr(a, "nguong", None) else None
    return meta_p, prep, diem, llm, ng


def _cmd_can_llm(a: argparse.Namespace) -> None:
    _, prep, diem, _, ng = _load_inputs(a)
    if a.phuong_an.startswith("tang5b:") and (ng is None or not diem):
        raise SystemExit("DỪNG: tang5b cần --diem và --nguong (hai ngưỡng)")
    ids = [r["id"] for r in prep if can_llm(a.phuong_an, r, diem.get(r["id"]), ng)]
    Path(a.ra).write_text("\n".join(ids) + ("\n" if ids else ""), encoding="utf-8")
    print(f"can-llm {a.phuong_an}: {len(ids)}/{len(prep)} câu cần LLM → {a.ra}")


# ---- 5. goi-llm (tiến trình backend; TỐN TIỀN) -------------------------------------------------------------------------


async def _goi(judge: Any, todo: Sequence[Mapping[str, Any]], out: Path) -> int:
    n = 0
    try:
        for r in todo:  # tuần tự: đo độ trễ từng câu không bị lẫn lời gọi song song
            res = await judge.one(str(r["text_l1"]))  # L4 nhận bản L1 CHƯA thay nhãn (như node)
            append_jsonl(out, {"id": r["id"], **res})
            n += 1
            if n % 25 == 0:
                print(f"… {n}/{len(todo)} lời gọi")
    finally:
        await judge.aclose()
    return n


def _cmd_goi_llm(a: argparse.Namespace) -> None:
    model_cua(a.phuong_an)
    if a.phuong_an == "regex" or a.phuong_an.startswith("model:"):
        raise SystemExit("DỪNG: phương án này không gọi LLM")
    meta_p, prep = read_jsonl(a.prep)
    if a.ids_file:
        want = {x.strip() for x in Path(a.ids_file).read_text(encoding="utf-8").splitlines() if x.strip()}
    elif a.phuong_an.startswith("tang5b:"):
        raise SystemExit("DỪNG: tang5b cần --ids-file từ lệnh can-llm")
    else:
        want = {r["id"] for r in prep if can_llm(a.phuong_an, r, None, None)}
    out = Path(a.ra)
    if out.exists():
        meta_o, done_rows = read_jsonl(out)
        if meta_o.get("phuong_an") != a.phuong_an or meta_o.get("prep_sha256") != sha256_file(a.prep):
            raise SystemExit("DỪNG: file ra đã có của lượt/prep khác — dùng tên file khác")
        done = {x["id"] for x in done_rows if not x.get("error") and x.get("is_attack") is not None}
        if len(done) != len({x["id"] for x in done_rows}):  # dòng lỗi: ghi lại file chỉ giữ dòng tốt, gọi lại câu lỗi
            write_jsonl(out, meta_o, [x for x in done_rows if x["id"] in done])
    else:
        done = set()
    todo = [r for r in prep if r["id"] in want and r["id"] not in done][: a.max_calls]
    print(f"goi-llm {a.phuong_an}: cần {len(want)} · đã có {len(want & done)} · lượt này gọi {len(todo)}")
    if a.dry_run or not todo:
        return
    sys.path.insert(0, str(HERE))
    from _judge_runtime import TargetError, build_judge, environ, load_target

    env = environ()
    try:
        target = load_target(a.target, env)
        judge = build_judge(target, env, max_usd=a.max_usd)
    except TargetError as exc:
        raise SystemExit(f"DỪNG: {exc}") from None
    if not out.exists():
        write_jsonl(out, {"lenh": "goi-llm", "phuong_an": a.phuong_an, "prep_sha256": sha256_file(a.prep),
                          "input_sha256": meta_p.get("input_sha256"), "target": a.target, "model": target.model,
                          "prompt": "b02_injection_judge", "cache": "bypass", "du_phong": "không",
                          "goi": "tuần tự", "moi_truong": moi_truong()}, [])  # fmt: skip
    n = asyncio.run(_goi(judge, todo, out))
    _, rows = read_jsonl(out)
    print(f"xong {n} lời gọi · lỗi trong file {sum(1 for x in rows if x.get('error'))} → {out}")


# ---- 6. ghep, 7. tong-hop ---------------------------------------------------------------------------------------------


def ghep_rows(pa: str, prep: Sequence[Mapping[str, Any]], diem: Mapping[str, Any], llm: Mapping[str, Any],
              ng: Mapping[str, Any] | None, review: Any) -> list[dict[str, Any]]:  # fmt: skip
    m = model_cua(pa)
    if pa.startswith(("model:", "tang")) and not diem:
        raise SystemExit(f"DỪNG: {pa} cần --diem của model {m}")
    need = {"model:": "tau_block", "tang5a:": "tau_review", "tang5b:": "tau_pass"}
    for k, v in need.items():
        if pa.startswith(k) and (ng is None or v not in ng):
            raise SystemExit(f"DỪNG: {pa} cần --nguong có {v} (chọn trên validation)")
    out = []
    for r in prep:
        d = diem.get(r["id"]) if m else None
        q = quyet_dinh(pa, r, d, llm.get(r["id"]), ng, review)
        out.append({"id": r["id"], "phuong_an": pa, "nhan_du_doan": q["nhan_du_doan"],
                    "diem": "" if q["diem"] is None else f"{float(q['diem']):.6f}",
                    "thoi_gian_ms": f"{float(q['thoi_gian_ms']):.3f}", "so_loi_goi_llm": q["so_loi_goi_llm"],
                    "tang_quyet_dinh": q["tang_quyet_dinh"], "ket_cuc": q["ket_cuc"]})  # fmt: skip
    return out


def _cmd_ghep(a: argparse.Namespace) -> None:
    meta_p, prep, diem, llm, ng = _load_inputs(a)
    review = _b2_review()
    rows = ghep_rows(a.phuong_an, prep, diem, llm, ng, review)
    with open(a.ra, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COT_RA if a.ket_cuc else COT_RA[:-1], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    man = {"phuong_an": a.phuong_an, "input_sha256": meta_p.get("input_sha256"), "prep_sha256": sha256_file(a.prep),
           "diem_sha256": sha256_file(a.diem) if a.diem else None, "llm_sha256": sha256_file(a.llm) if a.llm else None,
           "nguong": ({"file": a.nguong, "sha256": sha256_file(a.nguong)} | {k: ng[k] for k in ng if k.startswith("tau")})
           if ng else None,
           "thoi_gian_ms": "tổng thời gian các lớp câu đi qua (regex_ms + model_ms + latency_ms LLM); L0–L1 không tính",
           "ket_qua": {"file": a.ra, "sha256": sha256_file(a.ra), "so_cau": len(rows)}, "moi_truong": moi_truong()}  # fmt: skip
    Path(a.ra).with_suffix(".manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=2, default=str),
                                                         encoding="utf-8")  # fmt: skip
    print(f"ghep {a.phuong_an}: {len(rows)} câu → {a.ra} (+ manifest)")


def tong_hop(rows: Sequence[Mapping[str, str]], label: Mapping[str, str]) -> dict[str, Any]:
    y = [1 if label[r["id"]] == "attack" else 0 for r in rows]
    du = [1 if r["nhan_du_doan"] == NHAN_TC else 0 for r in rows]
    pos, neg = sum(y), len(y) - sum(y)
    ms = [float(r["thoi_gian_ms"]) for r in rows]
    out: dict[str, Any] = {"so_cau": len(y), "so_tan_cong": pos, "so_thuong": neg,
                           "recall": sum(a and b for a, b in zip(y, du)) / pos if pos else None,
                           "ti_le_chan_nham": sum((not a) and b for a, b in zip(y, du)) / neg if neg else None,
                           "p50_ms": phan_vi(ms, 0.5), "p95_ms": phan_vi(ms, 0.95),
                           "loi_goi_llm_tren_100_cau": 100 * sum(int(r["so_loi_goi_llm"]) for r in rows) / len(y)}  # fmt: skip
    if "ket_cuc" in rows[0]:
        e0 = [r["ket_cuc"] == "E0" for r in rows]
        out["recall_chi_E0"] = sum(a and b for a, b in zip(y, e0)) / pos if pos else None
        out["E1_thua"] = sum((not a) and r["ket_cuc"] == "E1" for a, r in zip(y, rows)) / neg if neg else None
    if all(r["diem"] != "" for r in rows):
        out["auc"] = auc([float(r["diem"]) for r in rows], y)
    return out


def _cmd_tong_hop(a: argparse.Namespace) -> None:
    with open(a.ket_qua, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    _, prep = read_jsonl(a.prep)
    label = {r["id"]: r["label"] for r in prep}
    print(json.dumps(tong_hop(rows, label), ensure_ascii=False, indent=2))


# ---- CLI --------------------------------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="rq4_danh_gia", description="RQ4 — đánh giá phương án chặn injection (DA10)")
    sp = p.add_subparsers(dest="lenh", required=True)
    c = sp.add_parser("chuan-bi")
    c.add_argument("dau_vao")
    c.add_argument("ra")
    c.set_defaults(f=_cmd_chuan_bi)
    m = sp.add_parser("cham-model")
    m.add_argument("prep")
    m.add_argument("ra")
    m.add_argument("--model", choices=MODELS, required=True)
    m.add_argument("--model-dir", required=True)
    m.add_argument("--model-sha")
    m.add_argument("--manifest-sha")
    m.add_argument("--models-root")
    m.add_argument("--threads", type=int, default=4)
    m.add_argument("--chi-so-tan-cong", type=int, help="pg2: chỉ số lớp tấn công khi id2label không ghi rõ")
    m.add_argument("--nguon-chi-so", help="pg2: bằng chứng cho --chi-so-tan-cong (ghi vào manifest)")
    m.add_argument("--revision-hf", help="pg2: commit hash trên Hugging Face (ghi vào manifest)")
    m.set_defaults(f=_cmd_cham_model)
    n = sp.add_parser("chon-nguong")
    n.add_argument("--kieu", choices=("block", "hai-nguong", "review-d52", "co-dinh"), required=True)
    n.add_argument("--prep")
    n.add_argument("--diem")
    n.add_argument("--tau-review", type=float)
    n.add_argument("--model", choices=MODELS, help="co-dinh: model của ngưỡng cho sẵn")
    n.add_argument("--nguon")
    n.add_argument("--llm")
    n.add_argument("--fpr-toi-da", type=float, default=FPR_TOI_DA)
    n.add_argument("--lot-toi-da", type=int, default=0)
    n.add_argument("--ra", required=True)
    n.set_defaults(f=_cmd_chon_nguong)
    gn = sp.add_parser("gop-nguong")
    gn.add_argument("--nguong", action="append", required=True, help="PHUONG_AN=FILE, vd tang5b:v4=nguong.v4.5b.json")
    gn.add_argument("--validation-sha", help="SHA-256 file validation mong đợi (vd val_chung_rq4.csv)")
    gn.add_argument("--ra", required=True)
    gn.set_defaults(f=_cmd_gop_nguong)
    k = sp.add_parser("can-llm")
    for arg in ("--phuong-an", "--prep", "--ra"):
        k.add_argument(arg, required=True)
    k.add_argument("--diem")
    k.add_argument("--nguong")
    k.set_defaults(f=_cmd_can_llm)
    g = sp.add_parser("goi-llm")
    g.add_argument("prep")
    g.add_argument("ra")
    g.add_argument("--phuong-an", required=True)
    g.add_argument("--ids-file")
    g.add_argument("--target", default="deepseek")
    g.add_argument("--max-calls", type=int, required=True)
    g.add_argument("--max-usd", type=float, required=True)
    g.add_argument("--dry-run", action="store_true")
    g.set_defaults(f=_cmd_goi_llm)
    h = sp.add_parser("ghep")
    for arg in ("--phuong-an", "--prep", "--ra"):
        h.add_argument(arg, required=True)
    h.add_argument("--diem")
    h.add_argument("--llm")
    h.add_argument("--nguong")
    h.add_argument("--khong-ket-cuc", dest="ket_cuc", action="store_false", help="chỉ 7 cột đã chốt với Dương")
    h.set_defaults(f=_cmd_ghep)
    t = sp.add_parser("tong-hop")
    t.add_argument("--ket-qua", required=True)
    t.add_argument("--prep", required=True)
    t.set_defaults(f=_cmd_tong_hop)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
