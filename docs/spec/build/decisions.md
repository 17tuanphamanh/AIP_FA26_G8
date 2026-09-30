# Quyết định của nhóm — danh sách duy nhất

*Thuộc bộ `build/`. Đây là **nơi duy nhất** theo dõi trạng thái quyết định. Nhóm **tự quyết** mọi mục (không có vòng hỏi GVHD); mục nào đổi hành vi hoặc công nghệ so với tài liệu gốc thì **báo cáo** GVHD trong báo cáo tuần. `huong-dan-xay-dung-he-thong-2.md` Phase 0 gọi file này là `decisions.md`. Khi một mục được chốt: sửa cột "Trạng thái" ở đây, rồi áp patch tương ứng (nếu có) trong `claude/bo-sung-bo-tai-lieu-build.md`.*

*Cập nhật: 30/09/2026 (D-34, Q-4-A…U).*

**Nguyên tắc chốt (áp cho mục 1, 2, 3):**

1. Không phá thứ đã **[Chốt]** trong tài liệu gốc.
2. Với an toàn: chọn phương án **giảm False Negative** trước.
3. **Xây bản đơn giản trước, tối ưu sau:** bản đầu là phương án ít trạng thái/ít nhánh nhất; phương án "tối ưu" chỉ vào sau, sau một cờ cấu hình hoặc như một biến thể được đo, không sửa bản đầu.

---

## 1. Tài nguyên và việc nhóm tự chốt

| Mã | Việc | Đã chốt | Còn phải làm | Chặn từ | Trạng thái |
|---|---|---|---|---|---|
| N1 | Provider LLM, ngân sách | **Đa provider** qua `config/llm.yaml` (P2 mục 5): vai trò fast và strong có thể ở provider khác nhau; fast có chuỗi dự phòng sang provider khác hoặc model local. **Trần tổng ≤ 1.000.000 đ cho cả đồ án** (khoảng 38 USD, quy đổi lại theo tỉ giá lúc nạp). Kế hoạch chi ở mục 1.2 | Chọn model cụ thể cho fast/strong bằng probe (P2 mục 12) và điền bảng giá thật vào `pricing` | Phase 3 (chọn model) | Đã chốt hướng; model chọn ở Phase 3 |
| N2 | Phần cứng | 3 máy gaming (GPU NVIDIA) + 1 Mac. Phân vai ở mục 1.3. Nếu có ít nhất 1 máy ≥ 8 GB VRAM → **mức 1** (`huong-dan` mục 11): fast chạy local 7–8B 4-bit được | Chạy `nvidia-smi` trên 3 máy, ghi tên GPU + VRAM vào mục 1.3 | Phase 3 | 1/3 máy đã đo (RTX 4050 Laptop 6 GB, 28/09/2026) — chưa đạt mức 1; chờ 2 máy còn lại |
| N3 | Phân bố vận hành giả định (escalation rate có trọng số) | **70% thường ngày / 20% cần duyệt / 10% nhạy cao** + báo cáo độ nhạy với 60/30/10 và 80/15/5. Giải thích ở mục 1.4 | — | Phase 10 | Đã chốt |
| N4 | Đánh số 20 luật trong `policy.json` | Bảng R01–R20 ở mục 1.1; luật "VPN cho thiết bị chưa đăng ký" (tài liệu cũ ghi R22) là **R17** | — | Phase 4 | Đã chốt |
| N5 | Huấn luyện `intent-clf`, `injection-clf` | Nhóm tự huấn luyện trên **Kaggle + Colab** (P11). GPU T4/P100 không có bf16 → **train fp32** (không fp16). Model xuất ONNX lưu ngoài git (`*.onnx` bị ignore): GitHub Release hoặc Kaggle Dataset riêng tư, ghi link + sha256 vào `ml_models/<task>/<ver>/model_card.md`. Người phụ trách mặc định TV1 | — | Phase 1 (luồng dữ liệu) | Đã chốt |

### 1.1. Đánh số 20 luật (N4) [Đề xuất đánh số; nội dung luật = bảng Phần I mục 6.3 của NGU-CANH]

Giữ đúng các mã đã xuất hiện trong tài liệu: R01 (TC01), R04 (TC07), R07 (TC08), R12 (deny), R20 (TC02). Đủ 7 `allow` + 12 `approval_required` + 1 `deny` = 20.

| Mã | Loại | Nhóm | Luật |
|---|---|---|---|
| R01 | allow | Tài khoản | Reset mật khẩu cá nhân, tài khoản thường |
| R02 | allow | Tài khoản | Mở khóa tài khoản bị khóa do nhập sai |
| R03 | approval_required | Tài khoản | Tài khoản dịch vụ |
| R04 | approval_required | Tài khoản | Tài khoản quản trị |
| R05 | approval_required | Tài khoản | Tài khoản của người đã nghỉ việc |
| R06 | allow | Quyền | Xem quyền hiện có |
| R07 | approval_required | Quyền | Quyền mới vào dữ liệu nhạy cảm (`resource_sensitivity=high`) |
| R08 | approval_required | Quyền | Quyền quản trị |
| R09 | approval_required | Quyền | Vượt cấp quản lý |
| R10 | allow | Quyền | Gia hạn quyền cũ |
| R11 | allow | Phần mềm | Cài phần mềm trong danh mục duyệt sẵn |
| R12 | deny | Quyền | Cấp quyền cho tài khoản bị vô hiệu hóa vì lý do bảo mật |
| R13 | approval_required | Phần mềm | Ngoài danh mục |
| R14 | approval_required | Phần mềm | Có phí license |
| R15 | approval_required | Phần mềm | Cần quyền quản trị máy |
| R16 | allow | VPN | Kiểm tra trạng thái VPN |
| R17 | approval_required | VPN | Thiết bị chưa đăng ký *(tài liệu cũ: R22)* |
| R18 | approval_required | VPN | Ngoài giờ |
| R19 | approval_required | VPN | Nhân viên mới chưa qua thử việc |
| R20 | allow | VPN | Cấp lại cho thiết bị đã đăng ký |

