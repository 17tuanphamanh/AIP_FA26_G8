# Knowledge Base (KB)

Tài liệu KB (Markdown có front matter) — **được commit**. Hướng dẫn soạn, quy tắc front matter, số liệu, bộ câu kiểm
tra: `docs/spec/build/kb-mau/huong-dan-soan-kb.md` (kèm file mẫu cùng thư mục). Thiết kế ingest:
`docs/spec/build/phase3-thiet-ke-chi-tiet.md` mục 5.

```
kb/
├── README.md                    # file này (bỏ qua khi nạp)
├── kb-facts.md                  # số liệu chuẩn — một khối ```yaml; mọi con số trong tài liệu phải khớp
├── <request_type>/<doc_id>.md   # vpn | account | software | access | general; tên file = doc_id
└── eval/retrieval_set.yaml      # bộ câu kiểm tra truy hồi (cổng kiểm khi nạp)
```

Kiểm trước khi nộp (cần `make up`; không ghi gì):

```
make ingest ARGS=--dry-run
```

Nạp thật: `make ingest`. Sửa bất kỳ chữ nào trong một tài liệu → tăng `version`, không thì máy từ chối nạp. Tài liệu
thật do TV1 thêm; test dùng KB tổng hợp ở `backend/tests/fixtures/kb/`, không dùng thư mục này.
