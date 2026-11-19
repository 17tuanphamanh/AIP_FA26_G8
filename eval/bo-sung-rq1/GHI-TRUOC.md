# Đo bổ sung RQ1 — bản ghi trước (16/11/2026)

Bản này chốt câu hỏi, dữ liệu, cách chạy, cách tính và cách đọc kết quả **trước khi có thẻ và trước khi chạy**. Commit bản này lên
nhánh `do-bo-sung-rq1` trước khi phát phiếu viết; mọi thay đổi sau đó ghi ở mục 10, kèm lý do và thời điểm.

## 1. Vì sao đo, và vì sao không đo như kế hoạch cũ

Kế hoạch cũ (15/11) định viết thêm khoảng 30 tình huống để đưa cận trên tỉ lệ bỏ sót của lớp LLM xuống dưới 10% (0/29 hoặc 1/46).
Rà soát 16/11 cho thấy cách đo đó **gần như ra kết quả định sẵn**:

- Bảng L.20 của báo cáo: ở cả 5 phần, Platt a = 0,027–0,216, ngưỡng dưới t_low = 0 ở 4/5 phần (0,08 ở phần 2). Mục 6.8: cả 48 ca
  do LLM quyết định đều ra HITL.
- Với các tham số đó, p sau hiệu chỉnh nhỏ nhất (p thô = 0) là 0,527 / 0,077 / 0,500 / 0,561 / 0,914 ở phần 1–5. Ở phần 1, 3, 4, 5
  không mức p thô nào ra AUTO. Ở phần 2, p thô = 0 cho 0,077 < 0,08, tức là ra AUTO.
- Kiểm trên `off-tau05/hybrid` (gói kết quả Dương gửi 16/11): ở phần 2 có đúng 2 lá rơi vào trường hợp này, HB12-q1 và HB12-q2. Cả hai
  có nhãn ESCALATE_L2 và p thô 0, và chỉ không bị tự xử lý vì `kb_gap = true` nên D-34 hạ AUTO về HITL.
- Vậy 0/24 không cho biết LLM phân biệt tốt hay không: ở 4/5 phần, số bỏ sót bằng 0 dù LLM trả lời thế nào; ở phần còn lại, hai ca
  LLM trả lời sai hẳn (p = 0 cho ca cần L2) chỉ được chặn nhờ D-34. Thêm thẻ chỉ làm hẹp cận trên của một số gần như đã biết trước.
- *(Sửa 16/11 chiều, trước khi duyệt và commit: bản đầu ghi "lớp LLM không bao giờ tự xử lý", sai ở phần 2.)*

Câu hỏi đáng đo là câu đứng trước việc hiệu chỉnh: **p thô của lớp LLM có mang tín hiệu nào để tách ca tự xử lý được với ca cần người
không?** Có tín hiệu thì hiệu chỉnh có ý nghĩa khi đủ dữ liệu. Chưa thấy tín hiệu thì chưa đủ bằng chứng để cho lớp LLM tự xử lý, nên
giữ mặc định an toàn (luôn chuyển người); kết quả đó không chứng minh LLM không có tín hiệu. *(Sửa 16/11, mục 10.)*

## 2. Câu hỏi và giả thuyết

- **Câu hỏi:** trong các yêu cầu hành động mà không luật nào khớp (đi lớp LLM của M5), p "cần người" do B14 ước lượng (sampling_k5:
  tỉ lệ phiếu "cần người" trong 5 lần hỏi) có xếp ca cần người (nhãn HITL hoặc ESCALATE_L2) cao hơn ca tự xử lý được (nhãn AUTO) không?
- **Chỉ số chính:** AUC của p thô, dương = nhãn khác AUTO.
- **H0:** AUC = 0,5 (không có tín hiệu). Không đặt giả thuyết một phía trước.

## 3. Dữ liệu

- **Khung tình huống:** `scripts/eval/bo_sung_rq1/khung.py`, chạy trên nhánh này (= tag `v1.0-freeze`, 20 luật, seed bản đo):
  - liệt kê mọi tổ hợp (người gửi, hành động, đối tượng, người được làm hộ) dựng được từ `mock_services/seed.json`;
  - giữ tổ hợp không luật nào khớp, chấm bằng chính `scripts/rule_coverage.py` (trên bộ cũ ra 66 thẻ đi lớp LLM, khớp số đã báo cáo);
  - bỏ tổ hợp đã có trong `eval/the100`;
  - bỏ người gửi có OTP hoặc gây đổi người duyệt sang Trưởng BP có OTP (`it_mgr01`, `l1_01`, `l1_lead`; đối tượng `l1_01`, `svc_backup`),
    vì harness lỗi 401 ở các ca này (Bảng L.19).
