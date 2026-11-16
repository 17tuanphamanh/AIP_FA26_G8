# Khối lệnh — đo bổ sung RQ1

Theo `GHI-TRUOC.md`. Mọi lệnh chạy ở thư mục gốc của nhánh `do-bo-sung-rq1`. Thư mục `~/bo-sung-rq1/` nằm **ngoài repo**: chứa
phiếu, bài gán, kết quả lượt chạy, không commit.

## 0. Một lần trên mỗi máy

```
cd ~/code/AIP_FA26_G8            # thư mục repo của bạn
git fetch origin
git worktree add ../AIP_FA26_G8-bo-sung origin/do-bo-sung-rq1
cd ../AIP_FA26_G8-bo-sung
git log --oneline -1             # phải là commit mới nhất của nhánh
git diff --stat bf94df2 -- backend config mock_services ml_service docker-compose.yml   # phải rỗng
```

## 1. Khung (Tuấn Anh hoặc Claude) — đã chạy, chạy lại để kiểm tái lập

```
uv run python scripts/eval/bo_sung_rq1/khung.py --out ~/bo-sung-rq1/khung
# khung.csv sha256 phải là aad7883283f9e2ffea84d64d03871220081194eb0e4fb8a9085dc179be947538
```

Phát `~/bo-sung-rq1/khung/phieu-viet.xlsx` cho người viết, kèm `HUONG-DAN-VIET.md`.

## 2. Phiếu gán (sau khi nhận phiếu viết đã điền, lưu thành `~/bo-sung-rq1/viet.xlsx`)

```
uv run python scripts/eval/bo_sung_rq1/dung_the.py phieu-gan \
  --khung ~/bo-sung-rq1/khung/khung.csv --viet ~/bo-sung-rq1/viet.xlsx --out ~/bo-sung-rq1/phieu
```

`DỪNG` = còn dòng chưa có câu, hoặc một nhóm thiếu chỉ tiêu (viết thêm dòng dự phòng cùng nhóm). Phát
`~/bo-sung-rq1/phieu/phieu-gan.xlsx` cho Dương và Duy Anh, kèm `HUONG-DAN-GAN.md`.

## 3. Gộp nhãn

```
EVAL_MODE=true uv run python scripts/eval/bo_sung_rq1/dung_the.py gop-nhan --phieu ~/bo-sung-rq1/phieu \
  --a ~/bo-sung-rq1/gan-duong.xlsx --b ~/bo-sung-rq1/gan-duyanh.xlsx --out ~/bo-sung-rq1/nhan-lan1
```

- In κ và số ca lệch. `nhan-lan1/lech.csv` liệt kê các ca lệch: gửi cho hai người trao đổi.
- Điền cột `nhan_phan_xu` (lưu thành `~/bo-sung-rq1/phan-xu.csv`). Vẫn lệch thì điền nhãn chặt hơn.
- Rồi chạy:

```
EVAL_MODE=true uv run python scripts/eval/bo_sung_rq1/dung_the.py gop-nhan --phieu ~/bo-sung-rq1/phieu \
  --a ~/bo-sung-rq1/gan-duong.xlsx --b ~/bo-sung-rq1/gan-duyanh.xlsx --phan-xu ~/bo-sung-rq1/phan-xu.csv \
  --out ~/bo-sung-rq1/nhan
```

Xem dòng "nhãn cuối". Một lớp (AUTO hoặc cần người) dưới 8 tình huống thì viết thêm từ dòng dự phòng (`GHI-TRUOC.md` mục 3),
**trước** bước 4.

## 4. Dựng thẻ, tự kiểm, khoá

```
EVAL_MODE=true uv run python scripts/eval/bo_sung_rq1/dung_the.py the --khung ~/bo-sung-rq1/khung/khung.csv \
  --phieu ~/bo-sung-rq1/phieu --viet ~/bo-sung-rq1/viet.xlsx --nhan ~/bo-sung-rq1/nhan/nhan-cuoi.json --out eval/bo-sung-rq1
```

- Dòng cuối phải là `KIỂM: rule_coverage 100% đi lớp LLM, 0 cảnh báo seed; dataset loader nạp đủ, đủ nhãn`.
- Rồi commit `eval/bo-sung-rq1/the/`, `tinh-huong.json`, `KHOA.md` (Tuấn Anh) và push. Từ đây không sửa thẻ.

## 5. Chạy (Dương, máy đo, trong giờ hành chính)

```
git pull                                   # có thẻ + KHOA.md
# .env giống lượt S1: EVAL_MODE=true, LLM_CACHE_MODE=eval, STRATEGY=hybrid, APPROVAL_SLA_MINUTES_DEV=2,
#   B2_CLASSIFIER_MODE=review, B2_TAU_REVIEW=0.9999, INTENT_MODEL_DIR rỗng, LLM thật (DeepSeek), trần chi phí còn đặt
make up && make seed
EVAL_MODE=true PYTHONPATH=backend uv run python -m app.eval.runner --scenarios eval/bo-sung-rq1/the --check-only
EVAL_MODE=true EVAL_PASSWORD='<mật khẩu demo>' PYTHONPATH=backend uv run python -m app.eval.runner \
  --scenarios eval/bo-sung-rq1/the --strategy hybrid --split test --timeout-s 300 --prob-method sampling_k5 \
  --out ~/eval-runs/bo-sung-rq1/s1-moi
```

- Bắt đầu lượt trước 16:00 (GHI-TRUOC mục 10, ý 6); ghi lại giờ bắt đầu và giờ xong.
- `--check-only` phải in `loaded=44 errors=0`, hoặc đúng số thẻ trong `KHOA.md`.
- Còn ca `skipped_hours` (chạy sát biên giờ) thì chạy lại đúng lệnh trên, thay `--out …` bằng `--resume ~/eval-runs/bo-sung-rq1/s1-moi`.
- Ca `timeout` hoặc `error` không chạy bù: chụp màn 7 dòng tổng hợp gửi nhóm.

## 6. Phân tích (Dương)

```
EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/bo_sung_rq1/phan_tich.py \
  --moi ~/eval-runs/bo-sung-rq1/s1-moi/predictions.jsonl ~/eval-runs/bo-sung-rq1/s1-moi/manifest.json \
  --khoa eval/bo-sung-rq1/KHOA.md --tinh-huong eval/bo-sung-rq1/tinh-huong.json --the eval/bo-sung-rq1/the \
  --cu ~/eval-runs/rq1/s1/predictions.jsonl ~/eval-runs/rq1/s1/manifest.json \
  --out ~/eval-runs/bo-sung-rq1/phan-tich
```

- `--cu` là lượt S1 gốc (run `95b5a579ec7e`, τ chạy 0,9999), không phải bản τ 0,50 đã tính lại.
- Gửi nhóm `phan-tich/bang.md` và `ket-qua.json`, kèm sha256 của `predictions.jsonl`. `chi-tiet.csv` giữ trên máy.
