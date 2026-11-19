# Đo bổ sung RQ1 — lớp LLM có tách ca tự xử lý được với ca cần người không

Lượt mới: run `7eae4ad6041a`, dataset `ad8ad99e2937…`, commit `9d2e786`, predictions sha256 `2b4e527d0c54…`.

**Nhãn bộ mới (mục 10 a):** AUTO 4/44 thẻ đã khoá, KTC 95% [0,025; 0,217]

| Bộ | Lá | Cần người | AUTO | Họ | AUC | KTC 95% | Đọc |
|---|---|---|---|---|---|---|---|
| Bộ mới (chính) | 26 | 22 | 4 | 26 | 0,443 | [0,260; 0,725] | không đủ dữ liệu |
| Bộ mới — nhãn khớp từ đầu (độ nhạy) | 20 | 18 | 2 | 20 | 0,361 | [0,250; 0,447] | không đủ dữ liệu |
| S1 cũ (tham khảo) | 56 | 51 | 5 | 14 | 0,767 | [0,430; 0,967] | chưa thấy tín hiệu |
| Gộp mới + cũ (phụ) | 82 | 73 | 9 | 40 | 0,627 | [0,403; 0,810] | chưa thấy tín hiệu |

Lá bị loại (bộ mới): khong_toi_m5 10, luat_quyet 7

## Bộ mới (chính)

| p thô | AUTO | HITL | ESCALATE_L2 |
|---|---|---|---|
| 0,0 | 0 | 0 | 0 |
| 0,2 | 0 | 1 | 1 |
| 0,4 | 0 | 0 | 0 |
| 0,6 | 0 | 2 | 0 |
| 0,8 | 1 | 2 | 1 |
| 1,0 | 3 | 13 | 2 |

KTC 95% của AUC khi bootstrap theo người gửi (11 người): [0,275; 0,623]

| Tự xử lý khi p ≤ | AUTO được tự xử lý | Cần người bị tự xử lý (áp D-34) | Cận trên 95% | Cần người có p ≤ ngưỡng (không áp D-34) | Cận trên 95% |
|---|---|---|---|---|---|
| 0,0 | 0/4 | 0/22 | 0,127 | 0/22 | 0,127 |
| 0,2 | 0/4 | 0/22 | 0,127 | 2/22 | 0,259 |

## Bộ mới — nhãn khớp từ đầu (độ nhạy)

| p thô | AUTO | HITL | ESCALATE_L2 |
|---|---|---|---|
| 0,0 | 0 | 0 | 0 |
| 0,2 | 0 | 1 | 0 |
| 0,4 | 0 | 0 | 0 |
| 0,6 | 0 | 2 | 0 |
| 0,8 | 0 | 2 | 0 |
| 1,0 | 2 | 13 | 0 |

| Tự xử lý khi p ≤ | AUTO được tự xử lý | Cần người bị tự xử lý (áp D-34) | Cận trên 95% | Cần người có p ≤ ngưỡng (không áp D-34) | Cận trên 95% |
|---|---|---|---|---|---|
| 0,0 | 0/2 | 0/18 | 0,153 | 0/18 | 0,153 |
| 0,2 | 0/2 | 0/18 | 0,153 | 1/18 | 0,238 |

## S1 cũ (tham khảo)

| p thô | AUTO | HITL | ESCALATE_L2 |
|---|---|---|---|
| 0,0 | 1 | 0 | 2 |
| 0,2 | 0 | 0 | 0 |
| 0,4 | 0 | 2 | 2 |
| 0,6 | 2 | 2 | 0 |
| 0,8 | 1 | 7 | 0 |
| 1,0 | 1 | 34 | 2 |

| Tự xử lý khi p ≤ | AUTO được tự xử lý | Cần người bị tự xử lý (áp D-34) | Cận trên 95% | Cần người có p ≤ ngưỡng (không áp D-34) | Cận trên 95% |
|---|---|---|---|---|---|
| 0,0 | 0/5 | 0/13 | 0,206 | 1/13 | 0,316 |
| 0,2 | 0/5 | 0/13 | 0,206 | 1/13 | 0,316 |

## Gộp mới + cũ (phụ)

| p thô | AUTO | HITL | ESCALATE_L2 |
|---|---|---|---|
| 0,0 | 1 | 0 | 2 |
| 0,2 | 0 | 1 | 1 |
| 0,4 | 0 | 2 | 2 |
| 0,6 | 2 | 4 | 0 |
| 0,8 | 2 | 9 | 1 |
| 1,0 | 4 | 47 | 4 |

| Tự xử lý khi p ≤ | AUTO được tự xử lý | Cần người bị tự xử lý (áp D-34) | Cận trên 95% | Cần người có p ≤ ngưỡng (không áp D-34) | Cận trên 95% |
|---|---|---|---|---|---|
| 0,0 | 0/9 | 0/35 | 0,082 | 1/35 | 0,129 |
| 0,2 | 0/9 | 0/35 | 0,082 | 3/35 | 0,207 |