- **Bốn nhóm** theo quan hệ người gửi ↔ người bị tác động. Quan hệ không tự nhiên bị loại: IT làm hộ người trong IT; người ngoài IT làm
  hộ người khác phòng mà không phải cấp trên trực tiếp.

  | Nhóm | Quan hệ | Tài khoản | Quyền thư mục | VPN | Phần mềm | Tổng |
  |---|---|---|---|---|---|---|
  | A | Nhân viên IT (L1/L2) làm hộ người ngoài IT | 6 | 5 | 3 | 3 | 17 |
  | B | Trưởng phòng làm hộ người cùng phòng | 2 | 4 | 3 | 2 | 11 |
  | C | Nhân viên nhờ cho đồng nghiệp cùng phòng hoặc cấp trên | 5 | 3 | 2 | 2 | 12 |
  | D | Tự làm cho mình mà không luật nào khớp | 2 | 2 | — | — | 4 |

  Nhóm D chỉ có 4 tổ hợp khác nhau; B/tài khoản chỉ có 2 người khác nhau.
- **Rút mẫu:** ngẫu nhiên trong từng ô nhóm × loại, hạt giống `20261116`. Hai tình huống không trùng người gửi, loại việc và người bị
  tác động. Rút thêm 3 dòng dự phòng mỗi nhóm.
  - Chạy lại script ra đúng cùng `khung.csv`, sha256 `aad78832…`, 44 dòng chính và 9 dòng dự phòng.
- **Mỗi tình huống một thẻ** (một câu đầu và tối đa 3 câu trả lời). Mọi thẻ có `at` = thứ Tư 18/11/2026 10:00 (trong giờ hành chính).
- **Người viết không gán nhãn; người gán không viết.** Tuấn Anh chốt 16/11:
  - viết: Quân, Tuấn Anh;
  - gán mù: Dương, Duy Anh, cặp đã gán bộ 100 thẻ, giữ tách vai D-43 (người xây M5 không gán).
- **Dòng không tự nhiên:** người viết đánh "x" và để trống câu. Dòng đó được thay bằng dòng dự phòng **cùng nhóm**, theo thứ tự mã. Hết
  dự phòng thì nhóm đó thiếu thẻ và báo đúng như vậy, không rút thêm sau khi đã thấy nhãn.
- **Lấy thêm thẻ theo lớp nhãn:** nếu sau khi gán, một lớp (AUTO hoặc cần người) có dưới 8 tình huống, được viết thêm từ dòng dự phòng
  **trước khi chạy**. Lấy mẫu theo lớp nhãn không làm lệch AUC. Không thêm thẻ sau khi đã chạy.

## 4. Nhãn

- Ba nhãn AUTO / HITL / ESCALATE_L2, tiêu chí ở `HUONG-DAN-GAN.md`: 3 câu tự hỏi và 5 điểm đã chốt 22/10. Tiêu chí giữ nguyên như bộ
  cũ để nhãn hai bộ cùng nghĩa.
- Gán một lượt trên đủ bộ, thứ tự xáo trộn (`dung_the.py phieu-gan`, hạt giống `20261117`). Không gán thử trước: thời gian không đủ cho
  hai lượt. Hai người gán đã dùng tiêu chí này ở đợt 2.
- κ tính bằng `app.eval.stats.agreement`. Báo κ, đồng ý thô và PABAK; không đặt ngưỡng chặn.
- **Phân xử:** ca lệch thì hai người gán trao đổi bằng lý do, không có người khác lái. Vẫn lệch thì lấy nhãn chặt hơn
  (ESCALATE_L2 > HITL > AUTO), như luật phân xử 18/10. Ghi số ca lệch, số ca thống nhất qua trao đổi, số ca lấy nhãn chặt hơn.
- **Khoá:** `dung_the.py the` dựng thẻ YAML vào `eval/bo-sung-rq1/the/`, ghi `tinh-huong.json` và `KHOA.md` (sha256 từng file và
  `dataset_sha256`), rồi tự kiểm:
  - mọi thẻ đi lớp LLM theo rule_coverage, 0 cảnh báo lệch seed;
  - loader của harness nạp đủ, đủ nhãn.

  Commit `KHOA.md` và thẻ **trước khi chạy**.

## 5. Cách chạy

