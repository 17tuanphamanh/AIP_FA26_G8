---
doc_id: KB-SW-001
version: 1
request_type: software
doc_type: howto
owner: it_mgr01
updated_at: 2026-10-03
sensitivity: internal
enabled: true
title: "Danh mục phần mềm duyệt sẵn và cách tự cài"
distractor: false
tags: [software, danh mục phần mềm, cài đặt, phần mềm duyệt sẵn]
---

## Danh mục phần mềm được duyệt sẵn

Hệ thống hiện có bảy phần mềm trong danh mục phần mềm được duyệt sẵn. Danh mục gồm 7-Zip, Adobe Acrobat Pro, AutoCAD, Microsoft Office, Microsoft Project, Visual Studio Code và Zoom Workplace.

Việc một phần mềm nằm trong danh mục có nghĩa là phần mềm đó đã có bản ghi hợp lệ trong catalog của hệ thống. Người dùng nên kiểm tra đúng tên phần mềm trước khi gửi yêu cầu cài đặt.

Phần mềm không có trong danh sách này được xem là phần mềm ngoài danh mục. Không nên tự coi một phần mềm ngoài danh mục là đã được duyệt chỉ vì phần mềm đó phổ biến hoặc đang được sử dụng ở nơi khác.

## Phần mềm không cần duyệt khi cài

Trong danh mục hiện tại, 7-Zip, Microsoft Office, Visual Studio Code và Zoom Workplace có requires_approval là false. Theo danh sách giá trị hợp lệ, các phần mềm này không cần bước duyệt khi cài.

Các phần mềm này cũng có license_type là free trong dữ liệu hiện tại.

Người dùng cần chọn đúng phần mềm trong danh mục. Ví dụ, Visual Studio Code có tên hiển thị là Visual Studio Code và tên trong catalog là vscode. Zoom Workplace có tên trong catalog là zoom.

Danh sách hiện tại không mô tả giao diện hoặc từng thao tác cài đặt cụ thể, vì vậy không nên tự ghi thêm đường dẫn tải hoặc các bước bấm nút chưa được xác nhận.

## Phần mềm cần duyệt khi cài

Adobe Acrobat Pro, AutoCAD và Microsoft Project đều nằm trong danh mục được duyệt sẵn nhưng có requires_approval là true. Vì vậy, các phần mềm này vẫn cần bước duyệt khi cài.

Ba phần mềm này có license_type là paid trong dữ liệu hiện tại. Người dùng không nên áp dụng quy trình của phần mềm không cần duyệt cho các phần mềm này.

Khi gửi yêu cầu, cần ghi đúng tên phần mềm cần sử dụng để hệ thống phân biệt giữa phần mềm không cần duyệt và phần mềm cần duyệt.

Không tự kết luận rằng mọi phần mềm có trong catalog đều được cài ngay mà không qua phê duyệt.

## Khi phần mềm không có trong danh mục

Nếu phần mềm người dùng cần không nằm trong bảy phần mềm của catalog hiện tại, phần mềm đó được xem là ngoài danh mục.

Không nên thay tên một phần mềm ngoài danh mục bằng tên của phần mềm khác có trong catalog để gửi yêu cầu. Cũng không nên tự ghi phần mềm mới vào danh mục.

Trường hợp phần mềm không có trong danh mục cần được xử lý theo quy trình dành cho yêu cầu phần mềm ngoài danh mục.

Danh sách giá trị hiện tại không cung cấp đường dẫn tải, phiên bản hay thao tác cài cụ thể cho từng phần mềm. Vì vậy các thông tin đó chỉ nên được bổ sung khi có nguồn hợp lệ khác xác nhận.