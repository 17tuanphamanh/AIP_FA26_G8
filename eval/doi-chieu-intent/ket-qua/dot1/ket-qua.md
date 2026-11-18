# Đối chiếu model intent với LLM trên 100 câu — kết quả

Model `intent-clf` bản `v3.1-seed42-st`; intent LLM từ lượt S1 `95b5a579ec7e` (bản đo `bf94df2`); đầu vào sha256 `103920952b5d…`. Quy tắc: `GHI-TRUOC.md`.

- Model khớp nhãn vàng, cả 100 câu: 95/100 = 95,0% (KTC 95% 88,7–98,4%)
- Model khớp nhãn vàng, tập chung 93 thẻ: 88/93 = 94,6% (KTC 95% 87,9–98,2%)
- Model khớp LLM, tập chung: 88/93 = 94,6% (KTC 95% 87,9–98,2%)
- LLM khớp nhãn vàng, tập chung: 93/93 = 100,0% (KTC 95% 96,1–100,0%)
- Bảng chéo tập chung: cả hai đúng 88, chỉ model sai 5, chỉ LLM sai 0, cả hai sai 0
- Macro-F1 của model trên 4 nhãn vàng, cả 100 câu: 0,9510
- Không nhãn nào ≥ 0,75: 0; từ 2 nhãn ≥ 0,75: 6; câu bị cắt độ dài: 0
- Trạng thái LLM của 100 câu: {'mot_la': 93, 'dung_o_b2': 3, 'tach_nhieu_y': 2, 'khong_chay': 2}

## Mô phỏng gộp model với LLM (tập chung, luật khoá trước)

- Chỉ LLM: 93/93 = 100,0% (KTC 95% 96,1–100,0%)
- R1 đồng thuận: tự nhận 88 thẻ, đúng 88/88 = 100,0% (KTC 95% 95,9–100,0%); chuyển người thêm 5, trong đó LLM sai được chặn 0
- R2 model sửa khi chắc: đúng 88/93 = 94,6% (KTC 95% 87,9–98,2%); sửa 5 lần, sửa đúng 0, sửa sai 5

## Các thẻ lệch

| Thẻ | Nhãn vàng | LLM | Model | p cao nhất |
|---|---|---|---|---|
| HB02-q6 | access | access | out_of_scope | 0,939 |
| HB06-q2 | vpn | vpn | access | 0,895 |
| HB06-q5 | vpn | vpn | access | 0,962 |
| HB10-q5 | account | account | vpn | 0,901 |
| HB12-q1 | account | account | out_of_scope | 0,962 |