**Chốt Phase 3 (3-Q2, `phase3-thiet-ke-chi-tiet.md` 11.2, 11.10):** R20 áp cho `renew_vpn_cert` và `reissue_vpn_access`, điều kiện `device_registered` ∧ `device_owner_is_requester` ∧ ¬`ctx.target_is_other`; R16 (`check_vpn_status`) đòi ¬`ctx.target_is_other`; R17/R18/R19 = `approval_required`. Thiếu fact → điều kiện sai.


Thứ tự số không ảnh hưởng kết quả: khớp cả `allow` và `approval_required` thì `approval_required` thắng, `deny` thắng tất cả (B12-B14 mục 10).

### 1.2. Kế hoạch chi LLM (N1)

**Nguyên tắc tiết kiệm (không đổi kiến trúc, chỉ dùng thứ P2 đã có):**

- Test tự động luôn dùng `ScriptedLLM` → 0 đ **[Chốt]**.
- Thực nghiệm dùng `LLM_CACHE_MODE=eval`: cùng một lời gọi chỉ trả tiền một lần, các chiến lược sau đọc lại cache **[Chốt P2 mục 8]**.
- B14 hỏi nhiều lần (k = 5) chỉ bật khi thực nghiệm, không bật khi dev.
- Fast chạy model local trên máy gaming khi có mức 1 (N2), API chỉ còn vai trò strong.
- Chọn model theo **chi phí mỗi ticket ≤ 0,03 USD** (tính bằng `llm_calls.cost_usd` sau probe), không chọn model mạnh nhất.

**Công thức ước lượng:** chi phí/ticket = Σ (số lời gọi × (token vào × giá vào + token ra × giá ra)). Một ticket điển hình: khoảng 4 lời gọi fast (~1.500 token vào, ~200 ra) + 1 lời gọi strong B10 + 5 lời gọi B14 (~4.000 vào, ~400 ra).

| Khoản | Trần | Ghi chú |
|---|---|---|
| Probe chọn model (Phase 3) | 5 USD | Probe intent 40 câu, JSON 200 lời gọi, p95 độ trễ trên 2–3 ứng viên mỗi vai trò |
| Chạy thật end-to-end Phase 3–7 | 8 USD | Chỉ các cổng phase; còn lại ScriptedLLM |
| Thực nghiệm Phase 8–10 | 15 USD | ≥ 2 lượt đầy đủ 150–180 kịch bản + chạy lại |
| Demo và bảo vệ | 3 USD | Bản bảo vệ chạy từ cache (`huong-dan` mục 13.1) |
| Dự phòng | 7 USD | |
| **Tổng** | **38 USD ≈ 1.000.000 đ** | Chặn cứng bằng `spend_cap` (P2 mục 5) |

### 1.3. Phân vai máy (N2) [Đề xuất]

| Máy | Vai trò | Ghi chú |
|---|---|---|
| Gaming #1 (VRAM lớn nhất) | Máy staging/demo: `docker compose` đủ dịch vụ + Ollama cho vai trò fast + ml-service dùng GPU | Thay VM thuê (`huong-dan` 13.1) nếu bật được liên tục; mở cho GVHD xem qua tunnel (ví dụ Tailscale/Cloudflare Tunnel). Không bật liên tục được thì vẫn thuê VM |
| Gaming #2, #3 | Dev + chạy thực nghiệm; huấn luyện dự phòng khi Kaggle/Colab hết lượt | RTX dòng 30/40 có bf16 |
| Mac | Dev backend/frontend, viết tài liệu | Không có CUDA: không huấn luyện, không chạy vLLM; Ollama và ONNX CPU vẫn chạy được |

| Máy | GPU | VRAM | Ghi khi đo |
|---|---|---|---|
| Gaming #1 (máy Tạ Duy Anh, WSL 2) | NVIDIA GeForce RTX 4050 Laptop GPU, driver 610.78, CUDA 13.3 | 6141 MiB (6 GB) — dưới ngưỡng 8 GB của mức 1 | 28/09/2026, kèm xác nhận cổng 2 |
| Gaming #2 | | | |
| Gaming #3 | | | |

### 1.4. Vì sao cần phân bố vận hành giả định (N3)

Bộ kịch bản do nhóm tự soạn cố ý có nhiều ca nhạy cảm và ca biên (khoảng 20% là TC09–TC12) để kiểm tra M5. Nếu tính escalation rate thô trên bộ này thì con số cao giả tạo, vì ngoài thực tế phần lớn yêu cầu là việc thường ngày.

Cách làm: tính escalation rate **riêng từng nhóm** (thường ngày / cần duyệt / nhạy cao), rồi cộng theo trọng số 70/20/10. Ví dụ: tỉ lệ escalate từng nhóm là 5% / 60% / 90% → có trọng số = 0,7×5% + 0,2×60% + 0,1×90% = 24,5%. Báo cáo cả số thô, số có trọng số, và độ nhạy với 60/30/10, 80/15/5 để hội đồng thấy kết luận không phụ thuộc một con số giả định. Luật cảnh báo > 40% (P9 luật 1) áp trên số có trọng số.

