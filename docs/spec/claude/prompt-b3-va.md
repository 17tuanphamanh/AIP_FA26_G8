# Prompt chặng B3-VA (v3) — tách ý có kiểm "dính nhau"

*18/10/2026, 03:05. Prompt cho phiên B3-VA (D-55, hướng "tách có kiểm dính nhau" Tuấn Anh chọn rạng sáng 18/10), đã soát lại với code `33b7484`. Không dùng bản 00:58. Dán từ dòng "NHIỆM VỤ" tới hết phần "MỐC".*

---

NHIỆM VỤ: B3-VA — câu nhiều ý có ý không chắc: vẫn tách như hiện nay, NHƯNG chuyển cả câu khi ý không chắc "dính" vào ý chạy được. Tên chặng: B3-VA.

NGỮ CẢNH (đã kiểm trên code `3cf0d18`; HEAD `33b7484` chỉ đổi `PROGRESS.md` và bộ câu cổng 5; đừng đổi):
- Code hiện tại đã phán TỪNG ý (T20b; chốt 13/10 "ý lẫn = tách"; D-49; phase5 bảng 5.2.2–5.2.3). `backend/app/graph/nodes/b03_classify.py`:
  - `_verdict` theo thứ tự cố định: `out_of_scope` → `split_span_invalid` → `confidence < TAU_INTENT` (`intent_low_confidence`) → intent chưa bật → chạy được.
  - Câu ≥ 2 ý (đếm MỌI ý, kể cả ngoài phạm vi — Q-3f-6) có ≥ 1 ý chạy được → `_split` tách MỌI ý; ý không chạy được thành con đóng ngay E1 với lý do của ý đó.
  - 0 ý chạy được → `_whole_e1` (cả câu E1, lý do của ý đầu tiên trong phạm vi).
  - `_splits()` dùng cho chạy lại cùng lượt (Q-T20b-12): lần trước đã tách mà lần này không → `SplitChanged` (E9 cha).
- Test đang ghim, phải giữ xanh, không sửa kỳ vọng:
  - `test_t20b_split.py` v1–v9, đặc biệt `test_v4_low_confidence_child_e1_other_runs`, `test_v2_one_runnable_one_out_of_scope_splits`, `test_v3_no_runnable_intent_whole_sentence_e1`, `test_v8_single_intent_unchanged`;
  - `test_b03_classify.py::test_q3f6_out_of_scope_request_is_second_intent`;
  - `test_t20b_flows.py` (tc32, tc34, tc35, tc36, tc12r).
- Đặc tả nhánh `B03-B05` §2, §5.1 (mã giả dòng 355 `len(in_scope) == 1 and …`) và §10 còn là bản TRƯỚC T20b. KHÔNG dùng làm nguồn; nguồn là phase5 5.2.2–5.2.3 và code.
- Nguyên tắc: không chắc thì chuyển người; ưu tiên giảm bỏ sót hơn giảm chuyển thừa.
- Không đụng: M5, B12, B17, đường model B3a và cascade (chưa có code), giá trị `TAU_INTENT`, prompt `b03_classify`, schema `ClassifyOut`, tin E1 gửi người dùng, `REASON_DETAILS` (không thêm mã lý do), `audit/handoff.py` (chỉ gói 1 sửa file này).

VẤN ĐỀ: thiết kế tách hiện nay cho ý chắc chạy cả khi ý không chắc dính vào nó. Khi đó hệ thống có thể làm theo một cách đọc trong lúc chính đoạn chữ đó còn cách đọc khác, hoặc làm đúng việc người dùng nói KHÔNG muốn.

VIỆC CẦN LÀM:
1. **Điều kiện kích hoạt.** Chỉ xét khi đủ cả ba:
   - câu có ≥ 2 ý (theo `out.intents`);
   - verdicts có ≥ 1 ý chạy được;
   - có ≥ 1 ý verdict `intent_low_confidence`.

   Ý `out_of_scope`, `split_span_invalid` hay `intent_not_enabled` KHÔNG kích hoạt luật này; với chúng giữ nguyên D-49.