- Stack dựng từ nhánh `do-bo-sung-rq1`. Nhánh chỉ thêm file so với `bf94df2`, `backend/`, `config/` và `mock_services/` giống hệt.
- Cấu hình như lượt S1 cũ (run `95b5a579ec7e`):
  - `.env`: `EVAL_MODE=true`, `LLM_CACHE_MODE=eval`, `STRATEGY=hybrid`, `APPROVAL_SLA_MINUTES_DEV=2`, `B2_CLASSIFIER_MODE=review`,
    `B2_TAU_REVIEW=0.9999`, `INTENT_MODEL_DIR` rỗng;
  - runner: `--strategy hybrid --split test --timeout-s 300 --prob-method sampling_k5`.
- **Giả lập giữ nguyên trong cả lượt:**
  - mọi thẻ đặt `approver_decision = reject`. Chỉ đo p ở điểm log 4, trước bước duyệt; từ chối thì không thẻ nào ghi vào giả lập,
    nên dữ kiện thẻ sau đúng như lúc gán nhãn;
  - chạy `make seed` ngay trước lượt để giả lập về đúng `seed.json`.
- **Một lượt, trong giờ hành chính** (T2–T6, 08:11–17:49; runner bỏ ca trong ±10 phút quanh biên giờ).
  - `--resume` chỉ dùng cho ca `skipped_hours`.
  - Ca `timeout` hoặc `error` không chạy bù (như lần trước): đếm và báo.
- **Người chạy:** Dương. Tuấn Anh không chạy.
- Model LLM: `manifest.config.llm_roles` so với S1 cũ. DeepSeek có thể đã đổi bản từ 29/10, nên khác thì ghi là lệch (mục 10), không
  dừng.
- **Không** áp B2 offline τ 0,50 cho bộ mới. τ chỉ quyết ca nào tới M5, không đổi p của ca đã tới M5. Bộ cũ so cùng τ chạy 0,9999
  (tập độ nhạy RQ2: 56 lá, 51 cần người / 5 AUTO).

## 6. Cách tính (`scripts/eval/bo_sung_rq1/phan_tich.py`)

- **Mẫu:** lá đã nhãn, có route, `decided_by = llm`, có `raw_prob`, `p_method = sampling_k5`. Lá bị loại được đếm theo lý do:
  - chưa nhãn;
  - không tới M5 (bị ngắt hay không);
  - luật quyết;
  - lớp LLM không có p.
- **Chính:** AUC của p thô trên bộ mới; KTC 95% bootstrap theo tình huống (họ), 2.000 lần, hạt giống 20260925, khoảng phân vị.
- **Đọc kết quả:**

  | Điều kiện | Kết luận |
  |---|---|
  | Một lớp dưới 5 lá | "không đủ dữ liệu", không đọc AUC |
  | Cận dưới > 0,5 | "có tín hiệu" |
  | Cận trên < 0,5 | "ngược chiều" |
  | Còn lại | "chưa thấy tín hiệu" |

- **Phụ (chỉ mô tả, không kết luận):**
  1. Bảng p (0; 0,2; …; 1) × nhãn.
  2. Điểm vận hành không hiệu chỉnh "tự xử lý khi p ≤ c và không thiếu căn cứ (`kb_gap`)", c ∈ {0; 0,2}:
     - số ca AUTO được tự xử lý, kèm KTC Clopper–Pearson hai phía;
     - số tình huống cần người bị tự xử lý, kèm cận trên Clopper–Pearson một phía 95%.
  3. S1 cũ riêng và gộp mới + cũ, cùng các chỉ số trên.
  4. Độ nhạy theo nhãn: AUC trên các tình huống hai người gán khớp ngay từ đầu.
  5. *(Thêm 16/11, mục 10)* Tỉ lệ nhãn AUTO trên mọi thẻ đã khoá, kèm Clopper–Pearson hai phía.
  6. *(Thêm 16/11, mục 10)* Ở mỗi c, số tình huống cần người có p ≤ c **không áp D-34** (sai sót của riêng LLM), kèm cận trên một phía.
  7. *(Thêm 16/11, mục 10)* KTC của AUC khi bootstrap theo người gửi thay cho theo tình huống.
- "Chưa thấy tín hiệu" và "không đủ dữ liệu" đều đọc là "chưa đủ bằng chứng; giữ mặc định an toàn", không đọc là "LLM không có tín hiệu".
- Sau khi thấy số, không đổi chỉ số, ngưỡng đọc, mẫu hay cách loại.

