# Hướng dẫn soạn Knowledge Base (KB) cho nhóm

*Dành cho người soạn tài liệu KB (mặc định TV1) và người soát (TV3). Đi kèm các file mẫu trong cùng thư mục: `kb-facts.md`, `KB-VPN-001.md`, `KB-VPN-003.md`, `retrieval_set.mau.yaml`. Thiết kế kỹ thuật: `build/phase3-thiet-ke-chi-tiet.md` mục 5 (ingest) và mục 12. Phiên bản 1.0 — 27/09/2026.*

---

## 1. KB dùng để làm gì

Agent **chỉ được trả lời bằng nội dung trong KB**, và mọi câu trả lời phải trích dẫn đoạn tài liệu. Không có tài liệu phù hợp thì agent chuyển L2 (E3), chứ không tự bịa. Vì vậy:

- KB **thiếu** → nhiều ca chuyển L2 thừa (tỉ lệ tự động hóa thấp).
- KB **sai số liệu** → agent trả lời sai quy trình bảo mật (nguy hiểm hơn thiếu).
- KB **viết lộn xộn** → hệ thống tìm sai đoạn, câu trả lời thiếu bước.

Mỗi tài liệu được máy cắt thành các **đoạn** theo heading `##`/`###`. Máy tìm theo đoạn, không theo cả bài. Viết sao cho **mỗi đoạn đọc riêng vẫn hiểu được**.

## 2. Thư mục và tên file

```
kb/
├── kb-facts.md                  # số liệu chuẩn — MỘT nguồn sự thật cho mọi con số
├── vpn/KB-VPN-001.md            # tên file = doc_id
├── vpn/KB-VPN-003.md
├── account/ … software/ … access/ … general/
└── eval/retrieval_set.yaml      # bộ câu kiểm tra truy hồi
```

- Tên file **phải bằng** `doc_id`, nằm trong thư mục đúng `request_type`. Sai → máy từ chối cả lượt nạp.
- `doc_id` dạng `KB-<LOẠI>-<3 chữ số>`: `VPN`, `ACC` (account), `SW` (software), `ACS` (access), `GEN` (general).

## 3. Front matter (phần đầu file, bắt buộc)

```yaml
---
doc_id: KB-VPN-003
version: 1
request_type: vpn            # vpn | account | software | access | general
doc_type: troubleshooting    # policy | howto | troubleshooting | faq
owner: it_mgr01
updated_at: 2026-09-27
sensitivity: internal        # public | internal | restricted
enabled: true
title: Xử lý lỗi VPN 809 trên Windows
distractor: false
tags: [vpn, lỗi 809, windows]
---
```

| Trường | Quy tắc |
|---|---|
| `version` | Số nguyên ≥ 1. **Sửa bất kỳ chữ nào trong bài → tăng `version`.** Không tăng thì máy từ chối nạp ("nội dung đã đổi nhưng chưa tăng version") |
| `owner` | Mã người dùng (user_id) của người chịu trách nhiệm bài, chữ thường/số/gạch dưới — dùng mã có trong hệ thống giả lập, ví dụ `it_mgr01` (Trưởng bộ phận IT), `l2_01`. Không dùng tên thật hay email |
| `sensitivity` | `public`: ai cũng xem được. `internal`: mọi nhân viên. `restricted`: chỉ L1, L2, Trưởng BP (ví dụ cấu hình máy chủ) |
| `enabled` | `false` = tài liệu cũ, không còn dùng; máy bỏ qua khi nạp |
| `title` | 5–120 ký tự, nêu đúng chủ đề — tiêu đề được ghép vào đầu **mọi** đoạn |
| `distractor` | `true` cho tài liệu gây nhiễu (mục 7) — vẫn là tài liệu đúng, chỉ đánh dấu để đo |
| `tags` | **Chỉ là nhãn cho người đọc — KHÔNG vào chỉ mục tìm kiếm** (chuỗi được index = `title › heading` + thân đoạn; soát 12/11, agent 08 F-V6). Thêm tag không sửa được ca truy hồi kém / E3: muốn máy tìm ra thì sửa tiêu đề, heading hoặc thân bài (mục 4.8) |
| Trường khác | Không được thêm trường ngoài bảng này |

## 4. Quy tắc viết thân bài

1. **Không viết heading `#` (H1).** Tiêu đề lấy từ `title`.
2. **Mỗi `##` một ý trọn vẹn.** Ví dụ "Nguyên nhân thường gặp", "Cách khắc phục trên mạng gia đình", "Khi nào cần liên hệ IT". Dùng `###` khi một ý có nhiều phần con.
3. **Độ dài mỗi mục `##`:** khoảng 80–250 từ. Mục quá dài máy sẽ cắt giữa chừng theo câu; mục quá ngắn (< 50 từ) máy gộp với mục bên cạnh.
4. **Cả bài:** 300–800 từ.
5. **Hướng dẫn nhiều bước:** đánh số `1.`, `2.`… Mỗi bước một hành động. Bước nào có điều kiện thì viết rõ "Nếu … thì …".
6. **Mỗi đoạn tự đủ nghĩa:** không viết "như trên", "bước đó" — nhắc lại tên đối tượng ("ứng dụng ABC Connect", "chứng chỉ VPN").
7. **Mã lỗi, tên dịch vụ, mã máy viết nguyên dạng:** `809`, `0x8004010F`, `IKEEXT`, `LAP-0342`. Máy tìm theo đúng chuỗi này.
8. **Có cả cách nói thường gặp** một lần trong bài: "mật khẩu (mk)", "không vào được VPN / không kết nối được VPN".
9. **Số liệu chỉ lấy từ `kb-facts.md`.** Cổng, thời hạn, số thiết bị tối đa, giờ hành chính, thời gian duyệt… viết đúng như file này. Máy tự kiểm; lệch là không nạp được.
10. **Không bao giờ ghi bí mật thật:** mật khẩu, khóa, token, tên máy chủ nội bộ thật. Dùng tên giả trong `kb-facts.md`.
11. Không dùng ảnh, không bảng lớn (bảng ≤ 5 dòng). Máy chỉ đọc chữ.
12. Viết tiếng Việt có dấu, câu ngắn, giọng hướng dẫn trực tiếp ("Bạn mở…").

