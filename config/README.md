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
