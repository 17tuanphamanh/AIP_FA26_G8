"""Vỏ `sample_reasons` trên máy (phase6 7.1 P5, chặng 6D) — lõi ở `backend/app/audit/m5_review.py` (có trong image).

  PYTHONPATH=backend uv run python scripts/sample_reasons.py --since <ISO> --n 10 --seed <số> [--min-llm 3] [--templates] [--key-out <file>]
  python -m app.audit.m5_review sample …   # TRONG container backend (image không có scripts/)

stdout = CHỈ danh sách câu `reason` (đưa người đọc); `--key-out` = file đối chiếu riêng. Tham số, mã thoát: docstring `app.audit.m5_review`.
Chỉ đọc; không in DSN.
"""

import sys

from app.audit.m5_review import sample_main

if __name__ == "__main__":
    sys.exit(sample_main())
