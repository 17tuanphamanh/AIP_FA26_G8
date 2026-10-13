# Quyết định của nhóm — danh sách duy nhất

*Thuộc bộ `build/`. Đây là **nơi duy nhất** theo dõi trạng thái quyết định. Nhóm **tự quyết** mọi mục (không có vòng hỏi GVHD); mục nào đổi hành vi hoặc công nghệ so với tài liệu gốc thì **báo cáo** GVHD trong báo cáo tuần. `huong-dan-xay-dung-he-thong-2.md` Phase 0 gọi file này là `decisions.md`. Khi một mục được chốt: sửa cột "Trạng thái" ở đây, rồi áp patch tương ứng (nếu có) trong `claude/bo-sung-bo-tai-lieu-build.md`.*

*Cập nhật: 13/10/2026 (D-49 ticket con vào B6 + tách ý lẫn — spec T20b; T24 đóng `457239d`; D-48 thực thi/hoàn tác theo bước — spec T24; T20a đóng; D-47 hợp đồng `Action` 4 intent — spec T20a; §1.1 điều kiện R01–R15 chốt theo T22a + R10 bổ sung ở T20a; D-35, D-41 chữ chốt). Trước đó 10/10/2026 (D-44…D-46 + Q-5-7…9 — kế hoạch Phase 5 sau T22a, phiên PHAN-TICH-P5; 09/10: Q-5-6 `procedure_doc` theo K2 thật; vào repo cùng spec Phase 5 ở chặng T22a; trước đó 03/10: cổng 4 đạt — §4.1 dòng 4d; 01/10: D-35…D-43 Phase 5–6, Q-5-1…5, Q-6-1…9).*

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

**Chốt Phase 4 (Q-4-M, 4b P7):** R17/R18/R19 thêm điều kiện `action.facts.device_owner_is_requester is_true` (máy người khác / không tồn tại → không luật nào → E5).

**Phase 5 — T22a [Chốt — đóng T22a `2ffb005`, 09/10]:** điều kiện đầy đủ R01–R15 ở `build/phase5-thiet-ke-chi-tiet.md` mục 4.4, đúng như `config/policy.json` (R09 = tài nguyên **phòng ban khác**, Q-5-4; R10 đòi cùng phòng, độ nhạy ≠ high, tài khoản đích active/probation, ≤ 90 ngày; R12 áp cả gia hạn quyền); 7 allow / 12 approval_required / 1 deny; Quân soát bảng (checklist 4.12). **T20a thêm cho R10:** `existing_permission_level in [read, write]` (Q-T22a-8, Q-5-8) — thiếu fact → không khớp → lớp LLM.

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

**Q-6-8 (`full_auto`) — chốt C (10/10/2026):** B12 không dựng `RiskDecision`; điểm log 4 ghi `decided_by = NULL`, `detail = {strategy: "full_auto", route: "AUTO"}`; `risk = None`; đi `S_EXECUTING`. B17 giữ nguyên kiểm lại luật (ca `approval_required`/`deny` → E5). Không migration, không nới B17. `audit_check` chỉ chấp nhận `decided_by` NULL khi `detail.strategy = "full_auto"`. Chỉ chạy khi `EVAL_MODE`. (phase6 v0.9 mục 6.1)

**Mục cần báo cáo GVHD (không cần GVHD quyết):** D-01, D-07, D-08 (đổi hành vi hoặc công nghệ đã ghi), D-13, D-22, D-25, D-29, D-30, D-32, D-33, **D-34**, **D-38**, **D-41**, **D-43**, **D-44**, **D-45**, **D-46**, **D-49** (mục a), cùng Q6 và Q12 — xem cột "Báo GVHD" ở mục 3.

