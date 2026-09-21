# Kiến trúc hệ thống

## Luồng chạy

```
người dùng
    │  câu hỏi
    ▼
main.py ──► Agent.ask()  (agent/core.py)
                │
                ▼
        tool_runner của SDK
                │  model quyết định gọi tool nào
                ▼
        agent/tools.py ──► kết quả trả ngược lại model
                │
                ▼  lặp đến khi model không gọi tool nữa
            câu trả lời
```

## Vì sao chọn cách này

- **Tool runner thay vì tự viết vòng lặp:** SDK lo phần gọi API → chạy tool → nạp kết quả → gọi tiếp. Ít code hơn, ít lỗi hơn.
- **Tool tách làm 2 lớp** (hàm thuần + bản bọc `@beta_tool`): test được logic mà không cần gọi API, đỡ tốn tiền và chạy nhanh.
- **Chặn đường dẫn ra ngoài repo** trong `_safe_path`: không cho model đọc bừa file trong máy.

## Những thứ còn thiếu / dự định làm thêm

- [ ] Ghi log mỗi lượt gọi tool ra `logs/`
- [ ] Thêm tool tìm kiếm nội dung trong repo
- [ ] Đo chi phí token mỗi lượt hỏi