## 2. Quyết định thay cho câu hỏi GVHD (báo cáo, không hỏi)

Mã Q giữ nguyên để không vỡ tham chiếu. Mỗi mục: bản **xây trước** (vào code ngay) và hướng **tối ưu sau** (chỉ làm khi luồng chính đã qua cổng, luôn sau cờ hoặc dưới dạng biến thể được đo). Báo cáo GVHD trong báo cáo tuần; nếu GVHD góp ý khác thì chỉ đổi cờ/cấu hình, không viết lại.

| Mã | Vấn đề | Xây trước (đã chốt) | Lý do | Tối ưu sau | Chốt trước | Trạng thái |
|---|---|---|---|---|---|---|
| Q1 | TC09/TC10: luật hay LLM? | **Theo bảng luật**: TC09 khớp R17/R18, TC10 khớp R13/R14 → `approval_required`, `decided_by=rule`. Kết quả cuối không đổi (chuyển phê duyệt). Dữ liệu cho lớp LLM lấy từ TC37 + các họ kịch bản không khớp luật (`huong-dan` mục 8.2) | Luật cứng có quyền phủ quyết LLM **[Chốt]**; luật khớp chắc chắn không bỏ sót | Không cần | Phase 3 | Đã chốt |
| Q2 | L2 hoàn tất tay ca hết hạn duyệt (E6)? | **Không.** L2 chỉ chọn `reopened_as_new` (ticket mới, đi lại phê duyệt) hoặc `confirmed_denial` | L2 không có quyền duyệt **[Chốt 2.2]**; hết hạn duyệt không bao giờ tự thực thi | Không cần | Phase 7 | Đã chốt |
| Q3 | ActionPlan đổi sau duyệt | **Escalate L2 (E5)**, như tài liệu gốc | Ít nhánh nhất, không mở đường tự thực thi | Cờ `RERUN_M5_ON_NONSENSITIVE_CHANGE` (mặc định tắt): chạy lại M5 khi chỉ trường không nhạy cảm đổi (NGU-CANH Phần III mục 12.3 — Future Work) | Phase 4 | Đã chốt |
| Q6 | Ý nghĩa % objectives; 2 vai trò làm tối giản | Hiểu là **tỉ trọng công sức và dung lượng báo cáo**; thứ tự phase đã theo tỉ trọng này. Trưởng BP và L2 làm đủ mục "Phải có" của P10 | Không đổi phạm vi đã chốt | — | — | Đã chốt (báo cáo) |
| Q8 | Biến thể `hybrid_guarded` | **Code ở Phase 6** (một nhánh chiến lược), **chạy ở Phase 10** như phương án thứ 6 của RQ1, sau 5 phương án chính | Nhắm đúng False Negative (luật `allow` bỏ qua ngữ cảnh bất thường); chi phí thấp nhờ cache | Hết thời gian thì bỏ lượt chạy, không bỏ code | Phase 6 | Đã chốt |
| Q9 | Tỉ lệ chi phí bỏ sót / một lượt duyệt | **10:1 → `t_low*` = 0,1**, báo cáo độ nhạy 5/10/20 (đã có trong P8) | Nghiêng về an toàn; độ nhạy cho thấy kết luận không phụ thuộc một con số | — | Phase 3 | Đã chốt |
| Q10 | Chẩn đoán lại khi bổ sung slot (D-20) | **Cờ `REDIAGNOSE_ON_NEW_SLOT` tắt**, không thêm chuyển `S_CLARIFYING → S_DIAGNOSING` | Không thêm chuyển trạng thái khi chưa có số liệu cần | Bật cờ và đo số lượt hỏi lại TC06/TC11 nếu kịch bản cho thấy chẩn đoán cũ sai sau khi có slot mới | Phase 5 | Đã chốt |
| Q11 | Ticket L2 mở lại chạy từ đâu (D-26) | **Từ B1** | Ticket mới phải xác thực và dựng `intended_action` lại từ đầu **[Chốt E5]** | — | Phase 7 | Đã chốt |
| Q12 | Yêu cầu nhiều ý: một tin tổng hợp (D-31) | **Giữ một tin mỗi lượt**; chấp nhận chờ ý chậm nhất (tối đa SLA 30 phút) | Đúng câu chốt; khung tiến độ từng ý (P10) bù trải nghiệm | — | Phase 5 | Đã chốt (báo cáo) |
| Q13 | Đổi tên đề tài "Risk-Aware…" | **Giữ tên đã nộp trên Edunext**; dùng cụm "risk-aware" trong phần đóng góp của báo cáo | Đổi tên cần thủ tục, không đổi nội dung | — | — | Đã chốt |
| Q14 | Fail-safe khi hết hạn duyệt | **Escalate, không tự làm** | Nguyên tắc 1: an toàn hơn tự động hóa | — | — | Đã chốt |

**Mục cần báo cáo GVHD (không cần GVHD quyết):** D-01, D-07, D-08 (đổi hành vi hoặc công nghệ đã ghi), D-13, D-22, D-25, D-29, D-30, D-32, D-33, **D-34**, cùng Q6 và Q12 — xem cột "Báo GVHD" ở mục 3.

## 3. Quyết định kỹ thuật D-01…D-34

Nội dung đầy đủ và lý do: `build/00-README.md` mục 4 và file được nêu trong từng quyết định. "Chốt trước" = phase phải chốt xong trước khi bắt đầu.

