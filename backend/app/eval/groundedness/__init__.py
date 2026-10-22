"""M8 — groundedness offline của câu trả lời B10 (G11; huong-dan 17.4, B10 mục 9 và 11; P2 mục 6 `eval_groundedness`).

Luồng: `answers.jsonl` → tách ý BẰNG CODE (`split`) → LLM chấm từng ý có được các đoạn ĐÃ DẪN hỗ trợ không (`judge`) → tỉ lệ ý được
hỗ trợ + citation precision (`scoring`) → mẫu 30 ca cho người soát + độ đồng thuận LLM–người (`review`). Chỉ import được khi
`EVAL_MODE=true` (qua `app.eval`). Thu thập `answers.jsonl` từ DB/Qdrant và đấu nối gateway thật là việc của mốc G.

Nhãn: yêu cầu đo (offline, tách ý, LLM chấm, người soát 30 mẫu, báo tỉ lệ ý được hỗ trợ + citation precision) = **[Chốt 17.4]**; cách đo
dưới đây = **[Đề xuất 22/10]** (P8 v1.5 6.3.1; P6 chốt 16:40). Repo không có định nghĩa nào trước đó (huong-dan 17.4 và B10 chỉ gọi tên;
P8 v1.4 không nhắc groundedness).

Dữ liệu vào: CÂU HỎI THÔNG TIN (bộ `eval/retrieval` + các câu info của probe), chạy với LLM thật; KHÔNG dùng thẻ giả `[fake:…]`.
`family` BẮT BUỘC trên mỗi dòng (họ = câu hỏi gốc + các biến thể) — thiếu thì lỗi, không suy từ tiền tố `scenario_id`. Bộ câu truy hồi:
họ = `expected_doc_ids[0]` (thứ tự YAML), câu âm tính → họ = id câu (`probe-input`). Thu thập từ DB: `collect` (xem `collect.py`).
`chunks[].text` = mọi khối bằng chứng đã gửi `b10_answer` cho chunk được dẫn, GỒM cả chunk liền kề (D-24); nguồn khi thu thập:
`llm_calls.prompt_full` (EVAL_MODE) — việc của mốc G.

Định nghĩa:
- **Ý được hỗ trợ**: verdict `supported` = các đoạn được dẫn nói rõ/suy ra trực tiếp TOÀN BỘ ý. `partial` báo riêng, KHÔNG tính là
  hỗ trợ. Tỉ lệ ý được hỗ trợ = ý `supported` ÷ tổng ý (gộp mọi ca; báo thêm trung bình theo ca).
- **Citation precision** = số cặp (ca, đoạn được dẫn) mà đoạn đó là bằng chứng `supported` của ≥ 1 ý trong ca ÷ tổng số cặp
  (ca, đoạn được dẫn). Đoạn được dẫn mà không có trong `chunks` đầu vào không chính xác (và được đếm riêng). Cách tính theo tinh
  thần citation precision/recall của ALCE (Gao và cộng sự, 2023) — [Suy luận] từ kiến thức ngoài repo; tỉ lệ ý được hỗ trợ chính là
  "citation recall" của ALCE.
- Ca `cannot_answer` ngoài mẫu số (đếm riêng); ca không có trích dẫn hợp lệ: mọi ý không được hỗ trợ, gắn cờ `no_citation` (thực tế
  hiếm: `check_citations` của B10 chặn ca không trích dẫn thành E3, nên hầu như không tới được đây); lỗi chấm
  (LLM lỗi, sai hợp đồng, bằng chứng bị cắt) ghi `errors.jsonl`, ngoài tỉ lệ, lệnh thoát mã 3 — lỗi hệ thống không phải kết quả rỗng.

GIỚI HẠN (đọc trước khi dùng số):
1. **Tách ý bằng code**: mỗi bước đánh số/gạch đầu dòng là một ý; văn xuôi tách theo câu. Câu ghép nhiều mệnh đề vẫn là MỘT ý (ý
   "nửa đúng nửa sai" ra `partial`); dòng dẫn dắt kết thúc bằng ":" bị bỏ; ý xã giao ("Chúc bạn thành công") không lọc được và bị chấm
   như ý thường → kéo tỉ lệ xuống. Không hỗ trợ bảng markdown.
2. **Người chấm = model viết** (cấu hình A: fast = strong = một model; `eval_groundedness` dùng vai trò strong như `b10_answer`) →
   có thể thiên vị cùng họ. Mẫu người soát là phép kiểm, không phải bảo đảm: κ < 0,6 → `low_kappa` (agreement.json và khối
   `human_agreement` của summary.json báo cả tỉ lệ khớp lẫn κ); κ không xác định cũng gắn cờ. Manifest ghi model chấm, id/phiên bản/sha256
   prompt chấm.
3. Chỉ chấm trên các đoạn ĐÃ DẪN: ý đúng theo KB nhưng không dẫn bị tính là không được hỗ trợ (đo chất lượng trích dẫn, không đo
   "đúng sự thật"). Bằng chứng bị gateway cắt → lỗi, không đoán.
4. Độ đồng thuận tính trên MẪU (mặc định phân tầng, cố ý lấy nhiều ca có ý không được hỗ trợ): κ và tỉ lệ khớp của mẫu không ngoại suy
   thành tỉ lệ của toàn bộ; 30 ca → khoảng tin cậy rộng.
5. Bản offline — không phải kiểm chứng online trước khi gửi (Nên có, B10 mục 13).
"""
