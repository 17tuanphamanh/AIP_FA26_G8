---
doc_id: KB-ACS-003
version: 1
request_type: access
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-04
sensitivity: internal
enabled: true
title: "Quyền truy cập có thời hạn và gia hạn quyền"
distractor: false
tags: [access, quyền có thời hạn, gia hạn quyền, thư mục]
---

## Quyền truy cập có thời hạn

Một yêu cầu quyền truy cập có thể liên quan đến việc sử dụng tài nguyên trong một khoảng thời gian nhất định.

Nguồn dữ liệu hiện tại chưa cung cấp số ngày cụ thể của quyền truy cập có thời hạn. Vì vậy tài liệu này không tự quy định quyền được cấp trong bao nhiêu ngày.

Nếu cần sử dụng một thời hạn cụ thể trong KB, giá trị đó cần được xác nhận bằng fact hoặc nguồn cấu hình hợp lệ trước khi bổ sung.

Không tự sử dụng một số ngày chưa có trong kb-facts.md.

## Tài nguyên liên quan đến quyền truy cập

Các tài nguyên hiện tại gồm engineering/specs, finance/Q3, finance/public-reports, hr/salaries và shared/templates.

Mỗi tài nguyên có mức độ nhạy và phòng ban sở hữu riêng. Khi yêu cầu quyền có thời hạn hoặc gia hạn quyền, cần xác định đúng tài nguyên liên quan.

Không tự thay đổi sensitivity hoặc owner_department của tài nguyên khi tạo yêu cầu.

Nếu tài nguyên không có trong danh sách hiện tại, dữ liệu nguồn chưa đủ để xác định chính sách áp dụng.

## Gia hạn quyền truy cập

Khi người dùng cần tiếp tục sử dụng một tài nguyên sau thời hạn hiện tại, yêu cầu gia hạn cần gắn với đúng tài nguyên mà người dùng đang sử dụng.

Nguồn hiện tại chưa xác định thời điểm phải gửi yêu cầu gia hạn, số ngày được gia hạn hoặc số lần được phép gia hạn.

Vì vậy tài liệu này không tự ghi các giá trị như gia hạn trước một số ngày hoặc kéo dài quyền thêm một số ngày cụ thể.

Các con số đó chỉ được thêm khi đã có fact tương ứng.

## Phê duyệt yêu cầu gia hạn

Đối với yêu cầu thuộc quy trình cần duyệt, yêu cầu được duyệt trong 30 phút.

Nguồn hiện tại chưa xác định người duyệt yêu cầu gia hạn hoặc điều kiện chi tiết để một yêu cầu gia hạn được chấp thuận.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Nếu cần bổ sung thời hạn quyền, thời điểm gia hạn hoặc người duyệt, phải có thêm nguồn hợp lệ trước khi sửa bài.