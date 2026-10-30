"""RQ4 (DA10) — fine-tune `injection-clf` v4 = dữ liệu huấn luyện v3 + tập train RQ4 mới, ĐÚNG công thức v3.

Công thức v3 lấy từ `prompt-injection-finetune-v3.ipynb` của Dương (nhận 30/10, đã đọc toàn bộ code + output kỹ thuật):
Kaggle Tesla T4, transformers 5.13.1, `FacebookAI/xlm-roberta-base`, 2 lớp BENIGN/INJECTION, MAX_LENGTH tự chọn = giá trị
nhỏ nhất của [128, 160, 192, 256] ≥ p99 token của train+validation (v3: p99 = 65 → 128), lr 2e-5, 4 epoch, batch 16
(eval 32), weight decay 0,01, warmup 10 % tuyến tính, đánh giá/lưu mỗi epoch, dừng sớm patience 2 theo macro-F1 validation
ở ngưỡng 0,5, nạp checkpoint tốt nhất, fp16 trên GPU, seed_everything + cudnn deterministic. KHÔNG tăng cường dữ liệu, KHÔNG
tiền xử lý văn bản (train trên chữ gốc). Khác v3 duy nhất: dữ liệu (v3 + RQ4 mới), 1 seed 123 (TA 30/10 câu 7), KHÔNG có tập
test nào (script không nhận đường dẫn test).

Ba lệnh:

  # 1. CPU, thư viện chuẩn: ghép dữ liệu, tách validation từ train RQ4 THEO template_id (tỉ lệ CHỜ TA chốt)
  python training/injection/fine_tune_v4.py chuan-bi --v3-train train.csv --v3-val validation.csv \
      --rq4-train rq4_train.csv --ti-le-val 0.2 --ra DIR
  python training/injection/fine_tune_v4.py chuan-bi --v3-train train.csv --v3-val validation.csv --khong-rq4 --ra DIR
      # ↑ tái lập v3 (kiểm script): seed 123 phải ra macro-F1 validation ≈ 0,9494 như notebook v3
  # 2. Kaggle GPU T4 (%pip install -q --upgrade "transformers==5.13.1" datasets accelerate scikit-learn safetensors)
  python fine_tune_v4.py train --du-lieu DIR --ra OUT
  # 3. CPU: đóng gói đúng chuẩn ml-service (guard.check_guard): bỏ file pickle, id2label có INJECTION, MANIFEST.sha256
  python training/injection/fine_tune_v4.py dong-goi --model OUT/final_model --ra ml_models_ngoai_repo/injection-clf/v4-seed123 \
      [--thresholds nguong.json]

`chuan-bi` ghi `v4_train.csv`, `v4_val.csv` (lược đồ v3 tối thiểu cho `train`) và `val_chung_rq4.csv` (lược đồ RQ4
`id, ho, template_id, cau, nhan`) — validation CHUNG để chọn ngưỡng PG2/v3/v4 bằng `scripts/eval/rq4_danh_gia.py`.
Không in chữ câu nào. Model v4 KHÔNG vào repo (giao qua Drive kèm SHA-256).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import shutil
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

PHIEN_BAN = "0.1.1"
SEED = 123
TRANSFORMERS_V3 = "5.13.1"
MODEL_NAME = "FacebookAI/xlm-roberta-base"
ID2LABEL = {0: "BENIGN", 1: "INJECTION"}
LABEL2ID = {v: k for k, v in ID2LABEL.items()}
RQ4_LABEL = {"tan_cong": 1, "binh_thuong": 0}
MAX_LENGTH_CANDIDATES = (128, 160, 192, 256)
ML_SERVICE_MAX_LENGTH = 128  # ml_service/app/guard.py: thân 126 + cls + sep — model khác 128 sẽ bị chấm sai cửa sổ
HYPER = {  # nguyên văn ô 6 của notebook v3
    "learning_rate": 2e-5, "num_train_epochs": 4, "per_device_train_batch_size": 16, "per_device_eval_batch_size": 32,
    "weight_decay": 0.01, "gradient_accumulation_steps": 1, "warmup_ratio": 0.10, "lr_scheduler_type": "linear",
    "early_stopping_patience": 2, "metric_for_best_model": "macro_f1", "threshold": 0.50, "logging_steps": 50,
    "save_total_limit": 2, "dataloader_num_workers": 2,
}  # fmt: skip
V4_COLS = ["id", "text", "label", "label_name", "semantic_group_id", "family_id", "nguon"]
RQ4_COLS = ["id", "ho", "template_id", "cau", "nhan"]
FORBIDDEN_SUFFIXES = {".bin", ".pt", ".pth", ".pkl", ".pickle", ".ckpt", ".py"}  # như ml_service/app/guard.py
REQUIRED_FILES = ("model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json")
MANIFEST_FILE = "MANIFEST.sha256"


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def doc_csv(path: str | Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as f:  # file v3 có BOM
        return list(csv.DictReader(f))


def ghi_csv(path: Path, rows: Sequence[Mapping[str, Any]], cols: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cols), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def norm_basic(s: str) -> str:
    """Như `norm_basic` của notebook v3 (kiểm trùng giữa các tập)."""
    import unicodedata

    return " ".join(unicodedata.normalize("NFKC", str(s).lower()).split())


# ---- 1. chuan-bi ------------------------------------------------------------------------------------------------------


def tu_v3(rows: Sequence[Mapping[str, str]], split: str) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        if r.get("split") != split:
            raise SystemExit(f"DỪNG: dòng {r.get('id')} có split={r.get('split')!r}, mong đợi {split!r}")
        lab = int(r["label"])
        if lab not in ID2LABEL or r["label_name"].strip().upper() != ID2LABEL[lab]:
            raise SystemExit(f"DỪNG: nhãn v3 lạ ở {r.get('id')}")
        out.append({"id": r["id"], "text": r["text"], "label": lab, "label_name": ID2LABEL[lab],
                    "semantic_group_id": r["semantic_group_id"], "family_id": r["family_id"], "nguon": f"v3_{split}"})  # fmt: skip
    return out


def tu_rq4(rows: Sequence[Mapping[str, str]]) -> list[dict[str, Any]]:
    if not rows:
        raise SystemExit("DỪNG: tập train RQ4 rỗng")
    thieu = set(RQ4_COLS) - set(rows[0])
    if thieu:
        raise SystemExit(f"DỪNG: tập train RQ4 thiếu cột {sorted(thieu)}")
    out = []
    for r in rows:
        if r["nhan"] not in RQ4_LABEL:
            raise SystemExit(f"DỪNG: nhãn RQ4 lạ ở {r['id']} (chỉ nhận {sorted(RQ4_LABEL)})")
        if not r["template_id"].strip() or not r["cau"].strip():
            raise SystemExit(f"DỪNG: dòng {r['id']} thiếu template_id hoặc câu")
        lab = RQ4_LABEL[r["nhan"]]
        out.append({"id": f"RQ4_{r['id']}", "text": r["cau"], "label": lab, "label_name": ID2LABEL[lab],
                    "semantic_group_id": f"RQ4_{r['template_id']}", "family_id": r["ho"], "nguon": "rq4_train"})  # fmt: skip
    return out


def tach_theo_template(rows: Sequence[Mapping[str, Any]], ti_le: float, seed: int = SEED) -> tuple[list, list]:
    """Tách THEO template (semantic_group_id), phân tầng theo nhãn: mọi câu của một template cùng một phía (TA 30/10 câu 6).
    Mỗi nhãn đưa ceil(ti_le × số template của nhãn) template sang validation (≥ 1 nếu ti_le > 0)."""
    if not 0 <= ti_le < 1:
        raise SystemExit("DỪNG: --ti-le-val phải trong [0, 1)")
    nhan_cua: dict[str, set[int]] = {}
    for r in rows:
        nhan_cua.setdefault(r["semantic_group_id"], set()).add(int(r["label"]))
    rng = random.Random(seed)
    val_g: set[str] = set()
    for lab in (0, 1):
        gs = sorted(g for g, s in nhan_cua.items() if max(s) == lab)  # template lẫn nhãn xếp theo nhãn tấn công
        rng.shuffle(gs)
        k = math.ceil(ti_le * len(gs)) if ti_le > 0 and gs else 0
        val_g.update(gs[:k])
    return [r for r in rows if r["semantic_group_id"] not in val_g], [r for r in rows if r["semantic_group_id"] in val_g]


def kiem_tra(train: Sequence[Mapping[str, Any]], val: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ids = [r["id"] for r in [*train, *val]]
    if len(set(ids)) != len(ids):
        raise SystemExit("DỪNG: trùng id sau khi ghép")
    gt, gv = {r["semantic_group_id"] for r in train}, {r["semantic_group_id"] for r in val}
    if gt & gv:
        raise SystemExit(f"DỪNG: {len(gt & gv)} nhóm vừa ở train vừa ở validation")
    tt, tv = {norm_basic(r["text"]) for r in train}, {norm_basic(r["text"]) for r in val}
    trung = len(tt & tv)
    if trung:
        raise SystemExit(f"DỪNG: {trung} câu (chuẩn hoá cơ bản) có ở cả train lẫn validation")
    return {"train": dict(Counter(r["nguon"] for r in train)), "validation": dict(Counter(r["nguon"] for r in val)),
            "nhan_train": dict(Counter(r["label_name"] for r in train)),
            "nhan_val": dict(Counter(r["label_name"] for r in val)), "trung_text_train_val": trung}  # fmt: skip


def sang_rq4(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Validation chung ở lược đồ RQ4 cho `scripts/eval/rq4_danh_gia.py` (template_id = nhóm, ho = family)."""
    inv = {v: k for k, v in RQ4_LABEL.items()}
    return [{"id": r["id"], "ho": r["family_id"], "template_id": r["semantic_group_id"], "cau": r["text"],
             "nhan": inv[int(r["label"])]} for r in rows]  # fmt: skip


