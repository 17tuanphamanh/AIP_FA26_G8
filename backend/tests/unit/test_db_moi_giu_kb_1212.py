"""O1 (V16, 12/11): `scripts/ops/db_moi_giu_kb.sh` — DB mới (xoá ca cũ) mà GIỮ KB Qdrant, ingest chỉ ghi bù DB.

- Mặc định chỉ IN lệnh; `--chay` mới chạy (ở đây `docker` là bản giả ghi lại lời gọi).
- Chỉ đụng postgres + backend + worker: không `down`, không dựng lại ml-service (bẫy MODELS_DIR), không `make up`.
- Xoá đúng MỘT volume `servicedesk_pgdata`, và chỉ sau khi nhãn compose của nó đúng `servicedesk/pgdata`; nhãn sai → dừng, không xoá.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "ops" / "db_moi_giu_kb.sh"

FAKE_DOCKER = """#!/usr/bin/env bash
echo "$*" >> "$CALLS"
if [ "$1" = volume ] && [ "$2" = inspect ]; then echo "$LABELS"; fi
exit 0
"""


def _run(args: list[str], tmp_path: Path, labels: str = "servicedesk/pgdata") -> tuple[subprocess.CompletedProcess[str], list[str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    docker = bin_dir / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    calls = tmp_path / "calls.txt"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "CALLS": str(calls), "LABELS": labels}
    r = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, cwd=tmp_path, check=False)
    return r, (calls.read_text().splitlines() if calls.exists() else [])


def _docker_lines(text: str) -> list[str]:
    return [line.split("docker ", 1)[1] for line in text.splitlines() if line.lstrip("+ ").startswith("docker ")]


ORDER = [
    "compose -p servicedesk stop backend worker",
    "compose -p servicedesk rm -f -s postgres",
    "volume inspect",
    "volume rm servicedesk_pgdata",
    "compose -p servicedesk up -d --wait --no-deps postgres",
    "compose -p servicedesk run --rm --no-deps backend alembic upgrade head",
    "compose -p servicedesk up -d --wait --no-deps backend worker",
    "compose -p servicedesk run --rm --no-deps -v",
    "compose -p servicedesk exec -T mock python -m app.seed reset",
]


def _assert_order(lines: list[str]) -> None:
    pos = 0
    for want in ORDER:
        idx = next((i for i in range(pos, len(lines)) if lines[i].startswith(want)), None)
        assert idx is not None, f"thiếu hoặc sai thứ tự: {want}\n" + "\n".join(lines)
        pos = idx + 1


def test_mac_dinh_chi_in_lenh(tmp_path: Path) -> None:
    r, calls = _run([], tmp_path)
    assert r.returncode == 0, r.stderr
    assert calls == []  # không gọi docker nào
    lines = _docker_lines(r.stdout)
    _assert_order(lines)
    assert "--chay" in r.stdout


def test_chi_xoa_mot_volume_pgdata_giu_qdrant(tmp_path: Path) -> None:
    r, _ = _run([], tmp_path)
    lines = _docker_lines(r.stdout)
    removes = [line for line in lines if line.startswith("volume rm")]
    assert removes == ["volume rm servicedesk_pgdata"]
    joined = "\n".join(lines)
    assert "down" not in joined and " -v\n" not in joined
    for svc in ("ml-service", "qdrant"):  # không dựng lại / dừng / xoá
        assert not any(svc in line and ("up" in line or "rm" in line or "stop" in line) for line in lines), svc
    assert "make up" not in r.stdout
    assert all(line.startswith(("compose -p servicedesk ", "volume ")) for line in lines)


def test_ingest_mount_kb_chi_doc(tmp_path: Path) -> None:
    r, _ = _run([], tmp_path)
    [ingest] = [line for line in _docker_lines(r.stdout) if "app.rag.ingest.cli" in line]
    assert f"{ROOT}/kb:/srv/kb:ro" in ingest and "--kb-dir /srv/kb" in ingest


def test_chay_goi_dung_thu_tu(tmp_path: Path) -> None:
    r, calls = _run(["--chay"], tmp_path)
    assert r.returncode == 0, r.stderr
    _assert_order(calls)
    assert "--user-id it_mgr01" in r.stdout  # bước tay tiếp theo: OTP quan.tm trên DB mới


@pytest.mark.parametrize("labels", ["khac/pgdata", "servicedesk/qdrant", ""])
def test_nhan_volume_sai_thi_dung_khong_xoa(tmp_path: Path, labels: str) -> None:
    r, calls = _run(["--chay"], tmp_path, labels=labels)
    assert r.returncode != 0
    assert not any(c.startswith("volume rm") for c in calls)
    assert not any(c.startswith("compose -p servicedesk up") for c in calls)
    assert "servicedesk_pgdata" in r.stderr


def test_tham_so_la_bi_tu_choi(tmp_path: Path) -> None:
    r, calls = _run(["--xoa-het"], tmp_path)
    assert r.returncode == 2 and calls == []


def test_makefile_co_target() -> None:
    text = (ROOT / "Makefile").read_text()
    assert "db-moi-giu-kb:" in text and "scripts/ops/db_moi_giu_kb.sh" in text