2. **Dính nhau** là khi có MỘT trong hai dấu hiệu. Viết thành hàm thuần `entangled(spans_low: Sequence[str], spans_run: Sequence[str], text: str) -> Literal["overlap", "negation"] | None`, đặt cạnh `phrase_in_text` trong `domain/slots.py` và dùng chung `_squash`.
   - Hàm chỉ nhận chuỗi: KHÔNG import `IntentItem` hay `RUNNABLE` vào `domain/` (hợp đồng import-linter `core-domain-pure` trong `.importlinter`). Việc chọn đoạn nào thuộc ý chạy được, ý nào `intent_low_confidence` làm ở `b03_classify.py`.
   - **(D1) `overlap`:** so trên `_squash(text)`, tức cùng chuẩn hoá với `phrase_in_text` (casefold + gộp khoảng trắng).
     - Đoạn của một ý `intent_low_confidence` giao với đoạn của một ý chạy được (≥ 1 ký tự), kể cả lồng nhau hay trùng hẳn, thì là dính. Hai đoạn chỉ KỀ nhau thì không phải dính. "Kề" = đoạn sau bắt đầu đúng tại vị trí đoạn trước kết thúc trên `_squash(text)`, không có ký tự nào xen giữa.
     - Đoạn của ý không chắc hoặc của ý chạy được xuất hiện ≥ 2 lần trong câu (không định vị được) cũng coi là dính.
   - **(D2) `negation`:** câu (`_squash(text)`) chứa một trong các cụm: có dấu "đừng", "không cần", "khỏi cần", "thay vì", "chứ không"; không dấu "khong can", "khoi can", "thay vi", "chu khong" (người dùng hay gõ không dấu; `_squash` chỉ casefold và gộp khoảng trắng, không bỏ dấu).
     - So theo ranh giới từ: `(?<!\w)…(?!\w)`.
     - Các cụm để thành hằng tuple ở một chỗ và có test.
     - KHÔNG thêm "dung" (trùng "dùng", "đúng", "dụng" khi bỏ dấu).
   - Kiểm D1 trước, D2 sau. Có dính thì trả về loại dính đầu tiên tìm thấy.
3. **Dính → cả câu E1, KHÔNG tạo con:**
   - goto `S_ESCALATED`, `next_node="b20_audit"`, `step="B4"`, `event="intent_low_confidence"`, `exit_code=E1`, `escalation_reason_detail="intent_low_confidence"`, giữ `reasoning_loops`;
   - không side effect `child_create`/`child_submit`, không `mark_parent_once`;
   - điểm log 1 giữ `children`/`verdicts` như `_whole_e1` đang ghi, thêm `entangled` (`"overlap"` | `"negation"`); `intent`/`confidence` là của ý `intent_low_confidence` ĐẦU TIÊN.
   - Nếu điểm log 1 có test ghim tập khoá thì nêu ở MẪU A trước khi thêm.
4. **`_splits()` phải dùng chung `entangled`.** Với ca dính, `_splits()` trả False. Như vậy lần chạy lại thấy cùng output không tạo con và không ném `SplitChanged`. Còn nếu lần trước đã tách mà lần này dính → `SplitChanged` (E9 cha) như quy tắc hiện có.
5. **Không dính → tách như hiện nay.** Con có verdict `intent_low_confidence` thêm `escalation_note` vào seed: "Một phần của yêu cầu nhiều ý (ticket cha <id cha>); phần khác đang được hệ thống tự xử lý — xem ticket cha trước khi trả lời người dùng."
   - `_why` đã nối sẵn `escalation_note`, nên KHÔNG sửa `audit/handoff.py`.
   - Ở MẪU A, kiểm `escalation_note` có trong schema state và đi qua seed của con (`ChildOps` chỉ kiểm `E1_FIELDS`). Không đi qua được thì DỪNG báo.
6. **QUAN SÁT — CHỈ BÁO, KHÔNG SỬA** (nêu trong PLAN, kèm có test nào ghim không):
   - (a) hai ý cùng chạy được mà chồng đoạn vẫn tách cả hai, nên có thể làm hai việc cho một đoạn chữ;
   - (b) con E1 loại khác (ngoài phạm vi, chưa bật, span hỏng) chưa có dòng toàn cảnh cho L2.

