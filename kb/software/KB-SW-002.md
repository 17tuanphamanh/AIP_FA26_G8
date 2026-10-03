---
doc_id: KB-SW-002
version: 1
request_type: software
doc_type: policy
owner: it_mgr01
updated_at: 2026-10-03
sensitivity: internal
enabled: true
title: "Yêu cầu phần mềm ngoài danh mục hoặc có phí"
distractor: false
tags: [software, ngoài danh mục, phần mềm có phí, phê duyệt]
---

## Phần mềm ngoài danh mục

Catalog hiện tại gồm 7-Zip, Adobe Acrobat Pro, AutoCAD, Microsoft Office, Microsoft Project, Visual Studio Code và Zoom Workplace.

Phần mềm không xuất hiện trong danh sách này được xem là ngoài danh mục.

Khi cần một phần mềm ngoài danh mục, người dùng cần ghi đúng tên phần mềm cần sử dụng. Không thay tên phần mềm đó bằng tên một phần mềm đã có trong catalog.

Danh sách giá trị hợp lệ hiện tại không cung cấp các ví dụ cụ thể về phần mềm ngoài danh mục, vì vậy bài này không tự bổ sung tên phần mềm khác.

## Phần mềm có phí trong danh mục

Adobe Acrobat Pro, AutoCAD và Microsoft Project có `license_type: paid`.

Cả ba phần mềm trên đồng thời có `requires_approval: true`.

Vì vậy, dù các phần mềm này đã có trong catalog, yêu cầu cài chúng vẫn thuộc nhóm cần duyệt theo dữ liệu hiện tại.

7-Zip, Microsoft Office, Visual Studio Code và Zoom Workplace có `license_type: free` và `requires_approval: false`.

Không suy luận giá tiền cụ thể từ giá trị `paid`, vì dữ liệu hiện tại không cung cấp giá.

## Thời gian duyệt

Đối với các yêu cầu thuộc trường hợp cần duyệt, fact hiện tại cho phép sử dụng SLA duyệt.

Yêu cầu được duyệt trong 30 phút.

Tài liệu hiện tại không xác định ai là người duyệt yêu cầu phần mềm. Vì vậy không ghi trưởng phòng, IT Manager hoặc bất kỳ vai trò cụ thể nào là người duyệt nếu chưa có nguồn bổ sung.

Tài liệu cũng không cung cấp số lượng giấy phép, thời gian cài đặt hoặc thứ tự các bước xử lý sau khi yêu cầu được duyệt.

## Thông tin cần giữ đúng với catalog

Người dùng cần sử dụng đúng tên phần mềm trong catalog.

Adobe Acrobat Pro có tên catalog là adobe-acrobat-pro. AutoCAD có tên catalog là autocad. Microsoft Project có tên catalog là ms-project.

7-Zip có tên catalog là 7zip. Microsoft Office có tên catalog là ms-office. Visual Studio Code có tên catalog là vscode. Zoom Workplace có tên catalog là zoom.

Không tự thay đổi trạng thái `requires_approval` hoặc `license_type` của phần mềm trong nội dung KB.