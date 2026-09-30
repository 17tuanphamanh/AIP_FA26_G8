"""`make verify` (phase4 mục 4.4; 4a-8) — `scripts/verify.sh` chạy THẬT trên thư mục tạm với `make`, `docker compose`, `curl`,
`gh`, `uv` GIẢ (script shell trong PATH): thứ tự bước, biến shell cho từng cổng, bước 8 luôn trả về `.env` sau bước 3, dừng ở
bước đỏ đầu tiên, summary cho agent đọc. Không đụng stack, không đọc `.env` (thư mục tạm không có `.env`).
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "verify.sh"

MAKE_STUB = r"""#!/usr/bin/env bash
echo "make $*" >>"$STUB_LOG"
target="$1"
case "$target" in
  test) printf '3166 passed in 90.98s (0:01:30)\n94 passed in 5.17s\n77 passed, 5 deselected in 0.49s\n' ;;
  gate2|gate3) echo "==== 8 PASS, 0 FAIL ====" ;;
  ingest) echo "kb_version=abc" ;;
esac
case " ${STUB_FAIL:-} " in *" $target "*) echo "giả: $target đỏ" >&2; exit 1 ;; esac
exit 0
"""
COMPOSE_STUB = r"""#!/usr/bin/env bash
echo "compose $* | FAKE_SCENARIO=${FAKE_SCENARIO-<unset>} FAKE_NODE_DELAY=${FAKE_NODE_DELAY-<unset>}" >>"$STUB_LOG"
if [[ "$*" == *"printenv APP_ENV"* ]]; then echo "${STUB_APPENV:-dev}"; fi
exit 0
"""
UV_STUB = r"""#!/usr/bin/env bash
echo "uv $*" >>"$STUB_LOG"
printf '5 KB p50=1.0ms p95=2.0ms\n20 KB p50=2.0ms p95=3.0ms\n50 KB p50=4.0ms p95=6.0ms\n'
"""


def _stub(bin_dir: Path, name: str, body: str) -> Path:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _run(tmp_path: Path, *, g: str, bench: str = "0", fail: str = "", appenv: str = "dev") -> tuple[int, list[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    make = _stub(bin_dir, "make", MAKE_STUB)
    compose = _stub(bin_dir, "compose", COMPOSE_STUB)
    _stub(bin_dir, "uv", UV_STUB)
    _stub(bin_dir, "curl", "#!/usr/bin/env bash\nexit 0\n")
    _stub(bin_dir, "gh", "#!/usr/bin/env bash\nexit 1\n")
    work = tmp_path / "repo"
    work.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path), "G": g, "BENCH": bench,
        "MAKE_BIN": str(make), "COMPOSE": str(compose), "STUB_LOG": str(log), "STUB_FAIL": fail, "STUB_APPENV": appenv,
        "FAKE_SCENARIO": "tu-shell-cha", "FAKE_NODE_DELAY": "7",  # biến shell cha — bước 8 phải gỡ
    }  # fmt: skip
    out = subprocess.run(["bash", str(SCRIPT)], cwd=work, env=env, capture_output=True, text=True, timeout=60, check=False)
    summary = (work / ".verify" / "summary.txt").read_text(encoding="utf-8")
    return out.returncode, log.read_text(encoding="utf-8").splitlines(), summary


def _ups(calls: list[str]) -> list[str]:
    return [c.split(" | ", 1)[1] for c in calls if c.startswith("compose up")]


def test_4a8_bash_syntax_and_shellcheck_if_available() -> None:
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, check=False).returncode == 0
    if shutil.which("shellcheck"):
        out = subprocess.run(["shellcheck", str(SCRIPT)], capture_output=True, text=True, check=False)
        assert out.returncode == 0, out.stdout


def test_g0_only_lint_and_test_no_stack(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="0")
    assert rc == 0
    assert calls == ["make lint", "make test"]  # không compose, không up
    assert "KẾT LUẬN: XANH" in summary
    assert "| 2 | test | PASS |" in summary
    assert "backend 3166 passed · mock 94 passed · ml 77 passed, 5 deselected" in summary
    assert "| 8 |" not in summary and "| 9 | CI (gh) | BỎ QUA |" in summary


def test_g23_order_env_per_gate_and_restore(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="23")
    assert rc == 0
    makes = [c for c in calls if c.startswith("make ")]
    assert makes == ["make lint", "make test", "make up", "make gate2 S=all",
                     "make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated", "make gate3 S=all"]  # fmt: skip
    assert _ups(calls) == [
        "FAKE_SCENARIO=approval FAKE_NODE_DELAY=40",  # gate2: đặt
        "FAKE_SCENARIO= FAKE_NODE_DELAY=",  # gate3: rỗng = không đặt (Settings env_ignore_empty)
        "FAKE_SCENARIO=<unset> FAKE_NODE_DELAY=<unset>",  # bước 8: gỡ cả biến của shell cha → đúng .env
    ]
    ups = [c for c in calls if c.startswith("compose up")]
    assert len(ups) == 3 and all("up -d --force-recreate --no-deps --wait --wait-timeout 180 backend worker |" in c
                                 for c in ups)  # fmt: skip
    assert not [c for c in calls if " down" in c or "volume" in c or " -v" in c]  # không xoá volume
    for row in ("| 3 | up | PASS |", "| 6 | gate2 | PASS |", "| 4 | ingest | PASS |", "| 5 | gate3 | PASS |",
                "| 8 | trả về .env | PASS |", "8 PASS, 0 FAIL"):  # fmt: skip
        assert row in summary
    assert "KẾT LUẬN: XANH" in summary


def test_red_gate_still_restores_env_and_reports_step(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="32", fail="gate3")
    assert rc != 0
    assert "make gate2 S=all" not in calls  # dừng ở bước đỏ đầu tiên
    assert _ups(calls)[-1] == "FAKE_SCENARIO=<unset> FAKE_NODE_DELAY=<unset>"  # bước 8 vẫn chạy
    assert "KẾT LUẬN: ĐỎ ở bước 5 (gate3)" in summary and "---- 30 dòng cuối của bước 5 ----" in summary
    assert "giả: gate3 đỏ" in summary and "| 8 | trả về .env | PASS |" in summary


@pytest.mark.parametrize(("fail", "step"), [("lint", 1), ("test", 2)])
def test_red_before_up_touches_no_stack(tmp_path: Path, fail: str, step: int) -> None:
    rc, calls, summary = _run(tmp_path, g="23", fail=fail)
    assert rc != 0 and not [c for c in calls if c.startswith("compose")]
    assert f"KẾT LUẬN: ĐỎ ở bước {step} ({fail})" in summary and "| 8 |" not in summary


def test_red_up_or_wrong_app_env_runs_no_gate_no_restore(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="3", fail="up")
    assert rc != 0 and _ups(calls) == [] and "KẾT LUẬN: ĐỎ ở bước 3 (up)" in summary
    rc, calls, summary = _run(tmp_path, g="3", appenv="prod")
    assert rc != 0 and "make gate3 S=all" not in calls and _ups(calls) == []
    assert "KẾT LUẬN: ĐỎ ở bước 3 (up)" in summary and "APP_ENV của backend không phải dev" in summary


def test_bench_step_optional(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="0", bench="1")
    assert rc == 0 and "uv run python -m tests.stack.bench_checkpoint" in calls
    assert "| 7 | bench | PASS |" in summary and "50 KB p50=4.0ms p95=6.0ms" in summary


@pytest.mark.parametrize("g", ["2a", "5", "1"])  # G rỗng = mặc định 3 (không phải lỗi)
def test_bad_g_rejected_before_anything(tmp_path: Path, g: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    out = subprocess.run(["bash", str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
                         env={"PATH": os.environ["PATH"], "G": g, "MAKE_BIN": "false", "COMPOSE": "false"})  # fmt: skip
    assert out.returncode == 2 and not (tmp_path / ".verify").exists()