TEST (viết TRƯỚC code, từ prompt này; dùng khuôn `make_flow`/`classify(...)`, `reset_item`, `adobe_item`, `oos_item` của `test_t20b_split.py`):

*Unit:*

| Ca | Đầu vào | Kỳ vọng |
|---|---|---|
| a | 2 ý 0,9 + 0,9, đoạn tách rời | tách 2 con, như v1 |
| b | 2 ý 0,9 + 0,3, đoạn tách rời, không có cụm phủ định | tách: con 1 chạy, con 2 E1 `intent_low_confidence` (`test_v4` giữ XANH); seed con 2 có `escalation_note` đúng mẫu, seed con 1 không có |
| b1 | 0,9 + 0,3, đoạn của ý 0,3 LỒNG đoạn của ý 0,9 | cả câu E1 `intent_low_confidence`; 0 con; 0 side effect `child_*`; không `mark_parent`; `entangled == "overlap"` |
| b2 | như b1, nhưng hai đoạn giao đúng 1 ký tự | E1 |
| b2' | hai đoạn KỀ nhau: đoạn sau bắt đầu đúng tại chỗ đoạn trước kết thúc, không có dấu cách xen giữa | tách (biên) |
| b3 | 0,9 + 0,3, đoạn tách rời, câu có "đừng" | E1, `entangled == "negation"` |
| b3' | câu có "dùng" (không phải "đừng") | tách (không bắt nhầm vì khác dấu) |
| b3'' | 0,9 + 0,3, đoạn tách rời, câu không dấu có "khong can" | E1, `entangled == "negation"` |
| b3''' | câu không dấu có "dung" | tách |
| b4 | đoạn của ý 0,9 xuất hiện 2 lần trong câu | E1, `overlap` |
| c | 0,3 + 0,3 | cả câu E1, như v3 |
| d | 1 ý 0,6 | B6 |
| d' | 1 ý 0,5999 | E1 |
| d'' | 1 ý có chữ "đừng" | không đổi gì (luật chỉ áp khi ≥ 2 ý) |
| e | 0,6 + 0,9, chồng đoạn | tách (0,6 là đạt, không có ý `intent_low_confidence`) |
| f | 1 ý chạy được + 1 ý `out_of_scope`, chồng đoạn | tách như v2 |
| g | 1 ý chạy được + 1 ý `intent_not_enabled`, chồng đoạn | tách như v4 not_enabled |
| h1 | chạy lại cùng lượt: lần 1 dính (E1, không con), lần 2 cùng output | không `SplitChanged`, không tạo con |
| h2 | lần 1 tách, lần 2 LLM trả output dính | `SplitChanged` |

*Integration (ScriptedLLM, harness `test_t20b_flows.py`):*
- tc12r, tc32, tc34, tc35, tc36 xanh nguyên kỳ vọng. Đỏ thì BÁO (tên test, lý do), không tự sửa.
- Ca b1 qua harness: điểm log 1 có intents, `verdicts`, `entangled` (layer=llm); `escalations.reason_detail = intent_low_confidence`; notice E1 dùng mẫu cũ.

*Rà dữ liệu, chỉ báo số:* đếm số câu nhiều ý kích hoạt luật trong preset ScriptedLLM. Với bộ probe cổng 5 (`eval/probe/cong5-v1.jsonl`, 10 câu nhiều ý) chỉ đếm câu có cụm phủ định trên chữ: kết quả lượt 17/10 không có span hay confidence, muốn đếm đủ phải đọc DB lượt đó (cần stack — báo Tuấn Anh, không tự chạy). Bộ probe CHỈ ĐỂ ĐO: không chỉnh cụm từ hay luật theo bộ này.

*MUTATION (`scripts/mutation/mutate_b3va.py`, khuôn `mutate_t23a.py`, md5 + `git diff --stat`; bắt buộc trước commit; cả 7 phải đỏ đúng dự đoán):*

| # | Đột biến | Test phải đỏ |
|---|---|---|
| 1 | bỏ kiểm chồng đoạn | b1 |
| 2 | bỏ kiểm cụm phủ định | b3 |
| 3 | coi hai đoạn kề nhau là chồng (giao ≥ 0) | b2' |
| 4 | kích hoạt cả khi ý không chạy được là `out_of_scope`/`intent_not_enabled` | f hoặc g |
| 5 | `_splits` không dùng `entangled` | h2 (lần 2 dính mà không ném `SplitChanged`; h1 vẫn xanh vì `_split` tự kiểm dính) |
| 6 | bỏ `escalation_note` ở seed con | b |
| 7 | bỏ các cụm không dấu | b3'' |

TÀI LIỆU: không tự sửa file spec. Ghi vào mục "Spec cần sửa":
1. `B03-B05` §2 (sơ đồ), §5.1 (mã giả), §10 (bảng): đồng bộ theo phase5 5.2.2 (lệch có từ T20b), thêm dòng "câu ≥ 2 ý, ý không chắc dính ý chạy được → cả câu E1".
2. Phase5 bảng 5.2.2: thêm bước "dính nhau" sau phán từng ý. Bảng 5.2.3: seed con `intent_low_confidence` có `escalation_note`.
3. Nhật ký 1.7.

Số quyết định Tuấn Anh đã cấp: D-55. Soạn sẵn 3 dòng nội dung cho D-55 trong MẪU B2; không tự ghi vào decisions.md.

LUẬT PHIÊN: giữ nguyên các luật cũ, thêm các dòng sau.
- Luật cũ:
  - không đọc hay in `.env`; không `--no-verify`;
  - lệnh cần Docker thì báo Tuấn Anh chạy bằng `!`; KHÔNG đụng stack trước khi Tuấn Anh báo "stack rảnh"; không `down -v`;
  - stage đích danh; commit CỤC BỘ khi Tuấn Anh bảo, tiếng Việt không dấu, không dòng AI;
  - không gọi subagent trừ khi PLAN ghi tên và Tuấn Anh duyệt.
- Thêm:
  - Không đụng `config/llm.yaml` (chặng khác quản).
  - Không đụng `audit/handoff.py`.
  - `b03_classify.py` cũng là file gói 2 sửa (bộ nạp intent, `_classify` dòng 88–91), nên không chạy song song với gói 2 trong cùng thư mục. Ai commit sau thì rebase rồi chạy lại toàn bộ test B3/T20b.
  - MẪU A nêu mọi file chồng với gói 2 và với prompt `b03_classify`.
  - Chặng bắt đầu sau khi gói 2 commit (cùng file), trừ khi Tuấn Anh bảo làm trước.

DỪNG: MẪU A (plan: file sẽ sửa, input/output, ca test, mức verify đề xuất, kết quả kiểm `escalation_note` và khoá điểm log 1) → MẪU B1 (lint + unit xanh) → MẪU B2 (mutation 7/7 + tự kiểm + 3 dòng decisions) → Tuấn Anh bảo mới commit.

MỐC: phải gộp trước 18:00 21/10 (giờ cắt đổi hành vi). Đề xuất xong MẪU B2 trước 18:00 20/10 để kịp `verify` lúc 14:00 21/10. Không kịp thì DỪNG hỏi, đừng ép.

---

## Ghi chú cho Tuấn Anh (không dán cho phiên)

- Ước lượng agent khoảng 3–4 giờ (hàm thuần + test + mutation).
- Chạy ở thư mục chính, T2 19/10, sau khi gói 2 commit (cùng file `b03_classify.py`). 09:00 19/10 chưa có SHA của Duy Anh, hoặc gói 2 kẹt vì đo bộ nhớ, thì B3-VA làm trước, gói 2 rebase.
- Cụm không dấu (D2, ca b3'', mutation 7) là mặc định đã đặt 18/10 (đặc tả `claude/dac-ta-bat-2-model.md` mục 13); muốn bỏ thì bảo Claude gỡ trước khi dán.
