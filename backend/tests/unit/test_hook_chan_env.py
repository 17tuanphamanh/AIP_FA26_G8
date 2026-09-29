""".claude/hooks/chan-env.py: chặn Read/Edit/Write/Grep/Glob đụng file .env* (trừ .env.example).

Chạy script thật bằng subprocess với JSON PreToolUse mẫu — hook không mở file nên đường dẫn
trong mẫu không cần tồn tại.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[3] / ".claude" / "hooks" / "chan-env.py"
THONG_BAO = "Chan: khong doc/sua file .env* (tru .env.example)"


def _chay(du_lieu: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HOOK)], input=du_lieu, capture_output=True, text=True, timeout=10, check=False
    )


@pytest.mark.parametrize(
    ("tool_name", "tool_input", "ma_thoat"),
    [
        pytest.param("Read", {"file_path": "/repo/.env"}, 2, id="env"),
        pytest.param("Read", {"file_path": "/repo/.env.local"}, 2, id="env-local"),
        pytest.param("Read", {"file_path": "/repo/.env.hooktest"}, 2, id="env-hooktest"),
        pytest.param("Edit", {"file_path": "sub/.ENV.production"}, 2, id="hoa-thuong-trong-thu-muc-con"),
        pytest.param("Read", {"file_path": "/repo/.env.example"}, 0, id="env-example-cho-qua"),
        pytest.param("Read", {"file_path": "/repo/README.md"}, 0, id="readme"),
        pytest.param("Grep", {"pattern": "HOOKTEST", "path": ".", "glob": "*.py"}, 0, id="grep-glob-py"),
        pytest.param("Grep", {"pattern": "HOOKTEST", "glob": ".env*"}, 2, id="grep-glob-env"),
        pytest.param("Glob", {"pattern": "**/.env*"}, 2, id="glob-pattern-env"),
        # `pattern` của Grep là regex tìm nội dung, không phải đường dẫn — tìm chữ ".env" trong code vẫn được.
        pytest.param("Grep", {"pattern": ".env", "path": "."}, 0, id="grep-regex-env-khong-phai-duong-dan"),
    ],
)
def test_chan_theo_basename(tool_name: str, tool_input: dict[str, str], ma_thoat: int) -> None:
    kq = _chay(json.dumps({"tool_name": tool_name, "tool_input": tool_input}))
    assert kq.returncode == ma_thoat
    assert kq.stdout == ""
    assert (THONG_BAO in kq.stderr) == (ma_thoat == 2)


def test_dau_vao_hong_thi_chan() -> None:
    """Hỏng ở đâu cũng chặn — cùng hướng với .claude/hooks/pre-commit-test.sh."""
    assert _chay("khong-phai-json").returncode == 2
    assert _chay("[]").returncode == 2