## 3. Quyết định kỹ thuật D-01…D-49

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
| D-32 | B3 chạy model phân loại intent đa nhãn (nhóm tự huấn luyện) trước; LLM cho vùng lưng chừng, câu nhiều ý và khi chưa có model | B03-B05, B02, P2, P4, P11 | 3 | Nên báo | Đã chốt (theo đặc tả); **ngoại lệ tạm D-44** (10/10) |
| D-33 | Backbone mDeBERTa-v3-base cho `intent-clf` và `injection-clf`; PhoBERT baseline intent; Prompt Guard 2 baseline RQ4 | P11, B02, P4 | 5 | Nên báo | Đã chốt (theo đặc tả); **lệch có ghi — D-45** (10/10) |
| D-34 | **Tách căn cứ câu trả lời và căn cứ hành động (Q-4-U A+).** Căn cứ của **câu trả lời** = độ liên quan truy hồi (B9, `RETRIEVAL_THRESHOLD`) — chỉ áp khi `need_type=info`, kiểm trong B10 **trước** `expand`/`b10_answer`. Căn cứ của **hành động** = tài liệu quy trình `procedure_doc` khai cho `action_type` (`action_metadata.yaml`), kiểm **tất định** ở B11 trên KB đang chạy lúc đó (alias hiện hành, lọc theo role) — thiếu → E3 `no_procedure`. Hành động được quản bởi chính sách (M5) và con người (M6), không bởi độ giống văn bản. Chunk dưới ngưỡng không làm bằng chứng cho B14 (`evidence_for_estimator`). Ràng buộc Phase 6: không luật nào khớp + `kb_gap` → tối đa HITL, không AUTO. Không kiểm lại quy trình ở B17: nếu quy trình bị rút sau B11, **người duyệt (HITL) là lớp chặn** — màn xem phiếu (4c) hiển thị `procedure_doc`. Cờ `GROUNDING_GATE_ACTIONS` (mặc định tắt) giữ hành vi cũ cho ablation Phase 10. Lý do đo được: reranker xếp đúng tài liệu cho câu ra lệnh nhưng điểm 0,047 (tc09) so với 0,981 cho câu hỏi (tc05) | **Thứ tự luồng**: B9 nay nằm trong nhánh trả lời của B10; B08, B10, B11, B14, B20 (ghi chú bàn giao) | 4 | **Có** (đổi thứ tự bước [Chốt] B9 → B10) | Đã chốt 30/09/2026, hiện thực `5ed423d` |
| D-35 | **T22a lên đầu Phase 5, làm sớm sau commit 4d** ("chưa tính qua cổng 5"). Cổng D2 đếm "ca đi xuống LLM" bằng `scripts/rule_coverage.py` chạy lớp luật trên `gold.action` + `gold.facts` (2 trường mới của schema kịch bản P8 §4.1) | Thứ tự Phase 5; schema kịch bản; P8 §4.1, §4.3 | 5 | Không | **Đã chốt** (T22a `2ffb005`, 09/10): `rule_coverage.py` + schema `gold.action`/`gold.facts` (phase5 4.6; P8 §4.1 — Phase 6 giữ bút) |
| D-36 | **Phase 6 làm sớm phần thuần** (6A toán + calibrator, 6B estimator + chiến lược) trước cổng 5 + D2, "chưa tính qua cổng 6". Phase 6 **không** fit calibrator trên dữ liệu thật (T37, Phase 10, người không xây M5) | Lịch Phase 6 | 6 | Không | Đã chốt hướng 01/10 (Q-6-1) |
| D-37 | **Một nguồn toán quyết định:** `app/risk/decision_math.py` (t_low*, quét lưới, Clopper–Pearson, ECE, Brier, AUC) + `app/risk/calibrator.py` (Platt, temperature, `LeakageError`); `eval/metrics.py` (T29), `eval/calibrate.py` (T27) import lại, không viết lần hai; test AST cấm `app.risk → app.eval` | P8 §2 (`stats.py`, `metrics.py`), B12 §3 | 6 | Không | Đã chốt hướng 01/10 (Q-6-2) |
| D-38 | **Chưa hiệu chỉnh thì không tự làm:** `calibrator_version = null` → `p > t_high` → chuyển L2, còn lại chờ duyệt; `reason` ghi "chưa hiệu chỉnh" | Hành vi M5 lớp 2 tới T37 | 6 | **Có** (đổi hành vi so với B12 §5) | Đã chốt hướng 01/10 (Q-6-3) |
| D-39 | **Cache B14:** prompt `b14_*` để `cache: default`; estimator truyền `cache_policy="bypass"` khi `EVAL_MODE=false` (vận hành không bao giờ cache); hỏi nhiều lần k = 5 = 5 lời gọi có biến `sample_idx` trong thân prompt (khoá cache khác nhau); `huong-dan` "hỏi 7 lần" sửa thành k = 5 | P2 §7–8, B12 §5.1 | 6 | Không | Đã chốt hướng 01/10 (Q-6-6) |
| D-40 | **`reason` của lớp LLM ghép theo mẫu** từ `factors` (tập mã đóng `FactorCode`); không lưu `rationale` tự do của LLM | B12 §4.1, audit điểm 4 | 6 | Không | Đã chốt hướng 01/10 (Q-6-5) |
| D-41 | **DSL thêm nguồn `action.params`** (danh sách trắng đích danh `permission_level`, `duration_days`); **`requested_for` = người bị tác động**; `build_ctx`: vế chủ máy chỉ áp cho đích `device:`; R09 "vượt cấp quản lý" = tài nguyên phòng ban khác (fact `same_department`) | B12 §4.2, B11 §4, `risk/context.py` | 5 | **Có** (định nghĩa R09) | **Đã chốt** (T22a `2ffb005`): `PARAM_TYPES` + `param_ok` (sai kiểu/ngoài khoảng = thiếu), `build_ctx` theo đích, docstring P4 ở `domain/action.py`, `domain/facts.py` |
| D-42 | **B17 chấp nhận AUTO do LLM** khi `risk.decided_by=llm ∧ route=AUTO ∧ action_plan_hash` (B12 đặt) khớp `hash_action(action)`; còn lại "không luật khớp, chưa duyệt" vẫn E5 | B17 (sau T24), B12 | 6 | Không | Đã chốt hướng 01/10 (Q-6-7) — làm ở 6C |
| D-43 | **Tách vai người gán nhãn:** người gán nhãn (Dương, Duy Anh) không xác nhận cổng luật M5 và không đọc lý do rủi ro; hai việc đó giao Quân. Xác nhận 6A (toán) giao Dương | Phân việc cổng 5, 6 | 5 | **Có** | Đã chốt hướng 01/10 |
| D-44 | **Ngoại lệ tạm của luật 8 / D-32 tới khi model qua kiểm.** B2 lớp 3 (`injection-clf` của nhóm) chạy chế độ **`shadow`** (`B2_CLASSIFIER_MODE`, mặc định): chỉ ghi `p_mal`, mọi câu không khớp mẫu xuống L4 LLM. Repo **mặc định không nạp model** (`GUARD_MODEL_DIR` rỗng → `/classify` 503 như Phase 3); bật bằng `.env` khi đo/demo. B3 **không dùng model** của nhóm ở Phase 5 (`/classify_intent` giữ 503; M9 `b3_cascade` giữ `pending`). Lý do: ở chế độ quyết định với 0,90/0,10, 31/900 câu tấn công đi thẳng không qua LLM (bỏ lọt), 10/22 câu thường có nhãn che bị chặn; gói intent chỉ có một ngưỡng 0,75, không có τ_hi/τ_lo (P11 §4.2). **Điều kiện chuyển `active` (B2):** `thresholds.json` chọn trên validation + đạt ≥ 13/15 chặn, ≤ 1/30 chặn nhầm + báo M9 bỏ `pending` luật 12. **Điều kiện cascade (B3):** Duy giao τ_hi/τ_lo từng nhãn trên validation + SHA-256 `seed_42.pt` xác nhận; làm sau cổng 5, trước đóng băng Phase 10. **10/10: Duy đã giao** — SHA `3efd3bd0…46db9` khớp; `thresholds.json` (val 3.143 câu, seed_42, điểm = confidence của gói): account 0,135/0,027 · vpn 0,365/0,679 · software 0,905/0,085 · access 0,305/0,156 · out_of_scope 0,820/0,372 (τ_hi/τ_lo). Quy tắc dùng: τ_hi_dùng = max(τ_hi, τ_lo), τ_lo_dùng = min(τ_hi, τ_lo) (vpn có τ_lo > τ_hi → vùng 0,365–0,679 xuống LLM, không ép bằng nhau); số trên val là số chọn — đo lại một lần trên test của model để báo cáo, **không** chỉnh lại ngưỡng theo test. **10/10 11:20 — Duy đo test (3.191 câu) MỘT lần:** 3 chỉ tiêu ngưỡng đạt; nhưng cascade (cận trên, LLM đúng 100%) 0,9883 không vượt model một ngưỡng 0,75 (0,9885) vì τ_hi của account (0,135)/access (0,305) < 0,75 nhận thẳng thêm nhãn sai; test dễ hơn val (97,7% vs 91,6% exact-match). **Hệ quả [Đề xuất, chốt khi làm cascade]:** quy tắc τ_hi_dùng = max(τ_hi P11, 0,75) ("chắc có" không lỏng hơn cách một ngưỡng → cascade không kém baseline khi LLM tốt — lập luận cấu trúc, không chỉnh số theo test); so 3 cấu hình trên **val**; tập test model coi như **đã xem một lần (10/10)** — không đo lại tới báo cáo cuối; Duy soát trùng/gần trùng train–test (khoảng cách val–test lớn). **10/10 12:00 — kết quả trên VAL:** (a) một ngưỡng 0,75: macro-F1 0,9531 / exact 91,57%, 0% xuống LLM; (b) cascade P11: trần 0,9680 / 93,22%, 11,58% xuống LLM; (c) "chắc có" = max(τ_hi, 0,75): trần 0,9730 / 94,40%, 13,62% xuống LLM; cận dưới (b)/(c) ≈ (a) − 0,5 điểm (LLM vô dụng). **Chốt cấu hình cascade = (c)** (trần cao nhất, ≤ 30% xuống LLM của P11). Giới hạn ghi báo cáo: ~5,6% câu sai với điểm ~0,98 (model tự tin sai — cascade không bắt; temperature scaling P11 §4.2 chưa làm); ngưỡng chọn và đo cùng val (lạc quan). **Soát rò rỉ:** 0 câu trùng/gần trùng ≥ 0,92; test gần train hơn val có hệ thống (≥ 0,70: test 2,57% vs val 0,35%; trung vị 0,439 vs 0,371) → chia tập chưa tách hẳn theo mẫu câu (P11) ở mức 0,5–2,6% test; báo cáo cuối thêm một con số test bỏ 82 câu ≥ 0,70 (đo cùng lượt cuối, không đo riêng trước) | B02, B03-B05, P11, P4, M9 luật 12/13 | 5 | **Có** | Đã chốt 10/10 (T23a) |
| D-45 | **Lệch D-33 cho model hiện có:** `injection-clf` = XLM-R (safetensors fp32, ~1,1 GB), không mDeBERTa-v3 ONNX int8; chưa có `thresholds.json` (ngưỡng là hằng `TAU_BLOCK/TAU_PASS` trong `guard/injection.py` — chỉ tác dụng ở `active`). Số đo ML-KIEM 03/10: câu ngắn p95 31,8 ms (đạt < 100 ms), câu 3 cửa sổ p95 290 ms (**không đạt** mốc 100 ms của P4/P11 — ghi nhận); p95 khi chung hàng chờ với rerank chưa đo. Lý do: model nhóm đã huấn luyện xong trên nền này; đổi nền = huấn luyện lại | P11 §4.3, §5.1, B02 §7, P4 | 5 | **Có** | Đã chốt 10/10 (T23a) |
| D-46 | **`TOOL_MAP` (B6) mở rộng:** kiểu `tuple[str, ...]`; `access` thêm `check_account_status` (trạng thái/phòng ban/lý do vô hiệu của `requested_for`), `software` thêm `check_device_registered` (chủ máy). Lý do: fact bảng 4.3 Phase 5 cần hai tool này; giữ nguyên tắc "fact chỉ từ tool ở B6", không để B11 thu fact | B6 mục 0.3 [Chốt cũ], `tools/specs.py` | 5 | Không | Đã chốt 10/10 (làm ở T20a) |
| D-47 | **Hợp đồng dựng `Action` cho 4 intent (T20a):** bảng `PARAMS_BY_ACTION` một nguồn (`domain/action.py`) — mỗi `action_type` có đúng tập khoá `params`; không slot chữ tự do (`reason`, `justification`, `version`) nào vào `params` (nợ N1 của 6B); `extend_permission` không mang mức quyền; tên phần mềm chuẩn hoá không dấu cách; `requested_for` của account **và access** = `target_user` nếu có (access cần để R12 chạm được đầu-cuối — tài khoản bị vô hiệu không tự đăng nhập xin quyền); `target_user`, `resource_path`, `software_name` phải có trong câu người dùng (chống LLM bịa đích); slot bắt buộc theo hành động (`required_by_action`); fact 3 intent mới tính lại toàn bộ ở B11 từ slot cuối | B11 §0.3, §4; B06; P6→P5 #8 (danh sách trắng 6C) | 5 | Không | **Đã chốt 13/10** (Tuấn Anh duyệt PLAN-T20a, Q-T20a-2) |
| D-48 | **Thực thi + hoàn tác theo từng bước (T24):** `install_software` có phí = ① `assign_paid_license` (không hoàn tác được) → ② `install_software` (hoàn tác `uninstall_software`); bước ① có khi `license_paid is not False` (**thiếu fact → coi như có phí**); cài lỗi sau khi đã cấp license → **không gọi hoàn tác** (license không thu hồi qua tool) + ghi chú bàn giao nói rõ license đã cấp. Executor chung `PlanExecutor`: bước không hoàn tác được ghi `not_reversible`, không gọi; mọi bước đã xong đều không hoàn tác được → `not_attempted`. Tin B18 + ghi chú bàn giao theo mẫu từng hành động, chỉ ghép định danh qua regex | B17 §3–5; `executor/*`; cổng 5 "phần mềm có phí lỗi khi cài" | 5 | Không | **Đã chốt 13/10** (duyệt PLAN-T24; + Q-T24-6: `same_department` chỉ bỏ khi cả hai phòng ban rỗng; Q-T24-7: `version` chỉ số chấm, `software` trong tin lấy từ `params`) |
| D-49 | **Yêu cầu nhiều ý (T20b):** (a) **Q5** — ticket con bắt đầu ở **B6**, intent + slot lấy từ phần tử B3 của cha (seed bền trong checkpoint cha trước khi con chạy), không chạy lại B1/B2/B3 → không tốn thêm LLM, không lệch phân loại với cha, con không tự tách tiếp, con không bao giờ `S_BLOCKED` (theo B03 §5.3, P1 §8 — thay cách hiểu "con quay lại B3" của bảng 2.1); (b) **ý lẫn** — câu ≥ 2 ý có ít nhất 1 ý chạy được thì tách **mọi** ý; ý ngoài phạm vi / `confidence < TAU_INTENT` / intent chưa bật / `span` không có trong câu thành ticket con đóng ngay E1 (`reason_detail` riêng, mới: `split_span_invalid`); 0 ý chạy được → cả câu E1 như cũ; (c) slot của mỗi ý chỉ lấy trong `span` của chính ý; (d) tổ hợp con đủ 3 loại kết quả → cha `S_RESOLVED` + `PARTIALLY_ESCALATED` [Đề xuất] | B03 §5.2–5.4, P1 §8, bảng 2.1; phase5 §5.2 | 5 | Nên báo (a) | **Đã chốt 13/10** (a), (b) — Tuấn Anh; (c), (d) theo spec T20b, soát ở PLAN |

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
| 4b | Q-4-L, M, N, P, Q, R; Q-4b-1…8 | Xung đột → Trưởng BP [Chốt]; R17/R18/R19 thêm `device_owner_is_requester`; đồng bộ `users` từ AD; chuỗi quản lý; seed `l1_lead`; B17 kiểm người đã duyệt | mục 5, 5.6, 5.7 |
| 4c | Q-4c-1…3 | `note` vào `_POINT_COLUMNS`; nhắc trên `SqlDeadlineStore`; giữ 403 route quyết | mục 6.4 |
| 4d | Q-4d-1…10, TQ-14…17 | Ghi đè `POST /api/tickets/{id}/override` (1 dòng audit `OVERRIDE`, không đổi ticket, cần đăng nhập lại ≤ 10 phút); `audit_check` chỉ đọc, kiểm đúng chỗ code ghi (4 cột audit chưa từng được ghi → Việc treo 31); B16 so hash state + phiếu trước khi thực thi → E5 (Q-4d-3), B17 thêm lớp so hash phiếu; `make gate4` không đăng nhập manager (Q-4d-9), g4-12 theo ticket của lần chạy (Q-4d-10); làm nóng rerank ở preflight (Việc treo 32) | mục 7.7, 7.8, 7.9 |