def _cmd_chuan_bi(a: argparse.Namespace) -> None:
    out = Path(a.ra)
    v3_train, v3_val = tu_v3(doc_csv(a.v3_train), "train"), tu_v3(doc_csv(a.v3_val), "validation")
    if a.khong_rq4:  # tái lập v3: chỉ dữ liệu v3 — kiểm script đúng công thức (seed 123 v3: macro-F1 val 0,9494)
        if a.rq4_train:
            raise SystemExit("DỪNG: --khong-rq4 thì không truyền --rq4-train")
        rq4_tr, rq4_val = [], []
    elif not a.rq4_train:
        raise SystemExit("DỪNG: cần --rq4-train (hoặc --khong-rq4 để tái lập v3)")
    else:
        rq4_tr, rq4_val = tach_theo_template(tu_rq4(doc_csv(a.rq4_train)), a.ti_le_val, a.seed)
    train, val = [*v3_train, *rq4_tr], [*v3_val, *rq4_val]
    ket = kiem_tra(train, val)
    ghi_csv(out / "v4_train.csv", train, V4_COLS)
    ghi_csv(out / "v4_val.csv", val, V4_COLS)
    ghi_csv(out / "val_chung_rq4.csv", sang_rq4(val), RQ4_COLS)
    meta = {"lenh": "chuan-bi", "phien_ban": PHIEN_BAN, "ti_le_val": a.ti_le_val, "seed_tach": a.seed,
            "khong_rq4": a.khong_rq4,
            "dau_vao": {k: {"file": str(p), "sha256": sha256_file(p)}
                        for k, p in (("v3_train", a.v3_train), ("v3_val", a.v3_val), ("rq4_train", a.rq4_train)) if p},
            "dau_ra": {f: sha256_file(out / f) for f in ("v4_train.csv", "v4_val.csv", "val_chung_rq4.csv")},
            "template_rq4_sang_val": sorted({r["semantic_group_id"] for r in rq4_val}), **ket}  # fmt: skip
    (out / "chuan_bi.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"chuan-bi: train {len(train)} {ket['train']} · validation {len(val)} {ket['validation']} → {out}")


# ---- 2. train (Kaggle T4) ---------------------------------------------------------------------------------------------


def chon_max_length(n_tokens: Sequence[int]) -> tuple[int, float]:
    """Như ô 15 v3: giá trị nhỏ nhất của ứng viên ≥ p99 (train+validation)."""
    s = sorted(n_tokens)
    k = (len(s) - 1) * 0.99
    lo, hi = math.floor(k), math.ceil(k)
    p99 = s[lo] + (s[hi] - s[lo]) * (k - lo)
    return next((x for x in MAX_LENGTH_CANDIDATES if x >= p99), MAX_LENGTH_CANDIDATES[-1]), p99


def _cmd_train(a: argparse.Namespace) -> None:  # pragma: no cover — cần GPU + transformers
    import os

    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    os.environ["WANDB_DISABLED"] = "true"
    import numpy as np
    import torch
    import transformers
    from datasets import Dataset, DatasetDict
    from sklearn.metrics import f1_score, recall_score, roc_auc_score
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        EarlyStoppingCallback,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    if transformers.__version__ != TRANSFORMERS_V3:
        msg = f"transformers {transformers.__version__} ≠ {TRANSFORMERS_V3} của v3"
        if not a.cho_phep_lech_phien_ban:
            raise SystemExit(f"DỪNG: {msg}")
        print(f"[WARN] {msg}")
    if not torch.cuda.is_available() and not a.cho_phep_cpu:
        raise SystemExit("DỪNG: không có GPU (v3 train trên Kaggle T4). Chạy thử nhỏ trên CPU: --cho-phep-cpu")

    def seed_everything(seed: int) -> None:  # ô 7 v3
        os.environ["PYTHONHASHSEED"] = str(seed)
        random.seed(seed)
        np.random.seed(seed)
        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        set_seed(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False

    d = Path(a.du_lieu)
    train_rows, val_rows = doc_csv(d / "v4_train.csv"), doc_csv(d / "v4_val.csv")
    out = Path(a.ra)
    seed_everything(SEED)
    tok = AutoTokenizer.from_pretrained(MODEL_NAME)
    # MAX_LENGTH luôn tính trên TOÀN BỘ train+validation (như ô 15 v3) — kể cả khi chạy thử nhỏ
    lens = [len(x) for x in tok([r["text"] for r in [*train_rows, *val_rows]], add_special_tokens=True,
                                truncation=False)["input_ids"]]  # fmt: skip
    max_length, p99 = chon_max_length(lens)
    if a.thu_nho:  # chạy thử script, KHÔNG dùng kết quả
        rnd = random.Random(SEED)
        train_rows, val_rows = rnd.sample(train_rows, min(a.thu_nho, len(train_rows))), val_rows[: max(a.thu_nho // 4, 8)]
    print(f"[AUTO] MAX_LENGTH = {max_length} (p99 train+validation = {p99:.0f} tokens)")
    if max_length != ML_SERVICE_MAX_LENGTH:
        raise SystemExit(f"DỪNG: MAX_LENGTH {max_length} ≠ {ML_SERVICE_MAX_LENGTH} — ml-service cắt cửa sổ theo 128; báo TA")

    def to_ds(rows: Sequence[Mapping[str, str]]) -> Any:
        return Dataset.from_dict({"text": [r["text"] for r in rows], "label": [int(r["label"]) for r in rows]})

    raw = DatasetDict({"train": to_ds(train_rows), "validation": to_ds(val_rows)})
    tokenized = raw.map(lambda b: tok(b["text"], truncation=True, max_length=max_length), batched=True,
                        remove_columns=["text"])  # fmt: skip
    fp16 = bool(torch.cuda.is_available())
    collator = DataCollatorWithPadding(tokenizer=tok, pad_to_multiple_of=8 if fp16 else None)
    steps_per_epoch = math.ceil(math.ceil(len(tokenized["train"]) / HYPER["per_device_train_batch_size"])
                                / HYPER["gradient_accumulation_steps"])  # fmt: skip
    warmup = math.ceil(steps_per_epoch * HYPER["num_train_epochs"] * HYPER["warmup_ratio"])

    def compute_metrics(ev: Any) -> dict[str, float]:
        logits = ev.predictions[0] if isinstance(ev.predictions, (tuple, list)) else ev.predictions
        z = logits - logits.max(axis=-1, keepdims=True)
        p = (np.exp(z) / np.exp(z).sum(axis=-1, keepdims=True))[:, LABEL2ID["INJECTION"]]
        y, yhat = ev.label_ids, (p >= HYPER["threshold"]).astype(int)
        return {"macro_f1": float(f1_score(y, yhat, average="macro", labels=[0, 1], zero_division=0)),
                "recall": float(recall_score(y, yhat, pos_label=1, zero_division=0)),
                "roc_auc": float(roc_auc_score(y, p)) if len(set(y.tolist())) == 2 else float("nan")}  # fmt: skip

    args = TrainingArguments(
        output_dir=str(out / "checkpoints"), eval_strategy="epoch", save_strategy="epoch", logging_strategy="steps",
        logging_steps=HYPER["logging_steps"], logging_first_step=True, learning_rate=HYPER["learning_rate"],
        per_device_train_batch_size=HYPER["per_device_train_batch_size"],
        per_device_eval_batch_size=HYPER["per_device_eval_batch_size"],
        gradient_accumulation_steps=HYPER["gradient_accumulation_steps"], num_train_epochs=HYPER["num_train_epochs"],
        weight_decay=HYPER["weight_decay"], warmup_steps=warmup, lr_scheduler_type=HYPER["lr_scheduler_type"],
        load_best_model_at_end=True, metric_for_best_model=HYPER["metric_for_best_model"], greater_is_better=True,
        save_total_limit=HYPER["save_total_limit"], save_only_model=True, fp16=fp16, seed=SEED, data_seed=SEED,
        report_to="none", dataloader_num_workers=HYPER["dataloader_num_workers"],
    )  # fmt: skip
    seed_everything(SEED)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME, num_labels=2, id2label=ID2LABEL,
                                                               label2id=LABEL2ID)  # fmt: skip
    trainer = Trainer(model=model, args=args, train_dataset=tokenized["train"], eval_dataset=tokenized["validation"],
                      data_collator=collator, compute_metrics=compute_metrics, processing_class=tok,
                      callbacks=[EarlyStoppingCallback(early_stopping_patience=HYPER["early_stopping_patience"])])  # fmt: skip
    trainer.train()
    final = out / "final_model"
    trainer.save_model(str(final))
    tok.save_pretrained(str(final))
    pred = trainer.predict(tokenized["validation"]).predictions
    pred = pred[0] if isinstance(pred, (tuple, list)) else pred
    z = pred - pred.max(axis=-1, keepdims=True)
    p = (np.exp(z) / np.exp(z).sum(axis=-1, keepdims=True))[:, LABEL2ID["INJECTION"]]
    ghi_csv(out / "du_doan_validation.csv",
            [{"id": r["id"], "label": r["label"], "p_injection": f"{float(x):.6f}"} for r, x in zip(val_rows, p)],
            ["id", "label", "p_injection"])  # fmt: skip
    info = {"phien_ban_script": PHIEN_BAN, "sha256_script": sha256_file(__file__), "seed": SEED, "max_length": max_length, "p99_tokens": p99, "fp16": fp16,
            "thu_nho": a.thu_nho, "so_cau": {"train": len(train_rows), "validation": len(val_rows)},
            "best_checkpoint": trainer.state.best_model_checkpoint, "best_metric": trainer.state.best_metric,
            "hyper": HYPER, "warmup_steps": warmup, "du_lieu_sha256": {f: sha256_file(d / f) for f in ("v4_train.csv", "v4_val.csv")},
            "moi_truong": {"python": sys.version.split()[0], "torch": torch.__version__,
                           "transformers": transformers.__version__, "cuda": torch.version.cuda,
                           "gpu": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},
            "log": trainer.state.log_history}  # fmt: skip
    (out / "train_summary.json").write_text(json.dumps(info, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    shutil.rmtree(out / "checkpoints", ignore_errors=True)
    print(f"train: best {info['best_metric']} @ {info['best_checkpoint']} → {final}")


# ---- 3. dong-goi ------------------------------------------------------------------------------------------------------


def viet_manifest(d: Path) -> str:
    """`<sha256>  <đường tương đối>` mỗi file (trừ chính manifest), sắp theo đường — định dạng `guard.parse_manifest`."""
    files = sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file() and p.name != MANIFEST_FILE)
    text = "".join(f"{sha256_file(d / f)}  {f}\n" for f in files)
    (d / MANIFEST_FILE).write_text(text, encoding="utf-8")
    return sha256_file(d / MANIFEST_FILE)


def dong_goi(src: Path, dst: Path, thresholds: Path | None, card: Mapping[str, Any]) -> dict[str, Any]:
    if dst.exists() and any(dst.iterdir()):
        raise SystemExit(f"DỪNG: {dst} đã có file — dùng thư mục mới (không ghi đè model đã giao)")
    missing = [f for f in REQUIRED_FILES if not (src / f).is_file()]
    if missing:
        raise SystemExit(f"DỪNG: {src} thiếu {missing}")
    cfg = json.loads((src / "config.json").read_text(encoding="utf-8"))
    labels = {int(k): v for k, v in cfg.get("id2label", {}).items()}
    if [i for i, v in labels.items() if v == "INJECTION"] != [1] or sorted(labels) != [0, 1]:
        raise SystemExit(f"DỪNG: id2label {labels} không đúng {{0: BENIGN, 1: INJECTION}}")
    dst.mkdir(parents=True, exist_ok=True)
    bo = []
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        if p.suffix.lower() in FORBIDDEN_SUFFIXES:  # vd training_args.bin — ml-service từ chối khởi động nếu còn
            bo.append(p.name)
            continue
        shutil.copy2(p, dst / p.name)
    if thresholds is not None:
        shutil.copy2(thresholds, dst / "thresholds.json")
    lines = [f"# injection-clf {dst.name}", "", "Chỉ dùng cho thí nghiệm RQ4 (DA10) — KHÔNG thay vào hệ thống.", ""]
    lines += [f"- {k}: {v}" for k, v in card.items()]
    (dst / "model_card.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    manifest_sha = viet_manifest(dst)
    return {"thu_muc": str(dst), "bo_file": bo, "model_sha256": sha256_file(dst / "model.safetensors"),
            "manifest_sha256": manifest_sha}  # fmt: skip


def _cmd_dong_goi(a: argparse.Namespace) -> None:
    src = Path(a.model)
    summary = src.parent / "train_summary.json"
    s = json.loads(summary.read_text(encoding="utf-8")) if summary.is_file() else {}
    card = {"base": MODEL_NAME, "cong_thuc": "đúng notebook v3 (Dương), 1 seed", "seed": s.get("seed", SEED),
            "max_length": s.get("max_length"), "du_lieu_sha256": s.get("du_lieu_sha256"),
            "best_metric_macro_f1_val": s.get("best_metric"), "moi_truong": s.get("moi_truong"),
            "thresholds": "thresholds.json (chọn trên validation chung)" if a.thresholds else "chưa có"}  # fmt: skip
    kq = dong_goi(src, Path(a.ra), Path(a.thresholds) if a.thresholds else None, card)
    print(json.dumps(kq, ensure_ascii=False, indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="fine_tune_v4", description="RQ4 — fine-tune injection-clf v4 (DA10)")
    sp = p.add_subparsers(dest="lenh", required=True)
    c = sp.add_parser("chuan-bi")
    for arg in ("--v3-train", "--v3-val", "--ra"):
        c.add_argument(arg, required=True)
    c.add_argument("--rq4-train")
    c.add_argument("--khong-rq4", action="store_true", help="chỉ dữ liệu v3 (tái lập v3 để kiểm script)")
    c.add_argument("--ti-le-val", type=float, default=0.0, help="tỉ lệ template RQ4 sang validation (CHỜ TA chốt)")
    c.add_argument("--seed", type=int, default=SEED)
    c.set_defaults(f=_cmd_chuan_bi)
    t = sp.add_parser("train")
    t.add_argument("--du-lieu", required=True)
    t.add_argument("--ra", required=True)
    t.add_argument("--thu-nho", type=int, default=0, help="chạy thử N câu train (không dùng kết quả)")
    t.add_argument("--cho-phep-cpu", action="store_true")
    t.add_argument("--cho-phep-lech-phien-ban", action="store_true")
    t.set_defaults(f=_cmd_train)
    g = sp.add_parser("dong-goi")
    g.add_argument("--model", required=True)
    g.add_argument("--ra", required=True)
    g.add_argument("--thresholds")
    g.set_defaults(f=_cmd_dong_goi)
    a = p.parse_args(argv)
    a.f(a)


if __name__ == "__main__":
    main()
