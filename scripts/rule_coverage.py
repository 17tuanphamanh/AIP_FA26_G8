"""Đếm "ca không luật nào khớp → lớp LLM" trên kịch bản (phase5 mục 4.6, P9, Q-5-5) — chỉ đọc, không mạng, không stack.

  uv run python scripts/rule_coverage.py eval/scenarios [--seed mock_services/seed.json] [--csv out.csv]

STUB T22a DỪNG 1: giao diện `main(argv) -> int` đã chốt (PLAN-T22a TQ-9); thân hàm làm ở DỪNG 2 (S14).
"""

import sys


def main(argv: list[str] | None = None) -> int:
    raise NotImplementedError("T22a P9 — DỪNG 2")


if __name__ == "__main__":
    sys.exit(main())
