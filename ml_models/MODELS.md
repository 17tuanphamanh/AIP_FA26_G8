# Thẻ model (bản nộp 14/11/2026)

Trọng số **không** nằm trong repo (`.gitignore`: `ml_models/*-clf/`). File này ghi model nào được dùng, kiểm bằng hash gì, ngưỡng nào, và
mỗi con số lấy từ đâu. Số nào không tìm được file nguồn ghi **"chưa truy được"**. Không chép dữ liệu huấn luyện vào repo.

Lập 13/11/2026 (CLI-7 S2; bổ sung chiều 13/11 từ `HANDOFF_MODEL_CHAN_TAN_CONG.docx` và `thresholds.json` khi file đã tải về máy) từ: `MANIFEST.sha256`, `README_MODEL.md`, `mask_probe_results.md`, `thresholds-20261029.json`,
`inference_config.json`, `thresholds.json` trong thư mục `ml_models/` trên máy demo, cùng `docs/spec/build/decisions.md` (D-44, D-52,
D-53, D-69, D-70).

## 1. Model nhóm tự huấn luyện

### 1.1. `injection-clf` — chặn tấn công ở B2 (lớp 3), bản `v3-seed123`

| Mục | Giá trị | Nguồn |
|---|---|---|
| Model nền | `FacebookAI/xlm-roberta-base` (giấy phép MIT), phân loại 2 nhãn: `0 = BENIGN`, `1 = INJECTION` | `README_MODEL.md` |
| Huấn luyện | fine-tune trên bộ **v2.7** (tên bộ; dữ liệu không nằm trong repo), seed 123, `transformers==5.13.1` | `README_MODEL.md`; D-70 |
| Đầu vào | câu gốc, không tiền xử lý; tokenizer `max_length=128`, `truncation=True` | `README_MODEL.md` |
| Đầu ra | `p_mal = softmax(logits)[1]` | `README_MODEL.md` |
| SHA-256 `model.safetensors` | `2d926f83df29cbdbc3637e22ecab893a1e6a0c2dc0f912315b3686a747108a02` | `v3-seed123/MANIFEST.sha256` |
| SHA-256 `config.json` / `tokenizer.json` / `tokenizer_config.json` | `a57c5cd7…40b1` / `2687cc19…5fdf` / `5d84c938…37f6` | `v3-seed123/MANIFEST.sha256` |
| Cách dùng trong hệ thống | chế độ `review` (D-52): model chấm mọi câu không khớp regex; **LLM chấm vẫn xem mọi câu**; LLM nói không mà `p_mal ≥ τ` → E1 `injection_suspected`. Model không bao giờ cho câu đi thẳng. Nhãn che (`<SĐT_n>`, `<EMAIL_n>`…) được thay bằng từ thường trước khi chấm | D-52 |
| **τ báo cáo** | **0,50** — giá trị nhỏ nhất có cận trên 95% (bootstrap theo nhóm) của E1 thừa trên câu thường ≤ E_max 15%, chọn trên b2-val v2.7 (sha `a4a2ed0d…`, LLM chấm `deepseek-flash` `d656ca0f…`): E1 thừa 6,3%, cận trên 11,56% | D-70 |
| τ máy đo (`B2_TAU_REVIEW`) | 0,9999 — số RQ ở τ 0,50 được **tính lại offline** từ audit B2 của chính các lượt đã chạy; độ nhạy báo thêm ở 0,90 / 0,999 / 0,9999 | D-70 |
| τ máy demo | **0,9999** (TA kiểm `.env` máy demo 13/11 18:57). D-70 dự định đổi máy demo sang 0,50 nhưng chưa đổi; video demo 13/11 quay ở 0,9999. Số RQ báo cáo vẫn ở τ 0,50 tính lại offline (D-70) — không phụ thuộc τ máy demo | `.env` máy demo; D-70 |
| `thresholds-20261029.json` | τ 0,9999 chọn nhầm trên validation 25/09 (sha `5360c267…`) — **đã thay** bằng lượt D-70 | file trên máy; D-70 |
| `thresholds.json` (bản hiện hành) | `tau_review` **0,5**, `e_max` 0,15, ngày 2026-10-30, `data_sha256` `a4a2ed0d…11519`, LLM chấm `deepseek-flash`; luật chọn: τ nhỏ nhất (lưới 0,50–0,99 bước 0,01 + 0,995/0,999/0,9999) có cận trên 95% bootstrap theo nhóm (B=2000, seed 20261018) của E1 thừa ≤ E_max — khớp D-70 | `injection-clf/tai-lieu/thresholds.json` (đọc 13/11) |
| Độ trễ | ~17 ms/câu trên CPU 24 luồng | `README_MODEL.md` |
| Chặn nhầm khi câu có nhãn che (22 câu thường, ngưỡng 0,5) | để nguyên nhãn che: **10/22** bị chặn nhầm; giá trị giả: 3/22; từ thường: 0/22 → lý do D-52 thay nhãn che bằng từ thường | `mask_probe_results.md`; D-44 |
| Số đo của model (seed 123, ngưỡng 0,5 — **chỉ model, chưa qua LLM chấm**) | **validation** 900/900: TP 867 · FP 58 · TN 842 · FN 33 → recall 0,9633, FPR 0,0644, FNR 0,0367, macro-F1 0,9494; **test v2.7** 900/900: macro-F1 0,9622, FPR 0,0311, FNR 0,0444; **stress set** 300 câu (Gemini sinh, đảo các lối tắt): macro-F1 0,8633, FPR 0,1133, FNR 0,1600, pair accuracy 0,70; câu không dấu (test, TB 3 seed): F1 0,856, FPR 0,148; hiệu chỉnh trên validation: Brier 0,0489, ECE 0,0491 (chưa temperature scaling) | `injection-clf/tai-lieu/HANDOFF_MODEL_CHAN_TAN_CONG.docx` mục 6, 9, 14, 17 (Dương, 03/10; đọc 13/11) |
| Giới hạn ghi trong bàn giao | test v2.7 cùng bộ sinh với train (số lạc quan); stress set cho thấy chưa nên để model làm bộ chặn duy nhất (recall ~0,44 với tấn công nấp sau khung "giải thích / kiểm tra") → lý do hệ thống để LLM chấm mọi câu (D-52); hay chặn nhầm câu "xem quyền hiện có" (validation: 23/30 và 13/30 câu ở 2 mẫu) | như trên, mục 6, 16 |
| Chia tập | 400 nhóm mẫu chia 280/60/60 (mọi biến thể của một mẫu cùng tập); train 4.200/4.200, validation 900/900, test 900/900; audit rò rỉ = 0; không câu nào lấy từ TC01–TC37 | như trên, mục 11–13 |

