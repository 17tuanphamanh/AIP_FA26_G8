P11 — normalize (dùng chung với backend), augment, split, dedup_vs_m8. Xem docs/spec/build/01-kien-truc-project.md mục 3.
Kiểm trùng câu thẻ M8 với dữ liệu huấn luyện: `python -m training.common.dedup_vs_m8 --cau CAU.jsonl --train DATA [--train ...] (--embed-url URL | --no-embed) [--nguong 0.90] --out OUT.csv` (P11 mục 3.4 bước 2; P8 mục 4.3; mã thoát 0/3/2).