**Phase 5–6 (01/10/2026):** câu hỏi `Q-5-1…6`, `Q-6-1…9` (Tuấn Anh đồng ý theo khuyến nghị; Q-6-8 `full_auto` hoãn tới trước 6C) và lỗ hổng `G5-1…7`, `G6-1…7` nằm ở `claude/phase5-6-phan-tich-va-chia-chang.md`, `build/phase5-thiet-ke-chi-tiet.md` mục 2, `build/phase6-thiet-ke-chi-tiet.md` mục 2. Quyết định kỹ thuật D-35…D-46 ở mục 3. **Q-5-6 (09/10):** `procedure_doc` của 6 hành động mới theo K2 thật — `reset_password` KB-ACC-001, `unlock_account` KB-ACC-002, `install_software` KB-SW-001, `view_permissions` KB-ACS-005, `grant_permission` KB-ACS-001, `extend_permission` KB-ACS-003 (`phase5-thiet-ke-chi-tiet.md` bảng 4.2). **Q-T22a-8 (09/10):** T20a thêm fact `existing_permission_level` + R10 đòi `in [read, write]`; không bật `access` trước đó. **Q-5-7 (10/10):** bật `ENABLED_INTENTS` 4 intent ở **T24** (không ở T20) — `check_plans` từ chối khởi động khi intent bật thiếu `PLAN`/mẫu B18. **Q-5-8 (10/10):** `existing_permission_level` = mức cao nhất (read < write < full) trên **mọi** dòng (còn hạn và hết hạn) của đúng `resource_path`; không dòng nào → không đặt fact. **Q-5-9 (10/10):** `/classify` 422 `too_many_windows` → backend coi là lỗi lớp 3 → xuống L4 (không E9); 422 khác giữ `MlContractError`. **T20a ĐÓNG (`03b4450`, 13/10):** chốt khi hiện thực ở phase5 v0.4 mục 5.1.11 (cờ `target_is_other` khi `target_user` bị bỏ ở B3 / `clarify_wait`). **T24 (13/10, phase5 v0.4 mục 7):** D-48; bật 4 intent (Q-5-7); `make gate5`. **T20a (spec v0.3 mục 5.1):** D-47; roster `account`/`software`/`access` = roster VPN (Q-4-H); tin từ chối theo đích (`target_phrase`); không bật intent. **Kế hoạch (10/10):** T23a → (6B) → T20a (đơn ý) → T24 (+ bật intent) → T20b (nhiều ý); cổng 5 ~20–21/10 (`phase5-thiet-ke-chi-tiet.md` mục 8).

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
| 01/10/2026 | §1.1: ghi chốt Phase 4 (R17–R19 đòi chủ máy) + trỏ điều kiện R01–R15 (T22a); §3: D-35…D-43 (Phase 5–6, chốt hướng — chữ chốt khi đóng từng chặng); §4.1: dòng 4b, 4c và Phase 5–6; mục báo GVHD thêm D-38, D-41, D-43 |
| 03/10/2026 | §4.1: dòng 4d. **Cổng 4 đạt, Phase 4 đóng phần code** — 4d DỪNG 2 `858573d` (CI `37040959717`), cây gộp PR #24 của M9 `1455b55` (CI `37041941104`). Tạ Duy Anh chạy trên máy riêng (Windows + WSL 2), commit `1455b55`, ngoài giờ: `make gate3 S=all` 78 PASS / 0 FAIL (**trả NỢ-3-1**); `make gate4 S=all` lượt 2 73 PASS / 0 FAIL (lượt 1: 60/4 — g4-03, g4-05 ra E2 vì ml-service hết giờ khi máy tải nặng; xử lý an toàn, không sửa code). Mở Việc treo 35 (worker ~98% CPU sau gate4, chưa giải thích). Chi tiết: `phase4-thiet-ke-chi-tiet.md` mục 7.9 |
| 09/10/2026 | §4.1: Q-5-6 (`procedure_doc` 6 hành động mới theo K2 thật, 18 bài). Bản này (có D-35…D-43) vào repo cùng spec Phase 5 ở chặng T22a, thay bản repo cũ chỉ có phần Phase 4 |
| 10/10/2026 | §3: D-44 (B2 `shadow` + B3 không dùng model ở Phase 5 — ngoại lệ tạm luật 8/D-32, kèm điều kiện chuyển), D-45 (lệch D-33: XLM-R fp32, chưa `thresholds.json`), D-46 (`TOOL_MAP` mở rộng); §4.1: Q-T22a-8, Q-5-7…9, kế hoạch T23a → T20a → T24 → T20b; mục báo GVHD thêm D-44…46. Nguồn: phiên PHAN-TICH-P5 (`.verify/phan-tich-p5/bao-cao.md`) + Tuấn Anh chốt 10/10 |
| 10/10/2026 | §2: Q-6-8 `full_auto` chốt C (yêu cầu P6→P5 #9, nguyên văn); D-44: kết quả thresholds/cascade của Duy (val/test) |
| 13/10/2026 | §1.1: điều kiện R01–R15 chốt theo T22a (`2ffb005`) + R10 thêm `existing_permission_level` ở T20a; §3: D-35, D-41 chữ chốt; D-47 (hợp đồng `Action` 4 intent — chốt khi duyệt PLAN-T20a 13/10); §4.1: dòng T20a |
| 13/10/2026 | §3: D-48 (chốt khi duyệt PLAN-T24 + Q-T24-6/7); §4.1: T20a đóng `03b4450`, dòng T24 |
| 13/10/2026 | §3: D-49 (T20b — con vào B6, tách ý lẫn thành con E1; Q5 đóng) |