## 7. Cam kết báo cáo

- Báo đúng số dù kết quả xấu ("chưa thấy tín hiệu" hay "ngược chiều" vẫn là kết quả). Mọi số đi kèm `run_id`, `dataset_sha256`, commit
  và sha256 của `predictions.jsonl`.
- Ghi rõ đây là đo **sau** bản đo chính, trên bộ mới nhỏ, cùng nhóm người viết và gán. Không gộp vào số RQ1 chính của báo cáo; đưa vào
  phụ lục và slide dưới tên "đo bổ sung".

## 8. Không đo

- Cận trên tỉ lệ bỏ sót sau hiệu chỉnh: lý do ở mục 1.
- Hiệu chỉnh và ngưỡng mới: 5 lá âm của bộ cũ không đủ để fit. Nếu có tín hiệu, đây là hướng phát triển.

## 9. Lịch và điểm dừng

| Mốc | Việc | Ai |
|---|---|---|
| T2 16/11 tối | Commit bản này + script; phát `phieu-viet.xlsx` | Tuấn Anh |
| T3 17/11 trưa | Người viết nộp phiếu viết; dựng phiếu gán; phát phiếu gán | Quân, Tuấn Anh |
| T3 17/11 tối | Hai người nộp bài gán; gộp nhãn, phân xử | Dương, Duy Anh |
| T4 18/11 sáng | Dựng thẻ, tự kiểm, commit `KHOA.md` + thẻ | Tuấn Anh |
| T4 18/11 chiều (trong giờ) | Chạy một lượt; phân tích | Dương |
| T5 19/11 | Dự phòng nếu T4 không chạy được; viết kết quả | Dương, Duy Anh |
| **T6 20/11** | **Dừng cứng.** Chưa có số thì giữ kết quả cũ, ghi là hướng phát triển | — |

- Chạy theo lịch, không chờ ý kiến thầy (Tuấn Anh chốt 16/11). Kết quả đưa vào phụ lục "đo bổ sung", tách khỏi số RQ1 chính.
- Vai viết và gán như mục 3 (Tuấn Anh chốt 16/11).
- Trước khi chạy, kiểm trần chi phí tài khoản DeepSeek.
- Bắt đầu lượt trước 16:00 để cả 44 thẻ xong trước biên 17:49 (mục 10, ý 6).

## 10. Thay đổi sau khi ghi trước

**16/11, khoảng 17:00 — trước khi có câu viết và trước khi có nhãn.** Lý do: phản biện độc lập (agent chỉ đọc) và Tuấn Anh đã chốt
"cứ làm". Bản trước: commit `cba608a`.

1. **Dự báo lớp AUTO quá ít.** 40/44 tình huống thuộc nhóm làm hộ (A–C). Ở bộ 100 thẻ, 40 thẻ làm hộ có nhãn chốt 34 HITL, 6 L2,
   0 AUTO; `HUONG-DAN-GAN.md` câu 2 coi "người bị tác động không phải người xin" là HITL. Nhóm D (tự làm cho mình, không luật nào khớp)
   chỉ có 6 ứng viên trong cả seed. Vì vậy lớp AUTO nhiều khả năng dưới 5 lá và AUC sẽ ra "không đủ dữ liệu". **Không đổi khung:** khung
   đã phát cho người viết, và đổi khung theo dự báo nhãn là chọn mẫu theo kết quả. Bản thân điều này là một phát hiện: trong vùng không
   luật nào phủ dựng được từ seed, gần như mọi tình huống là làm hộ người khác.
2. **Thêm ba kết quả phụ** (mục 6, ý 5–7; đã có trong `phan_tich.py` ở commit này):
   (a) tỉ lệ nhãn AUTO trên thẻ đã khoá, kèm Clopper–Pearson hai phía — trần tự động hoá mà lớp LLM có thể thêm trong vùng này;
   (b) số tình huống cần người có p ≤ c không áp D-34 — số ca LLM sẽ cho tự xử lý sai nếu được phép, như HB12-q1/q2 ở bộ cũ;
   (c) KTC của AUC bootstrap theo người gửi — nhóm A chỉ có 2 người gửi, nhiều tình huống gần giống nhau.
3. **Sửa câu đọc kết quả** (mục 1, mục 6): bỏ câu "không có tín hiệu thì luôn chuyển người là lựa chọn đúng". KTC chứa 0,5 chỉ cho
   biết chưa đủ bằng chứng; trên bộ cũ AUC điểm 0,767 nhưng KTC theo họ khoảng [0,42; 0,97] cũng đọc là "chưa thấy tín hiệu".
