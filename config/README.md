Cấu hình nghiệp vụ và hành vi AI: policy.json, llm.yaml, patterns, slots, action_metadata, vi_abbrev. Xem docs/spec/build/01-kien-truc-project.md mục 3.

Sửa file ở đây là **đổi hành vi agent** — chạy lại test (và probe nếu có) trước khi báo xong.

- `privacy_patterns.json` (3e, B2 L1): 10 luật che bí mật/PII, **đúng thứ tự** pem → jwt → api_key → password → otp →
  entropy → email → phone → cccd → bank_account (`guard/patterns.PRIVACY_RULE_ORDER` kiểm); nhóm tên `v` = chỉ thay
  phần giá trị. `entropy_exclude`: token luật 6 bỏ qua (đường dẫn thật, đường dẫn tương đối có đuôi file trong danh
  sách cố định, mã thiết bị, mã lỗi hex, URL, username, chữ số, email). Nới loại trừ = cho bí mật lọt — có mutation
  M-3e-5/13/15/16 canh.
- `injection_patterns.json` (3e, B2 L2): ≥ 11 mẫu, id `^[A-Z]+-\d{2}$` không trùng, đủ 4 nhóm (override,
  impersonation, system_spoof, prompt_leak); regex viết trên bản **không dấu, chữ thường**.
- File mẫu hỏng (JSON sai, thiếu/thừa trường, regex không biên dịch, sai thứ tự) → backend và worker **không khởi động**.
- `slots.yaml` (3f): `intents.vpn` — required/optional, `action_types`, `value_rules`. Slot trùng tên fact bị từ chối
  lúc nạp. Luật "mã máy/mã lỗi/lý do phải có thật trong câu người dùng" và "> 100 ký tự → bỏ" nằm trong CODE
  (`domain/slots.py`), không tắt được bằng file này.
- `action_metadata.yaml` (3f): thuộc tính rủi ro từng hành động; mọi `action_type` của `slots.yaml` phải có dòng, thiếu →
  không khởi động (không mặc định reversible); `reversible` phải khớp `reversibility`.
- `policy.json`: `TAU_INTENT` (3f, B3 đường LLM, 0,6).
- `prompts/b03_classify.yaml` v2 (3f): câu xã giao/đệm không là một ý; việc ngoài phạm vi có yêu cầu LÀ một ý riêng —
  chất lượng thật đo ở mốc G (probe).
- `scripted/vpn.yaml` (3f): preset stack `[fake:vpn]` — luồng VPN thật B2 → B3 → B6 khi KHÔNG đặt `FAKE_SCENARIO`.
