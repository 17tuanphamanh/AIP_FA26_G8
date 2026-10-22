"""M8 — groundedness offline của câu trả lời B10 (G11; huong-dan 17.4, B10 mục 9 và 11; P2 mục 6 `eval_groundedness`).

Luồng: `answers.jsonl` → tách ý BẰNG CODE (`split`) → LLM chấm từng ý có được các đoạn ĐÃ DẪN hỗ trợ không (`judge`) → tỉ lệ ý được
hỗ trợ + citation precision (`scoring`) → mẫu 30 ca cho người soát + độ đồng thuận LLM–người (`review`). Chỉ import được khi
`EVAL_MODE=true` (qua `app.eval`). Thu thập `answers.jsonl` từ DB/Qdrant và đấu nối gateway thật là việc của mốc G.

Định nghĩa [Đề xuất] — repo KHÔNG có định nghĩa nào (huong-dan 17.4 và B10 chỉ gọi tên; P8 v1.4 không nhắc groundedness). P6 sẽ đưa
vào P8:
- **Ý được hỗ trợ**: verdict `supported` = các đoạn được dẫn nói rõ/suy ra trực tiếp TOÀN BỘ ý. `partial` báo riêng, KHÔNG tính là
  hỗ trợ. Tỉ lệ ý được hỗ trợ = ý `supported` ÷ tổng ý (gộp mọi ca; báo thêm trung bình theo ca).
- **Citation precision** = số cặp (ca, đoạn được dẫn) mà đoạn đó là bằng chứng `supported` của ≥ 1 ý trong ca ÷ tổng số cặp
  (ca, đoạn được dẫn). Đoạn được dẫn mà không có trong `chunks` đầu vào không chính xác (và được đếm riêng). Cách tính theo tinh
  thần citation precision/recall của ALCE (Gao và cộng sự, 2023) — [Suy luận] từ kiến thức ngoài repo; tỉ lệ ý được hỗ trợ chính là
  "citation recall" của ALCE.
- Ca `cannot_answer` ngoài mẫu số (đếm riêng); ca không có trích dẫn hợp lệ: mọi ý không được hỗ trợ, gắn cờ `no_citation`; lỗi chấm
  (LLM lỗi, sai hợp đồng, bằng chứng bị cắt) ghi `errors.jsonl`, ngoài tỉ lệ, lệnh thoát mã 3 — lỗi hệ thống không phải kết quả rỗng.

GIỚI HẠN (đọc trước khi dùng số):
1. **Tách ý bằng code**: mỗi bước đánh số/gạch đầu dòng là một ý; văn xuôi tách theo câu. Câu ghép nhiều mệnh đề vẫn là MỘT ý (ý
   "nửa đúng nửa sai" ra `partial`); dòng dẫn dắt kết thúc bằng ":" bị bỏ; ý xã giao ("Chúc bạn thành công") không lọc được và bị chấm
   như ý thường → kéo tỉ lệ xuống. Không hỗ trợ bảng markdown.
2. **Người chấm cùng model với người viết** (cấu hình A: fast = strong = một model; `eval_groundedness` dùng vai trò strong như
   `b10_answer`) → có thể thiên vị cùng họ. Mẫu người soát là phép kiểm, không phải bảo đảm.
3. Chỉ chấm trên các đoạn ĐÃ DẪN: ý đúng theo KB nhưng không dẫn bị tính là không được hỗ trợ (đo chất lượng trích dẫn, không đo
   "đúng sự thật"). Bằng chứng bị gateway cắt → lỗi, không đoán.
4. Độ đồng thuận tính trên MẪU (mặc định phân tầng, cố ý lấy nhiều ca có ý không được hỗ trợ): κ và tỉ lệ khớp của mẫu không ngoại suy
   thành tỉ lệ của toàn bộ; 30 ca → khoảng tin cậy rộng.
5. Bản offline — không phải kiểm chứng online trước khi gửi (Nên có, B10 mục 13).
"""
