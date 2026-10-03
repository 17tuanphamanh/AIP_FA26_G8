---
doc_id: KB-SW-003
version: 1
request_type: software
doc_type: troubleshooting
owner: it_mgr01
updated_at: 2026-10-03
sensitivity: internal
enabled: true
title: "Lỗi cài đặt phần mềm thường gặp"
distractor: false
tags: [software, cài đặt, lỗi cài đặt, troubleshooting]
---

## Kiểm tra phần mềm có trong catalog hay không

Khi một yêu cầu cài đặt phần mềm không thực hiện được, trước tiên cần xác định phần mềm đó có nằm trong catalog hiện tại hay không.

Catalog hiện tại gồm 7-Zip, Adobe Acrobat Pro, AutoCAD, Microsoft Office, Microsoft Project, Visual Studio Code và Zoom Workplace.

Nếu phần mềm không xuất hiện trong danh sách này, phần mềm được xem là ngoài danh mục. Trường hợp đó không nên được xử lý giống một phần mềm đã có trong catalog.

Tài liệu hiện tại không cung cấp tên các phần mềm ngoài danh mục cụ thể.

## Kiểm tra yêu cầu có cần duyệt hay không

Adobe Acrobat Pro, AutoCAD và Microsoft Project có `requires_approval: true`.

7-Zip, Microsoft Office, Visual Studio Code và Zoom Workplace có `requires_approval: false`.

Vì vậy, khi một yêu cầu liên quan đến Adobe Acrobat Pro, AutoCAD hoặc Microsoft Project chưa được xử lý, cần phân biệt trạng thái cần duyệt với một lỗi cài đặt kỹ thuật.

Yêu cầu được duyệt trong 30 phút.

Tài liệu hiện tại không cung cấp trạng thái chi tiết của từng yêu cầu cài đặt thực tế.

## Không tự suy đoán lỗi kỹ thuật

Danh sách giá trị hợp lệ hiện tại không cung cấp mã lỗi cài đặt, nguyên nhân lỗi, thông báo lỗi, phiên bản hệ điều hành được hỗ trợ hoặc yêu cầu phần cứng cho các phần mềm.

Vì vậy không nên tự kết luận rằng việc cài đặt thất bại là do thiếu dung lượng, thiếu quyền, lỗi mạng, lỗi bộ cài hoặc một nguyên nhân kỹ thuật cụ thể khác.

Khi cần bổ sung một lỗi kỹ thuật vào KB, lỗi đó cần có nguồn hợp lệ trước khi được viết vào tài liệu.

## Thông tin hiện có để phân loại yêu cầu

Thông tin hiện tại chỉ cho phép phân loại yêu cầu dựa trên tên phần mềm, việc phần mềm có trong catalog hay không, `requires_approval` và `license_type`.

Ví dụ, AutoCAD có trong catalog, `requires_approval: true` và `license_type: paid`.

Visual Studio Code có trong catalog, `requires_approval: false` và `license_type: free`.

Nếu cần hướng dẫn khắc phục một lỗi cài đặt cụ thể, dữ liệu hiện tại chưa đủ để viết bước xử lý kỹ thuật.