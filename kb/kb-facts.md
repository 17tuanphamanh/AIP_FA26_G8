# Số liệu chuẩn của Knowledge Base (mẫu)

*Mọi con số trong tài liệu KB phải khớp file này. Máy đọc **đúng một** khối `yaml` bên dưới khi chạy `make ingest`. Công ty, tên miền, số máy lẻ đều là **giả lập** (Công ty ABC).*

## Cách đọc một fact

- `id`: tên fact, không dấu.
- `applies_to`: chỉ kiểm các tài liệu có `request_type` trong danh sách này.
- `regex`: mẫu tìm trong thân bài. **Mọi nhóm trong ngoặc tròn** bắt được phải có giá trị thuộc `allowed`. Dùng `(?:...)` cho nhóm không cần bắt.
- `allowed`: giá trị chuẩn.
- Tài liệu không nhắc tới con số đó → không lỗi.

## Thêm fact mới

1. Thêm một mục vào khối `yaml` bên dưới (thử regex trên câu mẫu trước).
2. Người soát xác nhận con số khớp cấu hình hệ thống (`config/policy.json`, `mock_services/seed.json`).
3. Sau đó mới viết con số vào tài liệu.

```yaml
facts:
  - id: vpn_gateway_host
    applies_to: [vpn]
    regex: '\b(vpn\.[a-z0-9-]+\.[a-z]{2,})\b'
    allowed: ["vpn.congty-abc.vn"]
    note: Địa chỉ máy chủ VPN

  - id: vpn_ikev2_ports
    applies_to: [vpn]
    regex: '(?i)IKEv2[^.\n]{0,60}?UDP\s*(\d{2,5})(?:\s*(?:và|,)\s*(\d{2,5}))?|UDP\s*(\d{2,5})(?:\s*(?:và|,)\s*(\d{2,5}))?[^.\n]{0,40}?IKEv2'
    allowed: ["500", "4500"]
    note: Giao thức chính IKEv2 dùng UDP 500 và 4500

  - id: vpn_sstp_port
    applies_to: [vpn]
    regex: '(?i)SSTP[^.\n]{0,40}?TCP\s*(\d{2,5})'
    allowed: ["443"]
    note: Giao thức dự phòng SSTP dùng TCP 443

  - id: vpn_client_min_version
    applies_to: [vpn]
    regex: '(?i)ABC Connect[^.\n]{0,20}?(?:phiên bản|bản)\s*(\d+\.\d+)|phiên bản\s+(?:thấp hơn|cũ hơn|dưới|tối thiểu|từ)\s+(\d+\.\d+)'
    allowed: ["3.2"]
    note: Phiên bản ứng dụng tối thiểu

  - id: vpn_cert_validity_days
    applies_to: [vpn]
    regex: '(?i)chứng chỉ[^.\n]{0,40}?hiệu lực\s*(\d{2,4})\s*ngày'
    allowed: ["365"]

  - id: vpn_cert_renew_window_days
    applies_to: [vpn]
    regex: '(?i)gia hạn[^.\n]{0,40}?trước\s*(\d{1,3})\s*ngày'
    allowed: ["30"]
    note: Được gia hạn từ 30 ngày trước khi hết hạn

  - id: vpn_max_devices
    applies_to: [vpn]
    regex: '(?i)tối đa\s*(\d{1,2})\s*thiết bị'
    allowed: ["2"]

  - id: business_hours
    applies_to: [vpn, account, software, access, general]
    regex: '(?i)giờ hành chính[^.\n]{0,40}?(\d{1,2}:\d{2})\s*(?:–|-|đến)\s*(\d{1,2}:\d{2})'
    allowed: ["08:00", "18:00"]
    note: Khớp policy.json business_hours; thứ Hai đến thứ Sáu

  - id: approval_sla_minutes
    applies_to: [vpn, account, software, access, general]
    regex: '(?i)(?:duyệt|SLA)[^.\n]{0,40}?(\d{1,3})\s*phút'
    allowed: ["30"]
    note: Khớp SLA_MINUTES

  - id: access_extend_max_days
    applies_to: [access]
    regex: '(?i)gia hạn[^.\n]{0,40}?(?:tối đa|không quá)\s*(\d{1,3})\s*ngày'
    allowed: ["90"]
    note: Khớp policy.json - luật cho phép tự gia hạn quyền (thời hạn gia hạn tối đa 90 ngày)

  - id: it_extension
    applies_to: [vpn, account, software, access, general]
    regex: '(?i)máy lẻ\s*(\d{3,5})'
    allowed: ["1234"]
```
