# Đối chiếu model intent với LLM trên 100 thẻ the100 — ghi trước

Ghi 16/11/2026, **trước khi chạy model**. Nguồn đề xuất: `claude/de-xuat-doi-chieu-intent-1611.md` (Project), Tuấn Anh chốt
16/11. Đây là số kỹ thuật của O1 (model intent ở B3), **không phải RQ mới**, không đo lại RQ1–RQ4, không đổi hệ thống, không đổi tag.

## 1. Vì sao đo

- Báo cáo 15/11 mục 4.9 ghi "điểm của mô hình trên 100 kịch bản kiểm thử được chấm riêng" (D-69), nhưng chưa có kết quả nào.
- Số của model hiện chỉ có trên câu do LLM sinh (VAL 3.143 câu 0,9531, TEST 3.191 câu 0,9885 — Bảng 4.3). Câu đầu của 100
  thẻ the100 do người trong nhóm viết, nên đây là lần đầu model được đo trên câu người viết.
- Ở bản đo, model không nằm trên đường quyết định (D-53: B3 chỉ ghi điểm; D-69: máy đo không nạp). Kết quả nào cũng không đổi
  số RQ.

## 2. Đầu vào (khoá trước)

- `dau-vao.jsonl` (100 thẻ + 1 dòng header), dựng bằng `scripts/eval/doi_chieu_intent/chuan_bi.py` từ bản đo `bf94df2`:
  - Chuỗi đưa model = `l0(redact(câu đầu))`, đúng như `b03_classify.py` gửi `/classify_intent` ở bản đo, che bằng luật che của
    `bf94df2` (luật cũ, trước D-89). Không câu đầu nào của the100 có chỗ bị che.
  - Nhãn vàng: `gold.intents` của thẻ (access 42, account 34, software 12, vpn 12; thẻ nào cũng một ý).
  - Intent LLM: cột `intent` của `predictions.jsonl` lượt S1 `95b5a579ec7e` (hybrid, deepseek-flash, cache `eval`; gói kết
    quả của Dương, sha256 `22b3c254…c21c64f`). Không gọi lại LLM.
  - Trạng thái LLM: `mot_la` 93 thẻ có intent; `dung_o_b2` 3 (HB02-q1, HB16-q2, HB16-q5, dừng E1 trước B3); `tach_nhieu_y` 2
    (HB04-q12, HB05-q6: LLM tách thành nhiều yêu cầu dù nhãn vàng một ý); `khong_chay` 2 (HB16-q3, HB16-q4: lệch khung giờ).
- Model: gói `intent-clf` đang nạp ở ml-service máy demo (`v3.1-seed42-st`, MANIFEST + SHA kiểm khi khởi động — MODELS.md 1.2).
  Phiên bản lấy từ chính phản hồi `/classify_intent` và `/health`, ghi vào `model-ra.jsonl`.

## 3. Quy tắc tính (khoá trước)

- Nhãn của model = nhãn có điểm cao nhất trong 5 nhãn (`account`, `vpn`, `software`, `access`, `out_of_scope`). Hoà điểm cao
  nhất → script dừng, người xem. Dự đoán `out_of_scope` tính là sai.
- Báo, mỗi tỉ lệ kèm Clopper–Pearson hai phía 95%:
  - **Y** — model khớp nhãn vàng, trên 100 thẻ; và trên tập chung 93 thẻ `mot_la`.
  - **X** — model khớp LLM, trên tập chung 93 thẻ.
  - **Z** — LLM khớp nhãn vàng, trên tập chung 93 thẻ.
  - Bảng chéo trên tập chung: cả hai đúng / chỉ model sai / chỉ LLM sai / cả hai sai.
  - Macro-F1 của model trên 4 nhãn vàng, 100 thẻ (để đặt cạnh 0,9531 / 0,9885, ghi rõ khác bộ đo).
  - Mô tả: số thẻ không nhãn nào ≥ 0,75, số thẻ từ 2 nhãn ≥ 0,75, số câu bị cắt độ dài; danh sách từng thẻ lệch (không in câu).
- Không chọn ngưỡng, không đổi cấu hình, không chạy lại để lấy số đẹp hơn. Lỗi khi chấm (HTTP khác 200, sha câu lệch) → dừng,
  sửa nguyên nhân, chạy lại cả 100 câu.
- Số đã biết trước khi chạy model (đếm từ file của Dương, không cần model): **Z = 93/93**. Vì vậy X và Y trên tập chung bằng
  nhau; con số mới thật sự là Y và danh sách thẻ lệch.

## 4. Đọc kết quả (khoá trước)

- Y cao (cận dưới KTC ≥ 0,85, mục tiêu macro-F1 của nhóm): model giữ được chất lượng trên câu người viết; củng cố câu "model và
  LLM nhất quán, LLM quyết vì B3 vẫn phải trích trường (D-53), không phải vì model kém".
- Y thấp hơn: vẫn có ích — là bằng chứng trên câu người viết cho quyết định không để model quyết. Ghi là giới hạn của model,
  nêu các thẻ lệch, so với khoảng cách giữa câu LLM sinh và câu người viết.
- Mọi trường hợp: không đổi số RQ1–RQ4; ghi ở mục 4.9 (số kỹ thuật O1), không thêm RQ.

## 5. Ai làm, cách chạy

| Bước | Ai | Việc |
|---|---|---|
| 1 | Claude (đã xong 16/11) | Dựng `dau-vao.jsonl`, script, test; commit file này trước khi chạy model |
| 2 | Tuấn Anh, máy demo | Chạy `cham.py` (khoảng 5 phút); máy demo giữ nguyên `a2f4ad1`, không checkout nhánh này |
| 3 | Claude | Chạy `phan_tich.py`, commit `model-ra.jsonl`, `ket-qua.json`, `ket-qua.md` |
| 4 | Duy Anh (người giao trọng số model, theo MODELS.md) | Đọc danh sách thẻ lệch, ghi nhận xét; không đổi số |

Bước 2 trên máy demo (ml-service phải đang nạp `intent-clf`; lấy file từ nhánh bằng `git show`, không checkout):

```bash
git fetch origin doi-chieu-intent
git show origin/doi-chieu-intent:eval/doi-chieu-intent/dau-vao.jsonl > /tmp/dau-vao.jsonl
git show origin/doi-chieu-intent:scripts/eval/doi_chieu_intent/cham.py > /tmp/cham.py
docker compose cp /tmp/dau-vao.jsonl backend:/tmp/dau-vao.jsonl
docker compose cp /tmp/cham.py backend:/tmp/cham.py
docker compose exec -T backend python /tmp/cham.py /tmp/dau-vao.jsonl > /tmp/model-ra.jsonl
```

Gửi `/tmp/model-ra.jsonl` cho Claude. Script chỉ gọi `/health` và `/classify_intent`, không gọi LLM, không ghi DB, không in token.
Hạn: trước T6 20/11 (cùng hạn dừng cứng của đo bổ sung). Quá hạn thì không chạy; báo cáo 4.9 phải bỏ câu "được chấm riêng" và
ghi là chưa đo.