## 5. `kb-facts.md`

Đây là nơi **duy nhất** chứa con số chuẩn. Khi cần một con số mới (ví dụ thời hạn mật khẩu), **thêm fact vào `kb-facts.md` trước**, rồi mới viết vào tài liệu. Cách thêm: xem chú thích trong file mẫu. Người soát kiểm fact mới có khớp cấu hình hệ thống (`config/policy.json`, `mock_services/seed.json`) không.

## 6. Danh sách tài liệu cần soạn

**Cổng K1 (VPN, trước khi chọn ngưỡng ở Phase 3):**

| doc_id | Tiêu đề gợi ý | `doc_type` | `sensitivity` | Phục vụ |
|---|---|---|---|---|
| KB-VPN-001 | Tổng quan dịch vụ VPN công ty (có mẫu) | faq | public | TC04 "VPN dùng cổng nào" |
| KB-VPN-002 | Cài đặt và kết nối ABC Connect trên Windows | howto | internal | Hướng dẫn tự làm |
| KB-VPN-003 | Xử lý lỗi VPN 809 trên Windows (có mẫu) | troubleshooting | internal | TC05 |
| KB-VPN-004 | Gia hạn và cấp lại chứng chỉ VPN | policy | internal | TC02, TC06 |
| KB-VPN-005 | Đăng ký thiết bị mới để dùng VPN | policy | internal | TC09 (cần duyệt) |

**Nên có thêm (để đo được giá trị của tìm kiếm, D-25):**

| doc_id | Tiêu đề gợi ý | Ghi chú |
|---|---|---|
| KB-VPN-006 | Cài đặt ABC Connect trên macOS | `distractor: true` — gần KB-VPN-002 nhưng khác hệ điều hành |
| KB-VPN-007 | Cấu hình máy chủ VPN cho IT | `sensitivity: restricted` |
| KB-VPN-008 | Các mã lỗi VPN khác (789, 812, 691) | `distractor: true` — gần KB-VPN-003 |

**Cố ý KHÔNG soạn:** tài liệu về MFA / xác thực hai lớp (kịch bản TC16 kiểm agent biết nói "chưa có thông tin").

**Cổng K2 (trước Phase 5):** thêm 4 tài liệu cho mỗi loại `account`, `software`, `access` — cùng quy tắc.

## 7. Tài liệu gây nhiễu (distractor)

Là tài liệu **đúng và hợp lệ** nhưng **gần chủ đề** với một tài liệu khác, để kiểm máy có chọn đúng không. Ba kiểu:

- Khác đối tượng: VPN Windows ↔ VPN macOS.
- Khác phiên bản quy trình: quy trình cũ (`enabled: false`) ↔ quy trình mới.
- Khác phạm vi: mã lỗi 809 ↔ các mã lỗi khác.

Mục tiêu dài hạn: khoảng 30% tổng số tài liệu là gây nhiễu.

## 8. Bộ câu kiểm tra truy hồi (`kb/eval/retrieval_set.yaml`)

Dùng để **chọn ngưỡng** "có căn cứ hay không" (xem mẫu `retrieval_set.mau.yaml`).

- **≥ 30 câu có đáp án:** mỗi câu ghi `expected_doc_ids` (tài liệu chứa câu trả lời).
- **≥ 20 câu không có đáp án** trong KB (`expected_doc_ids: []`), trong đó **≥ 8 câu gần chủ đề** (`near_topic: true`): VPN trên Linux, MFA, VPN cho khách bên ngoài…
- Viết như **người dùng thật gõ**: viết tắt (`ko`, `mk`, `dc`), không dấu, sai chính tả nhẹ, câu dài dòng, câu cộc lốc. **Không** chép câu trong tài liệu.
- Người viết câu **khác** người viết tài liệu (tránh câu hỏi "trúng" từ ngữ của bài).
- Có câu với `role: l1` hỏi nội dung `restricted` và cùng câu đó với `role: employee` (đáp án rỗng với employee).
- Bộ này **không** trộn với bộ kịch bản đánh giá M8.

## 9. Tự kiểm trước khi nộp

- [ ] Tên file = `doc_id`, đúng thư mục.
- [ ] Front matter đủ trường, không thừa trường; `updated_at` không ở tương lai.
- [ ] Không có `#` (H1); mỗi `##` một ý, 80–250 từ.
- [ ] Mọi con số có trong `kb-facts.md`.
- [ ] Không có bí mật thật, tên máy chủ thật, số điện thoại thật.
- [ ] Sửa bài cũ → đã tăng `version`.
- [ ] Đọc riêng từng mục `##`: vẫn hiểu là nói về cái gì.
- [ ] Chạy `make ingest ARGS=--dry-run` (nhờ Tuấn Anh nếu chưa dựng được máy): 0 lỗi.

## 10. Cách nộp

1. Tạo nhánh riêng, thêm/sửa file trong `kb/`.
2. Mở PR; người soát (TV3) đọc theo mục 9 và đối chiếu `kb-facts.md`.
3. Merge xong, Tuấn Anh chạy `make ingest` trên máy dev.