| Mã | Nội dung | Ảnh hưởng | Chốt trước Phase | Báo GVHD | Trạng thái |
|---|---|---|---|---|---|
| D-01 | Đăng nhập tách khỏi graph; B1 chỉ chốt danh tính + `requester_context` từ AD | Đổi hành vi TC24/TC25 | 2 | **Có** | Đã chốt (theo đặc tả) |
| D-02 | RBAC + kiểm tra theo bản ghi (chống IDOR), deny-by-default | Thêm TC30 | 2 | Không | Đã chốt (theo đặc tả) |
| D-03 | 4 service identity; chỉ `svc_executor` có credential ghi | Mock | 1 | Không | Đã chốt (theo đặc tả) |
| D-04 | Bảng `security_events` + view `auth_failures` | DB | 1 | Không | Đã chốt (theo đặc tả) |
| D-05 | 3 role Postgres + trigger append-only | DB | 1 | Không | Đã chốt (theo đặc tả) |
| D-06 | B2 có 5 lớp, thêm model phân loại injection (Prompt Guard 2 baseline / mDeBERTa fine-tune) | B2, chi phí | 5 | Nên báo (gắn RQ4) | Đã chốt (theo đặc tả) |
| D-07 | Privacy guard chạy ở API trước khi lưu ticket | `TicketState` (`raw_request` → `redacted_request`) | 3 | **Có** | Đã chốt (theo đặc tả) |
| D-08 | `interrupt()` thay `interrupt_before` | Cơ chế chờ người | 2 | **Có** (đổi công nghệ đã ghi) | Đã chốt (theo đặc tả) |
| D-09 | Thêm process `ml-service` | Triển khai | 3 | Không | Đã chốt (theo đặc tả) |
| D-10 | BM25 tách từ tiếng Việt, sparse vector trong Qdrant, RRF phía server | M2 | 3 | Không | Đã chốt (theo đặc tả) |
| D-11 | Bảng `llm_cache` | DB | 1 | Không | Đã chốt (theo đặc tả) |
| D-12 | LLM gateway tự viết trên SDK `openai`; LiteLLM là phương án B | M4/LLMOps | 3 | Không | Đã chốt (theo đặc tả) |
| D-13 | Modular monolith + service phụ trợ | Toàn bộ | 1 | Nên báo | Đã chốt (theo đặc tả) |
| D-14 | Audit idempotent — khóa **`(ticket_id, step, event, turn_id, loop_seq)`** (sửa ở v1.2) | M7 | 2 | Không | Đã chốt (theo đặc tả) |
| D-15 | B17 kiểm lại **cả người gửi lẫn người hưởng lợi** trong AD trước khi ghi (sửa ở v1.2) | B17 | 5 | Không | Đã chốt (theo đặc tả) |
| D-16 | Tool chẩn đoán mặc định chỉ tra cứu chính người gửi | B6, M5 ctx | 5 | Không | Đã chốt (theo đặc tả) |
| D-17 | `parent_wait` đối soát trạng thái con từ DB; `child_done` chỉ để đánh thức | Runner, B5, B20 | 2 | Không | Đã chốt (theo đặc tả) |
| D-18 | Side effect idempotent qua bảng `side_effects`; phục hồi giữ `turn_id` | Runner, DB (22 bảng từ v1.3) | 2 | Không | Đã chốt (theo đặc tả) |
| D-19 | Khóa ticket cấp session trên pool riêng | Runner | 2 | Không | Đã chốt (theo đặc tả) |
| D-20 | Chẩn đoán lại B11 → B6 khi slot mới đổi tham số tool; thêm chuyển `S_CLARIFYING → S_DIAGNOSING` | **Máy trạng thái** | 5 | **Có** (Q10) | Đã chốt (theo đặc tả) |
| D-21 | Chunk theo token bge-m3 (≤ 380 token nội dung) | M2 | 3 | Không | Đã chốt (theo đặc tả) |
| D-22 | Bộ ≥ 20 câu không có đáp án để chọn ngưỡng E3 | M2, dữ liệu | 3 | Nên báo | Đã chốt (theo đặc tả) |
| D-23 | Truy hồi lại một lần không lọc intent khi điểm thấp | M2 | 3 | Không | Đã chốt (theo đặc tả) |
| D-24 | Ghép chunk liền kề làm ngữ cảnh cho B10 | M2 | 3 | Không | Đã chốt (theo đặc tả) |
| D-25 | KB mục tiêu ≥ 50 tài liệu có tài liệu gây nhiễu; ablation RAG 4 cấu hình | Khối lượng nội dung, Obj 1 | 5 | Nên báo | Đã chốt (theo đặc tả) |
| D-26 | Ticket mới do L2 mở lại chạy từ B1 | B20, NGU-CANH Phần VI | 7 | **Có** (Q11) | Đã chốt (theo đặc tả) |
| D-27 | Tách `event=intent_low_confidence` khỏi E1 thật | M9, chỉ số | 5 | Không | Đã chốt (theo đặc tả) |
| D-28 | Lập luận "constrained agent" trong P1 | Tài liệu | — | Không | Đã chốt (theo đặc tả) |
| D-29 | `ALLOWED_TRANSITIONS` = bảng 2.1 + 3 quy tắc (giữ nguyên trạng thái xử lý; mọi trạng thái chưa kết thúc → `S_ESCALATED`; chuyển riêng của ticket cha) | **Máy trạng thái** (không thêm trạng thái, không mở đường mới tới `S_EXECUTING`) | 2 | Nên báo | Đã chốt (theo đặc tả) |
| D-30 | Ticket cha: `close_reason = NULL`, không `exit_code`, không `escalations`; chỉ số chỉ tính ticket lá | Chỉ số Obj 3, DB (`tickets.is_parent`) | 5 | Nên báo (ảnh hưởng cách đếm) | Đã chốt (theo đặc tả) |
| D-31 | Một tin tổng hợp cho yêu cầu nhiều ý: con không tự nhắn, cha gửi một tin mỗi lượt người dùng, xác nhận một lần qua cha | B5, B10, B11, B16, B18, B19, B20; DB 22 bảng (`child_notices`) | 5 | **Có** — báo đánh đổi "người dùng chờ ý chậm nhất" (nhóm đã chọn giữ đúng câu chốt) | Đã chốt (theo đặc tả) |
| D-32 | B3 chạy model phân loại intent đa nhãn (nhóm tự huấn luyện) trước; LLM cho vùng lưng chừng, câu nhiều ý và khi chưa có model | B03-B05, B02, P2, P4, P11 | 3 | Nên báo | Đã chốt (theo đặc tả) |
| D-33 | Backbone mDeBERTa-v3-base cho `intent-clf` và `injection-clf`; PhoBERT baseline intent; Prompt Guard 2 baseline RQ4 | P11, B02, P4 | 5 | Nên báo | Đã chốt (theo đặc tả) |
| D-34 | **Tách căn cứ câu trả lời và căn cứ hành động (Q-4-U A+).** Căn cứ của **câu trả lời** = độ liên quan truy hồi (B9, `RETRIEVAL_THRESHOLD`) — chỉ áp khi `need_type=info`, kiểm trong B10 **trước** `expand`/`b10_answer`. Căn cứ của **hành động** = tài liệu quy trình `procedure_doc` khai cho `action_type` (`action_metadata.yaml`), kiểm **tất định** ở B11 trên KB đang chạy lúc đó (alias hiện hành, lọc theo role) — thiếu → E3 `no_procedure`. Hành động được quản bởi chính sách (M5) và con người (M6), không bởi độ giống văn bản. Chunk dưới ngưỡng không làm bằng chứng cho B14 (`evidence_for_estimator`). Ràng buộc Phase 6: không luật nào khớp + `kb_gap` → tối đa HITL, không AUTO. Không kiểm lại quy trình ở B17: nếu quy trình bị rút sau B11, **người duyệt (HITL) là lớp chặn** — màn xem phiếu (4c) hiển thị `procedure_doc`. Cờ `GROUNDING_GATE_ACTIONS` (mặc định tắt) giữ hành vi cũ cho ablation Phase 10. Lý do đo được: reranker xếp đúng tài liệu cho câu ra lệnh nhưng điểm 0,047 (tc09) so với 0,981 cho câu hỏi (tc05) | **Thứ tự luồng**: B9 nay nằm trong nhánh trả lời của B10; B08, B10, B11, B14, B20 (ghi chú bàn giao) | 4 | **Có** (đổi thứ tự bước [Chốt] B9 → B10) | Đã chốt 30/09/2026, hiện thực `5ed423d` |

