"""O6 (soát 12/11, agent 01): `.githooks/commit-msg` chặn thêm chữ "subagent" (không phân biệt hoa thường) — 4 commit cũ trên `main`
mang chữ này lọt qua hook. Chạy đúng script hook trên tệp lời commit mẫu (không cần repo git)."""

import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[3] / ".githooks" / "commit-msg"


def _run(tmp_path: Path, msg: str) -> int:
    f = tmp_path / "MSG"
    f.write_text(msg, encoding="utf-8")
    return subprocess.run(["bash", str(HOOK), str(f)], capture_output=True, check=False).returncode


@pytest.mark.parametrize(
    "msg",
    ["Gop ket qua subagent", "Subagent soat bao mat", "theo SUBAGENT test-writer", "kb: sua\n\nviet boi sub-agent khong", "Co-Authored-By: Claude"],
)  # fmt: skip
def test_chan_dau_vet(tmp_path: Path, msg: str) -> None:
    if "sub-agent" in msg:
        assert _run(tmp_path, msg) == 0  # "sub-agent" có gạch nối không nằm trong mẫu — chỉ chặn đúng chữ "subagent"
    else:
        assert _run(tmp_path, msg) == 1


@pytest.mark.parametrize("msg", ["approvals: 409 khi ticket cha da ket thuc", "docs: agent soat 20 muc", "# subagent trong dong comment git\nkb: sua"])
def test_loi_binh_thuong_khong_chan(tmp_path: Path, msg: str) -> None:
    assert _run(tmp_path, msg) == 0
