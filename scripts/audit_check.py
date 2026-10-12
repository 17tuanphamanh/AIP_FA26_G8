"""Vỏ `audit_check` trên máy (phase4 7.1 P5; PLAN-4d TQ-5) — lõi ở `backend/app/audit/check.py` (có trong image).

  make audit-check ARGS="<ticket_id> …"                       # chạy TRONG container backend (DSN của compose) — cách thường dùng
  PYTHONPATH=backend uv run python scripts/audit_check.py …   # trên máy: DSN theo Settings (MONITOR_DATABASE_URL | DATABASE_URL)

Tham số, mã thoát, luật in: xem docstring `app.audit.check`. Chỉ đọc; không in DSN, không in giá trị bí mật.
"""

import sys

from app.audit.check import main

if __name__ == "__main__":
    sys.exit(main())