## 4. Chế độ xây: code trước, gắn API sau

**Đã chốt 25/09/2026:** toàn bộ D-01…D-33 chốt **theo đúng đặc tả hiện có**; muốn đổi mục nào thì sửa dòng đó và ghi nhật ký, không đổi ngầm trong code.

Nhóm xây **toàn bộ code base trước bằng dữ liệu giả**, gắn LLM API thật sau:

| Thành phần | Khi xây (Phase 1–7) | Khi gắn API (mốc G) |
|---|---|---|
| LLM | `ScriptedLLM` trả JSON đúng schema của từng prompt (P2 mục 4) | Provider thật theo N1, `spend_cap` bật |
| ml-service (embed, rerank, classifier) | Chạy thật trên CPU; `intent-clf`/`injection-clf` chưa có → 503 → đường LLM (giả) | Nạp model đã huấn luyện (P11) |
| Hệ thống ngoài | `mock_services` **[Chốt]** — không đổi ở mốc G | Như cũ |

**Mỗi cổng phase tách làm hai phần:**

- **Cổng code (đạt ngay trong phase):** mọi test tự động của phase xanh với `ScriptedLLM`. Được mở phase sau khi phần này xanh.
- **Phần cần LLM thật (dồn về mốc G):** demo 4 ca VPN (cổng 3), cổng 5 thủ công, probe phân phối p (cổng 6), probe intent/injection/JSON (P2 mục 13), tải thật nhỏ.

**Mốc G — gắn API (sau cổng code Phase 7, trước Phase 8):** chọn model bằng probe (N1, P2 mục 12) → điền `pricing` → chạy lần lượt mọi phần đã dồn ở trên → sửa lỗi tích hợp → mới vào Phase 8. Phase 8–10 bắt buộc dùng LLM thật.

**Đánh đổi phải biết:** Phase 3 vốn dùng LLM thật để lộ lỗi tích hợp sớm; dồn về mốc G thì lỗi dạng "model trả JSON lệch schema, tiếng Việt kém, chậm" sẽ lộ muộn. Giảm rủi ro bằng hai việc rẻ:

