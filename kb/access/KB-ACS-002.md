---
doc_id: KB-ACS-002
version: 1
request_type: access
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-04
sensitivity: internal
enabled: true
title: "Mức độ nhạy của thư mục và ai duyệt"
distractor: false
tags: [access, thư mục, độ nhạy, phê duyệt]
---

## Các mức độ nhạy của thư mục

Danh sách tài nguyên hiện tại sử dụng ba mức độ nhạy là low, medium và high.

engineering/specs có mức độ nhạy medium.

finance/Q3 và hr/salaries có mức độ nhạy high.

finance/public-reports và shared/templates có mức độ nhạy low.

Mức độ nhạy phải được lấy đúng theo danh sách tài nguyên. Không tự thay đổi sensitivity dựa trên tên thư mục hoặc dựa trên đánh giá chủ quan về nội dung.

## Phòng ban sở hữu thư mục

engineering/specs thuộc phòng Engineering.

finance/Q3 và finance/public-reports thuộc phòng Finance.

hr/salaries thuộc phòng HR.

shared/templates thuộc phòng IT.

owner_department và sensitivity là hai thông tin khác nhau. Ví dụ, finance/Q3 và finance/public-reports đều thuộc Finance nhưng lần lượt có mức high và low.

Vì vậy không nên suy luận mức độ nhạy chỉ từ phòng ban sở hữu.

## Ai duyệt quyền truy cập

Nguồn dữ liệu hiện tại chưa xác định người hoặc vai trò cụ thể chịu trách nhiệm duyệt quyền đối với từng thư mục.

Do đó tài liệu này không khẳng định rằng trưởng phòng, quản lý trực tiếp, IT Manager hoặc owner_department là người duyệt.

Đối với yêu cầu thuộc quy trình cần duyệt, yêu cầu được duyệt trong 30 phút.

SLA 30 phút chỉ xác định thời gian duyệt. Giá trị này không cho biết danh tính hoặc vai trò của người duyệt.

## Khi chưa xác định được người duyệt

Nếu cần biết chính xác ai duyệt quyền cho thư mục low, medium hoặc high, cần sử dụng thêm nguồn dữ liệu hoặc cấu hình xác định quy tắc phê duyệt.

Không tự suy luận rằng phòng ban sở hữu tài nguyên chính là người duyệt.

Khi cần hỗ trợ, liên hệ IT qua máy lẻ 1234.

Thông tin người duyệt chỉ nên được bổ sung vào KB sau khi có nguồn hợp lệ xác nhận.