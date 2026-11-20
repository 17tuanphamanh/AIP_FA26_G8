# Đối chiếu model intent với LLM trên 44 câu — kết quả

Model `intent-clf` bản `v3.1-seed42-st`; intent LLM từ lượt S1 `7eae4ad6041a` (bản đo `bf94df2`); đầu vào sha256 `375707fbd979…`. Quy tắc: `GHI-TRUOC.md`.

- Model khớp nhãn vàng, cả 44 câu: 38/44 = 86,4% (KTC 95% 72,6–94,8%)
- Model khớp nhãn vàng, tập chung 40 thẻ: 34/40 = 85,0% (KTC 95% 70,2–94,3%)
- Model khớp LLM, tập chung: 34/40 = 85,0% (KTC 95% 70,2–94,3%)
- LLM khớp nhãn vàng, tập chung: 40/40 = 100,0% (KTC 95% 91,2–100,0%)
- Bảng chéo tập chung: cả hai đúng 34, chỉ model sai 6, chỉ LLM sai 0, cả hai sai 0
- Macro-F1 của model trên 4 nhãn vàng, cả 44 câu: 0,9107
- Không nhãn nào ≥ 0,75: 1; từ 2 nhãn ≥ 0,75: 7; câu bị cắt độ dài: 0
- Trạng thái LLM của 44 câu: {'mot_la': 40, 'tach_nhieu_y': 1, 'dung_o_b2': 3}

## Mô phỏng gộp model với LLM (tập chung, luật khoá trước)

- Chỉ LLM: 40/40 = 100,0% (KTC 95% 91,2–100,0%)
- R1 đồng thuận: tự nhận 34 thẻ, đúng 34/34 = 100,0% (KTC 95% 89,7–100,0%); chuyển người thêm 6, trong đó LLM sai được chặn 0
- R2 model sửa khi chắc: đúng 35/40 = 87,5% (KTC 95% 73,2–95,8%); sửa 5 lần, sửa đúng 0, sửa sai 5

## Các thẻ lệch

| Thẻ | Nhãn vàng | LLM | Model | p cao nhất |
|---|---|---|---|---|
| SB03-q1 | access | access | out_of_scope | 0,703 |
| SB15-q1 | vpn | vpn | access | 0,982 |
| SB19-q1 | access | access | out_of_scope | 0,822 |
| SB26-q1 | vpn | vpn | access | 0,965 |
| SB33-q1 | account | account | out_of_scope | 0,984 |
| SB35-q1 | account | account | out_of_scope | 0,971 |
