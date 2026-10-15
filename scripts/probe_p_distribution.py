"""Vỏ `probe_p_distribution` trên máy (phase6 7.1 P7, chặng 6D) — lõi ở `backend/app/audit/m5_review.py` (có trong image).

  PYTHONPATH=backend uv run python scripts/probe_p_distribution.py --since <ISO> [--csv <file>]
  python -m app.audit.m5_review probe …   # TRONG container backend (image không có scripts/)

`LLM_BACKEND` khác `real` → dòng cảnh báo đầu + mã thoát 3. Tham số, mã thoát: docstring `app.audit.m5_review`. Chỉ đọc; không in DSN.
"""

import sys

from app.audit.m5_review import probe_main

if __name__ == "__main__":
    sys.exit(probe_main())
