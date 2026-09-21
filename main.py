"""Run the agent as a question-and-answer loop in the terminal.

    python main.py                      # chat mode, type 'thoat' to stop
    python main.py "câu hỏi của bạn"    # ask one question and exit
"""

import sys

from agent.core import Agent


def main() -> int:
    try:
        agent = Agent()
    except RuntimeError as err:
        print(err)
        return 1

    if len(sys.argv) > 1:
        print(agent.ask(" ".join(sys.argv[1:]), show_progress=True))
        return 0

    print("Agent AIP_FA26_G8. Gõ 'thoat' để kết thúc.\n")
    while True:
        try:
            question = input("Bạn: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if question.lower() in {"thoat", "exit", "quit"}:
            return 0
        if not question:
            continue
        print("Agent:", agent.ask(question, show_progress=True), "\n")


if __name__ == "__main__":
    raise SystemExit(main())