4. **Vẫn chạy khi lớp AUTO dưới 5 sau khi gán:** khi đó (b) là số an toàn chính của đợt đo; chi phí một lượt nhỏ.
5. **Người viết:** Quân viết thêm `SB41`–`SB44` (nhóm D, nguồn AUTO chính) và `SD01`–`SD04`; Tuấn Anh viết `SB23`–`SB40` và
   `SD05`–`SD09`. Người xây M5 không viết nhóm D. Mọi dòng dự phòng viết xong cùng lúc với dòng chính, trước khi phát phiếu gán, để
   người viết không thấy nhãn. Quy tắc "lấy thêm thẻ theo lớp nhãn" (mục 3) giữ nguyên; nếu dùng, các dòng dự phòng được gán ở một
   phiếu gán thứ hai bởi cùng hai người, trước khi chạy. Cả 9 dòng dự phòng thuộc nhóm A–C nên quy tắc này khó cứu lớp AUTO.
6. **Giờ chạy:** bắt đầu trước 16:00. Lượt S1 cũ chạy 16:40–17:36, sát biên ±10 phút quanh 17:49.
7. **Giới hạn đã biết:** `phan_tich.py` chỉ so tên model trong manifest (`deepseek-flash`); nhà cung cấp đổi model bên dưới cùng tên
   thì không phát hiện được. Ghi giờ chạy để đối chiếu thông báo đổi model của DeepSeek nếu có.

**18/11, khoảng 20:45 — sau khi nhận phiếu viết, trước khi phát phiếu gán (chưa có nhãn nào).** Tuấn Anh chốt ý 2 và 3 lúc khoảng 20:45; ý 4 là lịch đề xuất, đã ghi lên
trang kế hoạch của nhóm.

1. **Phiếu viết đủ hai phần lúc 18/11 tối, trễ khoảng một ngày so với hạn trưa 17/11.** Quân lưu file xlsx 17/11 18:15. Phần Tuấn
   Anh viết trên Google Sheet (xong 18/11 tối), khác mục "điền thẳng trên file" của `HUONG-DAN-VIET.md`; Claude chép nguyên văn vào
   cùng một `viet.xlsx` (đã so từng ô với hai file gốc: 53 dòng, 0 ô lệch, cột xám giữ nguyên), không sửa chữ nào.
2. **Bỏ "x" ở 9 dòng của Tuấn Anh** (`SB24`, `SB30`, `SB31`, `SB33`, `SB34`, `SB35`, `SD07`–`SD09`). Tuấn Anh đánh "x" nhưng vẫn viết
   câu. Giữ "x" thì nhóm C còn 7/12 (cả 3 dòng dự phòng nhóm C cũng "x") và `dung_the.py` dừng. Các tình huống này không thuộc loại
   "không ai làm thế" ở `HUONG-DAN-VIET.md` mục 4: nhóm C theo thiết kế gồm nhân viên nhờ cho đồng nghiệp hoặc sếp. Đổi trước khi có
   nhãn, theo một tiêu chí đã ghi sẵn, nên không phải chọn mẫu theo kết quả. Ghi chú "x" gốc giữ ở cột "Ghi chú" của `viet.xlsx`.
3. **Kiểm kỹ thuật trước phiếu gán:** 10 câu của Quân thiếu nguyên văn thông tin mà bản đo bắt buộc phải thấy trong câu
   (`config/slots.yaml`: `target_user`, `resource_path` phải có thật trong câu): `SB01`, `SB04`, `SB05`, `SB07`–`SB11`, `SB20` thiếu mã
   người được làm hộ (chỉ có tên, hoặc gõ nhầm mã); `SB41` thiếu đường dẫn thư mục. Bản đo chưa có D-72 (sửa lỗi làm nhầm người), nên
   thiếu mã thì hệ thống có thể dựng hành động cho chính người gửi, tức đo một việc khác việc đã gán nhãn; hoặc hỏi lại mà thẻ không có
   câu trả lời và ca mất sau 300 giây. Quân tự bổ sung vào câu của mình, không ai gợi ý chữ, trước khi phát phiếu gán. Các câu còn lại
   đủ các thông tin trên (kiểm bằng script chỉ in mã dòng, không in câu); 0 câu trùng nguyên văn với 199 câu của bộ 100 thẻ.