1. `ScriptedLLM` phải trả cả ca xấu: JSON sai một lần rồi đúng, thiếu trường, timeout, 429 — để nhánh xử lý lỗi (P2 mục 9–10) được test từ đầu.
2. Khi xong cổng code Phase 3, chạy **một lần** luồng VPN với một model rẻ (tốn vài nghìn đồng, trong khoản 5 USD probe) để chắc hợp đồng P2 khớp provider thật. Không đạt thì sửa ngay, không đợi mốc G. **Dời (Tuấn Anh chốt 30/09/2026) — nợ NỢ-3-2** (`phase3-thiet-ke-chi-tiet.md` mục 13): chạy trước khi Phase 5 viết thêm prompt (khuyến nghị), muộn nhất mốc G; đánh đổi: lỗi hợp đồng P2 với provider thật lộ muộn hơn.

**Còn chặn:** không còn mục nào chặn việc viết code. N1 (chọn model) và N2 (VRAM) chỉ chặn mốc G.

## 4.1. Quyết định khi hiện thực Phase 2b (26/09/2026)

Đánh số `2b-Q…` để không lẫn với Q1–Q14 ở mục 2. Chi tiết và lý do nằm ở file đặc tả được trỏ tới.

| Mã | Câu hỏi | Chốt | Ở đâu |
|---|---|---|---|
| 2b-Q1 | Ai ghi cảnh báo dò mật khẩu? | Một writer idempotent `AlertWriter.raise_once`; auth ghi lúc khóa, B1 ghi lại cùng khóa. Khóa `(rule_id, subject, window_start)`, `subject` không DEFAULT (migration 0004). Cảnh báo E0/E7/E9 → M9 Phase 7 | P7 2.12, P9 mục 6, B01 5.1 |
| 2b-Q2 | Privacy guard ở `POST /api/tickets` trước Phase 3 | Port `PrivacyGuard`; 2b gắn `NotRedactingGuard`, **chỉ nạp khi `APP_ENV` ∈ {dev, test}**, env khác → app từ chối khởi động | B02 (Phase 3 thay adapter) |
| 2b-Q3 | Route duyệt trong 2b? | Có: `SqlApprovals` vào `app/approval/store.py`, `POST /api/approvals/{id}/decision` (`approval:decide` + `can_decide_approval`), đi qua `deliver_event`. `FAKE_APPROVER_ID` chỉ ở dev/test (fail-closed như 2b-Q2) | B15-B16 |
| 2b-Q4 | `is_deny_case` | Mọi E5 | B20 5.1 |
| 2b-Q5 | Hai `close_reason` do L2 sinh | Phase 7; "ghi một lần" theo từng cột | B20 5.1 |
| 2b-Q6 | Exception ở B20 | Ném tiếp, worker chạy lại; tối đa 3 lần rồi `finalize_failed_permanent` | B20 5.1 |
| 2b-Q7 | Mặc định còn lại | `role_unmappable` → E2; AD 404 → `invalid_credentials`; phiên theo họ token; TicketBusy (đang giữ khóa) → 503 + Retry-After, lượt đã xong mà trạng thái không còn chờ → 409; non-owner đọc được → 403, không đọc được → 404; `wake_parent` sau khi nhả khóa | B01 5.1, B20 5.1 |

**Phase 2b-2 (26/09/2026):**

| Mã | Câu hỏi | Chốt | Ở đâu |
|---|---|---|---|
| 2b-QA | `resolution_path` lấy từ đâu? | B20 suy ra tại một chỗ; `goto()`/boundary chặn key ngoài `TicketState` (LangGraph bỏ im lặng key lạ) | B20 5.1, P1 5.1, B10/B17 1.4 |
| 2b-QB | Đếm "3 lần" B20 lỗi bằng gì? | `turns.recover_attempts` (migration 0005), tăng **trước** khi recover; không đếm span lỗi vì process bị giết không kịp ghi. Vượt 3: B20 → `finalize_failed_permanent`; node khác → E9 `recover_exhausted` | P7 2.13, P1 mục 7, B20 5.1 |
| 2b-QC | Thứ tự trong B20 | `finalize_once` trước, điểm log 8 từ dòng đã lưu | B20 5.1 |
| 2b-QD | Mặc định còn lại | Route `/api/escalations/queue`; `handoff_note.request` chỉ từ `redacted_request`; `closed_at` ở B20 cho mọi trạng thái cuối; 2b-3: `created_at` lấy từ `Clock` của app | B20 5.1 |

**Phase 2b-3 (26/09/2026):**

| Mã | Câu hỏi | Chốt | Ở đâu |
|---|---|---|---|
| 2b-3-Q1 | Sự kiện qua API trả gì? | 202; khóa ticket lấy trong request rồi giao cho task nền (try/finally + cờ "đã giao") | P1 mục 7 |
| 2b-3-Q2 | `mark_late` làm gì với phiếu? | **A:** không đổi `approvals.status`, chỉ audit `late_event` (`reason = expired \| already_decided`); mọi đường 409 để lại đúng 1 `late_event`; bằng hạn = muộn | B15-B16 5.1 |
| 2b-3-Q3 | `APP_ENV` | Bắt buộc khai báo trong `.env`; compose `${APP_ENV:?…}`, không mặc định | 01 lịch sử v1.5 |
| 2b-3-Q4 | `FAKE_APPROVER_ID` cần dòng `users` | Không seed DB app; thiếu → B15 giả → E9; 2b-4 `gate2.py` đăng nhập l1 trước | B15-B16 5.1 |
| 2b-3-Q5 | Giới hạn body | 64 KB, kiểm **trước** quyền, đếm byte đọc thật (chunked cũng bị chặn) → 413 | B15-B16 5.1 |
| 2b-3-QA | Thứ tự kiểm ở messages/confirm | 413 → quyền → tải ticket → không đọc được 404 → không phải chủ 403 → ticket con 409 → body 422 → guard → `start_event` (route; worker dùng `deliver_event`); 403 và 404-có-thật ghi 1 `permission_denied`, guard không được gọi | P6, P1 6.1 |
| 2b-3-QB | `GET /api/tickets/{id}` | Response model khai báo; có `final_state` thì `status` từ `tickets`, còn mở từ checkpoint; `waiting_for` chỉ từ checkpoint; đọc checkpoint lỗi → 503 | P1 mục 7 |
| 2b-3-QC | Chết trước checkpoint đầu | Recover (đang giữ khóa) chạy state đầu dựng từ dòng `tickets` như `run_new`, giữ `turn_id` — không gọi `run_new` (tự khóa chết); quá 3 lần → E9 `recover_exhausted` qua B20 (không để ticket thiếu `final_state`) | P1 mục 7 |
| 2b-3-QD | Runtime lỗi lúc khởi động | Route ticket/duyệt 503; `/api/health` 200 + `"runtime": "up\|down"` | P1 mục 10 |

