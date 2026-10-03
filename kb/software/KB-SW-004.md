---
doc_id: KB-SW-004
version: 1
request_type: software
doc_type: howto
owner: it_mgr01
updated_at: 2026-10-03
sensitivity: internal
enabled: true
title: "Cập nhật phiên bản phần mềm đã cài"
distractor: true
tags: [software, cập nhật, phiên bản, phần mềm đã cài]
---

## Phần mềm thuộc catalog hiện tại

Catalog hiện tại gồm 7-Zip, Adobe Acrobat Pro, AutoCAD, Microsoft Office, Microsoft Project, Visual Studio Code và Zoom Workplace.

Khi người dùng hỏi về cập nhật phần mềm, trước tiên cần xác định đúng tên phần mềm đang nói tới.

Nếu phần mềm không có trong danh sách này, dữ liệu hiện tại chỉ cho phép xác định đó là phần mềm ngoài danh mục. Không sử dụng tài liệu này để tự coi một phần mềm ngoài danh mục là phần mềm đã có trong catalog.

## Trạng thái phê duyệt của phần mềm

Adobe Acrobat Pro, AutoCAD và Microsoft Project có `requires_approval: true`.

7-Zip, Microsoft Office, Visual Studio Code và Zoom Workplace có `requires_approval: false`.

Đây là trạng thái được ghi trong catalog hiện tại.

Tuy nhiên, danh sách giá trị hợp lệ không nói rằng việc cập nhật một phần mềm đã cài có giữ nguyên hay thay đổi yêu cầu phê duyệt này. Vì vậy bài này không tự kết luận rằng cập nhật luôn cần duyệt hoặc luôn không cần duyệt.

## Phiên bản phần mềm

Danh sách giá trị hợp lệ hiện tại không cung cấp số phiên bản của bất kỳ phần mềm nào trong catalog.

Vì vậy không ghi rằng 7-Zip, Adobe Acrobat Pro, AutoCAD, Microsoft Office, Microsoft Project, Visual Studio Code hoặc Zoom Workplace phải được cập nhật lên một phiên bản cụ thể.

Không tự thêm số phiên bản, ngày phát hành hoặc phiên bản tối thiểu nếu chưa có fact hoặc nguồn hợp lệ.

Nếu cần ghi một số phiên bản vào KB, thông tin đó cần được xác nhận trước.

## Giới hạn của tài liệu hiện tại

Nguồn hiện tại không mô tả thao tác cập nhật phần mềm, vị trí nút cập nhật, nguồn tải bản cập nhật hoặc cách xử lý khi cập nhật thất bại.

Vì vậy tài liệu này chỉ xác định phạm vi các phần mềm có trong catalog và trạng thái `requires_approval` hiện có.

Các bước cập nhật kỹ thuật chỉ nên được bổ sung khi có tài liệu nguồn mô tả chính xác cách cập nhật phần mềm.

Bài này được đánh dấu là tài liệu gây nhiễu để phân biệt yêu cầu cập nhật phần mềm với yêu cầu cài mới.