### 1.2. `intent-clf` — điểm loại yêu cầu ở B3, bản `v3.1-seed42-st`

| Mục | Giá trị | Nguồn |
|---|---|---|
| Model nền | `FacebookAI/xlm-roberta-base` (giấy phép MIT); 5 nhãn `account`, `vpn`, `software`, `access`, `out_of_scope`; đầu chuỗi + gắn thẻ span (`B-/I-REQ`, `B-/I-MEN`, `B-/I-CTX`) | `inference_config.json` |
| Điểm của gói | `0,4·sigmoid(seq) + 0,6·p_span` | D-53 |
| Trọng số gốc | `seed_42.pt`, SHA `3efd3bd0…46db9` (Duy giao 10/10, đã khớp) | D-44 |
| SHA-256 bản chạy (safetensors fp32) | `model.safetensors` `51f5d267bedabe0bcbb0cbe5faf8901deb792f3137b9697bbf2f7c4c96b120fc`; `inference_config.json` `a9b96133076cf2a601af0b4258d9cdb8768e5b9fe4c22c75b371d42f7b12f336`; `thresholds.json` `5dd8cdb2836e446a898b7b35b74f91a0c1fca9403a5b1820e488bc07295bbdd5` | `v3.1-seed42-st/MANIFEST.sha256` |
| Ngưỡng dùng | **một ngưỡng 0,75** cho mọi nhãn (`tau_lo = tau_hi = 0,75`) | `v3.1-seed42-st/thresholds.json`; D-53 |
| τ_hi/τ_lo từng nhãn của P11 (không dùng — chưa cascade) | account 0,135/0,027 · vpn 0,365/0,679 · software 0,905/0,085 · access 0,305/0,156 · out_of_scope 0,820/0,372 | D-44 |
| Cách dùng trong hệ thống | B3 **chỉ ghi** `model_probs`, `model_version` vào điểm log 1; LLM vẫn quyết loại yêu cầu (cascade không tiết kiệm vì B3 vẫn gọi LLM để trích slot) | D-53 |
| Máy đo RQ | **không nạp** model intent (D-69); điểm intent của 100 thẻ chấm offline. Máy demo nạp cả hai model | D-69 |
| Validation 3.143 câu (một ngưỡng 0,75) | macro-F1 0,9531, exact-match 91,57% | D-44 (số do Duy báo 10/10; file nguồn chưa truy được) |
| Test 3.191 câu (đo MỘT lần, 10/10) | một ngưỡng 0,75: 0,9885; cascade (cận trên): 0,9883; exact-match 97,7% | D-44 (như trên) |
| Soát rò rỉ train–test | 0 câu trùng/gần trùng ≥ 0,92; test gần train hơn val (≥ 0,70: 2,57% so với 0,35%) | D-44 |
| Hệ thống đầu–cuối (LLM quyết, 45 câu cổng 5) | macro-F1 5 lớp 0,9399 — **là của LLM DeepSeek, không phải model nhóm** | `docs/spec/build/phase5-thiet-ke-chi-tiet.md` dòng cổng 5 |

## 2. Model tải sẵn (không huấn luyện)

| Vai trò | Repo | Revision | Nguồn |
|---|---|---|---|
| Embedding (RAG) | `BAAI/bge-m3` | `5617a9f61b028005a4858fdac845db406aefb181` | `ml_service/models.lock.json` |
| Rerank (RAG) | `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | `ml_service/models.lock.json` |

## 3. Giới hạn ghi báo cáo

- Script huấn luyện của hai model không nằm trong repo (`training/intent/`, `training/injection/` chỉ có README); chỉ có
  `training/common/dedup_vs_m8.py` (soát rò rỉ với bộ đo).
- Định dạng lệch P11 §4.3: safetensors fp32, chưa ONNX int8 (D-53).
- Intent: khoảng 5,6% câu sai mà điểm ~0,98 (model tự tin sai); chưa temperature scaling; ngưỡng chọn và đo cùng val (lạc quan) — D-44.