**Phase 2b-4 (27/09/2026):**

| Mã | Câu hỏi | Chốt | Ở đâu |
|---|---|---|---|
| 2b-4-Q1 | Chọn kịch bản node giả trên stack | Thẻ `[fake:<preset>]` trong câu yêu cầu; chỉ đọc khi `FAKE_SCENARIO` được đặt (dev/test), đọc từ `redacted_request`; B1/B20 không đọc thẻ (test AST). Thẻ lạ → E9. Kết quả preset đánh chỉ số **theo state**, không theo bộ nhớ process (giống nhau trước/sau restart) | `backend/tests/stack/README.md`, PROGRESS 2b-4 |
| 2b-4-Q2 | `FAKE_NODE_DELAY` | Số giây, điểm dừng do preset quyết (`kill_b06`, `kill_b15`); < stale/2; fail-closed ngoài dev/test | như trên |
| 2b-4-Q3 | Hết hạn trên stack | Script dời `deadline` bằng psql; không thêm setting rút SLA | như trên |
| 2b-4-Q4 | Ai chạy lệnh compose | Script tự chạy, in lệnh trước; chốt an toàn `APP_ENV=dev`, chỉ `127.0.0.1`, cấm `down -v` | như trên |
| 2b-4-Q5 | Duyệt approved trên stack ra E7 | Chấp nhận tới Phase 3 (RefusingExecutor); script in rõ nguyên nhân | B17 |
| 2b-4-Q6 | Assert quét guard | Giữ ≥ 22 + tập con bắt buộc (ước tính 25 bảng) | — |
| 2b-4-Q7 | `make gate2` | Thêm, chỉ dev | 01 §7.1 |
| 2b-4-Q8 | Auth trên stack | Không chạy; TC24/TC25 đã phủ ở 2b-3 | — |
| 2b-4-QA | Đọc trạng thái sau request trả 202 | Luôn chờ **có lượt mới và mọi lượt đã đóng** (`after_event`) rồi mới đọc; mọi phép kiểm "khoá nhả / không có X" phải có đối chứng | PROGRESS 2b-4 |
| 2b-4-QB | Cổng 2 đạt khi nào | 10 kịch bản `make gate2` 0 FAIL trên máy Tuấn Anh **và** một thành viên khác chạy `make gate2 S=all` trên máy họ (ưu tiên máy gaming, kiêm N2) + người đọc bảng threads xác nhận | P1 §11 |

**Phase 3 (27/09/2026):** quyết định `3-Q1…3-Q40` nằm ở `build/phase3-thiet-ke-chi-tiet.md` mục 2; quyết định khi hiện thực từng chặng nằm ở mục chốt của chặng đó.

| Chặng | Mã | Tóm tắt | Ở đâu |
|---|---|---|---|
| 3h | Q-3h-1…11, P1–P9 | DSL chặt + `check_policy_config`; `target_is_other` (P3); thứ tự B17 [0]→[5], `begun` theo ticket; so `requester.*` AD mới vs B1; `durability="sync"`; `ExecutionResult.outputs`; hai đường gián đoạn; gate3 theo giờ; vpn-smoke theo `spend.cap_usd`; Q-3h-10: lỗi sau `begun` → E7 (ticket có `begun` không mang mẫu E9); Q-3h-11: câu truy hồi bỏ thẻ `[fake:…]`, gate3 tc09 = E3 (B9 chặn yêu cầu hành động — chuyển Phase 4 S0, Q-4-U) | `phase3-thiet-ke-chi-tiet.md` mục 11.10 |
| 3g | Q-3g-1…12, P1–P10 | `cannot_answer` → `no_grounding`; anchor ∩ khối gửi LLM; lineage qua `goto` cùng transaction audit; `validate_targets` luôn kiểm lại, bỏ fact máy cũ; D-20 fail-closed; che L1 trước khi tạo sự kiện | mục 10.7 |
| 3f | Q-3f-1…7, P1–P4 | Hạn cả lượt 100 s (trước semaphore); slot > 100 ký tự bỏ; slot phải có trong câu; slot không thành fact; R20 phải đòi `device_owner_is_requester` | mục 9.8 |
| 3e | Q-3e-1…14 | Privacy guard L0/L1 (bỏ Presidio); injection L2 + L4 judge; `screen_reply`; luật chung 8.9; HMAC username → Phase 4 S0 | mục 8.9 |
| 3d | Q-3d-1…8 | `llm.complete` + `ScriptedLLM` + prompt registry; trần chi `spend.cap_usd` (không env); giữ chỗ chi phí xấu nhất; `AnswerOut` hai chiều | mục 7.8 |
| 3c | Q-3c-1…8 | 2 đường cổng kiểm; nới tiêu chí rerank; probe `/aliases`; giữ role lạ `public`; audit câu đã che | mục 6.13 |
| 3b | Q-3b-1…17 | Embed ingest nhóm 1; sha gồm front matter; ghi bù từ metadata collection; cổng (c) đánh giá lại bản cũ; `pipeline_sha` (3c so lúc truy vấn → E2); khoá advisory; hợp đồng `rag-lower-layer`; cổng kiểm dense-only tạm tới 3c; hậu kiểm 3b sau dự án (mục 1.5) | `phase3-thiet-ke-chi-tiet.md` mục 5.14 |
| 3a | Q-3a-1…16 | torch CPU; `attempts` = số lần gọi lỗi; lỗi mạng khác → `connect` có retry; `NodeDeps.ml` bắt buộc; fake tầng HTTP; test sinh đôi + `ml_real`; worker chờ ml-service; lock luôn 40 hex; trần timeout < stale/2, rerank 10 s tạm, quyết ở 3c | `phase3-thiet-ke-chi-tiet.md` mục 4.12 |