4. **Lịch mới** (dừng cứng T6 20/11 giữ nguyên): gán T5 19/11 trước 12:00; gộp nhãn, phân xử T5 trưa; dựng và khoá thẻ T5 khoảng
   14:00; Dương chạy T5, bắt đầu trước 16:00; không kịp thì T6 20/11 sáng.

**19/11, khoảng 14:30 — sau khi gán nhãn và phân xử, trước khi chạy.** Ghi lại diễn biến; không đổi khung, tiêu chí hay cách tính.

1. **Phiếu gán:** Claude nhận hai phiếu lúc 13:46 (hạn 12:00), qua Tuấn Anh. Cả hai đủ 44/44 dòng, đúng thứ tự, không sửa ô nội dung,
   nhãn chỉ dùng 3 giá trị, dòng nào cũng có lý do, không dòng nào đánh "Mơ hồ". sha256: Dương `53e84f3c…`, Duy Anh `02639f8a…`.
2. **Đồng ý (mục 4):** κ = 0,425; đồng ý thô 0,818; PABAK 0,727; 8 ca lệch. Script in `ket_luan: KHONG_DAT`, nhưng mục 4 đã ghi "không
   đặt ngưỡng chặn", nên vẫn đi tiếp và báo đủ ba số. Trong 8 ca lệch, 6 ca là HITL so với ESCALATE_L2 (cùng phía "cần người", không
   đổi nhãn nhị phân của AUC); 2 ca `SB41`, `SB42` là AUTO so với HITL. Nếu tính nhị phân (AUTO / cần người): đồng ý 42/44, κ 0,645
   (số phụ, không ghi trước).
3. **Phân xử:** Claude dựng file 8 ca lệch kèm nhãn và lý do của cả hai, Tuấn Anh gửi lại cho hai người, không góp ý về nhãn. Claude có
   ghi một dòng kiểm dữ liệu ở `SB02`: lý do của Dương nói "xem quyền" trong khi hành động của dòng là "gia hạn quyền". Ghi chú này
   chỉ so với cột Hành động; câu đầu của `SB02` có hỏi "Nv001 đang có những quyền gì… thì gia hạn", nên lý do của Dương có thể không
   phải dán nhầm, và ghi chú có thể đã tác động tới trao đổi ở ca này (kết quả HITL, trùng nhãn Duy Anh).
   Kết quả: 8/8 ca thống nhất qua trao đổi, 0 ca phải lấy nhãn chặt hơn. Nhãn cuối: AUTO 4 (`SB41`–`SB44`, đều nhóm D), HITL 33,
   ESCALATE_L2 7. `phan-xu.csv` sha256 `376310c2…`.
4. **Lớp AUTO có 4 tình huống (< 8, < 5):** không viết thêm thẻ dự phòng. Cả 9 dòng dự phòng thuộc nhóm A–C (ý 5 của mục này, 16/11)
   nên không thêm được ca AUTO, và mỗi thẻ thêm phải qua phiếu gán thứ hai, không kịp trước giờ chạy 16:00. Theo ý 4 (16/11), vẫn chạy;
   kết quả (b) là số an toàn chính, AUC nhiều khả năng ra "không đủ dữ liệu".
5. **Nguy cơ mất độc lập của người gán:** 18/11 lúc 23:08, trước khi gán, Dương nhắn trong nhóm chung rằng sẽ gán "full HITL" và nêu
   "yêu cầu hộ ở hệ thống mình auto chuyển lên xem xét"; Duy Anh đã đọc tin này. Kiểm sau khi nhận phiếu:
   - nhãn của Dương không phải toàn HITL: 38 HITL, 4 ESCALATE_L2, 2 AUTO;
   - không lý do nào của hai người nhắc tới cách hệ thống xử lý;
   - không có câu lý do nào trùng nguyên văn giữa hai người;
   - 34/44 dòng của Dương dùng cùng một lý do, "Người gửi không phải chính chủ, cần xác minh", đúng câu 2 của `HUONG-DAN-GAN.md`.

   Không loại trừ được ảnh hưởng của tin nhắn lên nhãn. Báo cáo ghi điều này là giới hạn của đợt đo.
6. **Khoá:** `dung_the.py the` dựng 44 thẻ, dòng kiểm: `rule_coverage 100% đi lớp LLM, 0 cảnh báo seed; dataset loader nạp đủ, đủ nhãn`.
   `dataset_sha256` = `ad8ad99e29375d41af15c3838f00d69adf753b2165419c1b089949776291ffdd` (chi tiết ở `KHOA.md`).
