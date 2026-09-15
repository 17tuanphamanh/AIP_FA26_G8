"""Chay agent o che do hoi dap trong terminal.

    python main.py                      # che do chat, go 'thoat' de dung
    python main.py "cau hoi cua ban"    # hoi mot cau roi thoat
"""

import sys

from agent.core import Agent


def main() -> int:
    try:
        agent = Agent()
    except RuntimeError as loi:
        print(loi)
        return 1

    if len(sys.argv) > 1:
        print(agent.hoi(" ".join(sys.argv[1:]), in_tien_trinh=True))
        return 0

    print("Agent AIP_FA26_G8. Go 'thoat' de ket thuc.\n")
    while True:
        try:
            cau_hoi = input("Ban: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if cau_hoi.lower() in {"thoat", "exit", "quit"}:
            return 0
        if not cau_hoi:
            continue
        print("Agent:", agent.hoi(cau_hoi, in_tien_trinh=True), "\n")


if __name__ == "__main__":
    raise SystemExit(main())
