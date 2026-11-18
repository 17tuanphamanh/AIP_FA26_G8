# Đối chiếu model intent với LLM trên 45 câu — kết quả

Model `intent-clf` bản `v3.1-seed42-st`; intent LLM từ lượt S1 `cong5-20261017-181019` (bản đo `bf94df2`); đầu vào sha256 `ed17ab517998…`. Quy tắc: `GHI-TRUOC.md`.

- Model khớp nhãn vàng, cả 45 câu: 40/45 = 88,9% (KTC 95% 75,9–96,3%)
- Model khớp nhãn vàng, tập chung 45 thẻ: 40/45 = 88,9% (KTC 95% 75,9–96,3%)
- Model khớp LLM, tập chung: 39/45 = 86,7% (KTC 95% 73,2–94,9%)
- LLM khớp nhãn vàng, tập chung: 43/45 = 95,6% (KTC 95% 84,9–99,5%)
- Bảng chéo tập chung: cả hai đúng 39, chỉ model sai 4, chỉ LLM sai 1, cả hai sai 1
- Macro-F1 của model trên 4 nhãn vàng, cả 45 câu: 0,9321
- Không nhãn nào ≥ 0,75: 0; từ 2 nhãn ≥ 0,75: 2; câu bị cắt độ dài: 0
- Trạng thái LLM của 45 câu: {'mot_la': 45}

## Mô phỏng gộp model với LLM (tập chung, luật khoá trước)

- Chỉ LLM: 43/45 = 95,6% (KTC 95% 84,9–99,5%)
- R1 đồng thuận: tự nhận 39 thẻ, đúng 39/39 = 100,0% (KTC 95% 91,0–100,0%); chuyển người thêm 6, trong đó LLM sai được chặn 2
- R2 model sửa khi chắc: đúng 40/45 = 88,9% (KTC 95% 75,9–96,3%); sửa 6 lần, sửa đúng 1, sửa sai 4

## Các thẻ lệch

| Thẻ | Nhãn vàng | LLM | Model | p cao nhất |
|---|---|---|---|---|
| I-SW-03 | software | software | out_of_scope | 0,982 |
| I-SW-04 | software | software | out_of_scope | 0,877 |
| I-SW-06 | software | software | out_of_scope | 0,980 |
| I-ACS-07 | access | out_of_scope | access | 0,979 |
| I-OOS-02 | out_of_scope | account | access | 0,927 |
| I-OOS-03 | out_of_scope | out_of_scope | vpn | 0,879 |