**Phase 4 (30/09/2026):** câu hỏi `Q-4-A…U` và lỗ hổng `G4-1…25` nằm ở `build/phase4-thiet-ke-chi-tiet.md` mục 2–3 (Tuấn Anh chốt: A…T đồng ý hết, U = phương án A+). Quyết định khi hiện thực từng chặng nằm ở mục chốt của chặng đó.

| Chặng | Mã | Tóm tắt | Ở đâu |
|---|---|---|---|
| 4a S0 | Q-4-U, S0-P1…P11, S0-A1…A5, Q-4a-1…3 | D-34; handoff đánh dấu tài liệu dưới ngưỡng + câu cố định cho `no_procedure`; `procedure_available` đọc alias lúc B11; không kiểm quy trình ở B17 | `phase4-thiet-ke-chi-tiet.md` mục 4.0 + "Chốt khi hiện thực S0" |
| 4b (sắp) | Q-4-L, M, N, P, Q, R | Xung đột → Trưởng BP [Chốt]; **R17/R18/R19 sẽ thêm điều kiện `device_owner_is_requester`** (máy người khác/không tồn tại → E5); đồng bộ `users` từ AD; chuỗi quản lý; seed `l1_lead` | mục 5 |

## 5. Nhật ký

| Ngày | Thay đổi |
|---|---|
| 25/09/2026 | Tạo file: gộp D-01…D-33 và mọi câu hỏi GVHD (từ `huong-dan` mục 12, `NGU-CANH` Phần VI mục 1, `bo-sung`) thành một danh sách |
| 25/09/2026 | Thêm D-32, D-33 (model phân loại do nhóm huấn luyện), N5 |
| 25/09/2026 | Sửa bảng hỏng: dòng Q12 (7 cột, gắn D-31), đưa D-32/D-33 về bảng D |
| 25/09/2026 | Bỏ vòng hỏi GVHD: Q1–Q14 thành quyết định của nhóm (xây trước / tối ưu sau), chỉ báo cáo. Chốt N1 (đa provider, trần 1 triệu đ), N2 (3 máy gaming + 1 Mac, chờ VRAM), N3 (70/20/10), N4 (bảng R01–R20, R22 → R17), N5 (Kaggle + Colab, fp32) |
| 25/09/2026 | Chốt D-01…D-33 theo đặc tả; thêm chế độ "code trước, gắn API sau" (mục 4, mốc G); N1/N2 chỉ chặn mốc G |
| 26/09/2026 | Mục 4.1: quyết định 2b-Q1…2b-Q7 của Phase 2b |
| 26/09/2026 | Mục 4.1: quyết định 2b-QA…2b-QD của Phase 2b-2 |
| 26/09/2026 | Mục 4.1: quyết định 2b-3-Q1…Q5, 2b-3-QA…QD của Phase 2b-3 |
| 27/09/2026 | Mục 4.1: quyết định 2b-4-Q1…Q8, 2b-4-QA…QB của Phase 2b-4 |
| 28/09/2026 | Mục 1.3: ghi VRAM máy gaming thứ nhất (RTX 4050 Laptop 6 GB); **cổng 2 đạt** — Tạ Duy Anh chạy `make gate2 S=all` trên `2a9f3ee`: 89 PASS / 0 FAIL, threads đạt (20 ticket = 20 thread) |
| 27/09/2026 | Mục 4.1: trỏ 3-Q1…Q40 và Q-3a-1…16 (chặng 3a) |
| 28/09/2026 | Mục 4.1: Q-3b-1…17 (chặng 3b) |
| 30/09/2026 | Mục 4.1: Q-3c…Q-3h (chặng 3c–3h, trỏ mục chốt tương ứng); §1.1: ghi chú điều kiện R16–R20 Phase 3 |
| 30/09/2026 | Phase 3 đóng phần code (`c11b61f`, `61ad8ac`, CI `36684958734`); nợ nghiệm thu NỢ-3-1 (gate3 thành viên ngoài giờ), NỢ-3-2 (smoke LLM thật — dời mục 4 việc 2) gộp vào đợt kiểm tổng |
| 30/09/2026 | D-34 (tách căn cứ câu trả lời / hành động, Q-4-U A+, commit `5ed423d`); mục 4.1 thêm Phase 4 (Q-4-A…U) |
