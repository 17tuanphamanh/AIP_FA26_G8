# Đối chiếu model intent với LLM — kết quả lượt chính (17/11/2026)

Quy tắc tính và cách đọc đã khoá trước ở `GHI-TRUOC.md` (mục 3, 4, 6, 7). File này chỉ ghi lượt chạy và đọc số theo các quy tắc đó.

## 1. Lượt chạy

- **Máy:** máy demo (MacBook Pro của Tuấn Anh), stack `servicedesk`, ngày 17/11/2026 lúc 15:35–15:36 (+07). Lệnh như `GHI-TRUOC.md`
  mục 5 và mục 7, thêm `-p servicedesk` cho đúng tên stack và ghi kết quả vào `.verify/doi-chieu-intent/` thay vì `/tmp`.
- **Model:** `intent-clf` bản `v3.1-seed42-st` (lấy từ `/health` của ml-service, ghi ở dòng đầu mỗi `model-ra.jsonl`).
- **Mã:** backend trên máy demo ở `8a04a4c`, sớm hơn bản nộp `a2f4ad1` 8 commit. Thư mục `ml_service/` giống hệt giữa hai commit
  (`git diff --stat 8a04a4c a2f4ad1 -- ml_service/` rỗng); `cham.py` chỉ dùng thư viện chuẩn. Vì vậy số này là số của bản nộp.
- **Đầu vào:** sha256 trong dòng đầu khớp file đã commit — đợt 1 `103920952b5d…`, đợt 1b `ed17ab517998…`.
- **Kết quả thô:** `ket-qua/dot1/model-ra.jsonl` (sha256 `304873078a56…`), `ket-qua/dot1b-cong5/model-ra.jsonl` (sha256 `3cffac592cd7…`).
  Bảng tính lại bằng `phan_tich.py`: `ket-qua/*/ket-qua.md` và `ket-qua.json`.
- **So với lượt sơ bộ trong máy ảo** (16–17/11, torch 2.9.1 CPU, mã `ml_service/app` ở `a2f4ad1`): nhãn trùng 100/100 và 45/45;
  chênh xác suất lớn nhất 0,000007 (đợt 1) và 0,000037 (đợt 1b). Theo mục 6, báo một số.

## 2. Số

| | Đợt 1 — the100 | Đợt 1b — 45 câu intent cổng 5 |
|---|---|---|
| Model khớp nhãn vàng, cả bộ | 95/100 = 95,0% (KTC 95% 88,7–98,4%) | 40/45 = 88,9% (75,9–96,3%) |
| Macro-F1 của model, 4 nhãn IT | 0,9510 | 0,9321 |
| Tập chung (LLM ra đúng một nhãn) | 93 | 45 |
| Chỉ LLM, đúng trên tập chung | 93/93 | 43/45 |
| Model, đúng trên tập chung | 88/93 | 40/45 |
| Bảng chéo: cả hai đúng / chỉ model sai / chỉ LLM sai / cả hai sai | 88 / 5 / 0 / 0 | 39 / 4 / 1 / 1 |
| R2 (model sửa khi p ≥ 0,75): đúng | 88/93 | 40/45 |
| R2: số lần sửa / sửa đúng / sửa sai | 5 / 0 / 5 | 6 / 1 / 4 (1 lần sửa từ sai sang sai) |
| R1 (lệch thì chuyển người): tự nhận / đúng | 88 / 88 | 39 / 39 |
| R1: chuyển người thêm / lỗi LLM được chặn | 5 / 0 | 6 / 2 |

Macro-F1 ở đây đo trên câu người viết, khác bộ với 0,9531 (kiểm định) và 0,9885 (kiểm tra) của câu LLM sinh; không đặt cạnh nhau
như cùng một phép đo.

## 3. Đọc theo luật đã khoá

- **Mục 4 (chất lượng model):** cận dưới KTC của Y là 88,7%, không dưới 85%, nên thuộc trường hợp "Y cao": model giữ được chất lượng
  trên câu người viết. LLM vẫn quyết ở B3 vì B3 còn phải trích trường (D-53), không phải vì model kém.
- **Mục 6 và 7 (gộp R2):** ở cả hai đợt, R2 sửa sai nhiều hơn sửa đúng và có tỉ lệ đúng thấp hơn chỉ dùng LLM. Điều kiện "gộp chính xác
  hơn LLM" cần đạt ở mọi đợt, nên đã không thể đạt dù đợt 2 ra thế nào. Kết luận: trên dữ liệu đo, gộp R2 không tăng độ chính xác;
  giữ LLM quyết (D-53). Đợt 2 vẫn chạy như đã khoá để báo đủ số.
- **R1:** không làm nhãn chính xác hơn, nhưng là tín hiệu cảnh báo. Ở đợt 1b, R1 chặn cả 2 lỗi của LLM với 6 lượt chuyển người thêm;
  trong đó I-ACS-07 vốn đã sang người vì LLM trả `out_of_scope`, nên phần chặn thêm thật là 1 lỗi. Ở đợt 1, R1 thêm 5 lượt và không
  chặn lỗi nào. Ghi là hướng phát triển (model chạy bóng, lệch thì cảnh báo), không đổi bản nộp trước bảo vệ.
- **Mục 7, báo riêng:** ở 2 câu LLM sai, model đúng I-ACS-07 và sai I-OOS-02.

Danh sách thẻ lệch của đợt 1 nằm ở `ket-qua/dot1/ket-qua.md`. Người viết thẻ bộ bổ sung không mở file này cho tới khi đã gửi phiếu
viết (mục 6, "Thứ tự để đợt 2 sạch").
