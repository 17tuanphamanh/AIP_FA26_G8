"""`make verify` (phase4 mục 4.4; 4a-8) — `scripts/verify.sh` chạy THẬT trên thư mục tạm với `make`, `docker compose`, `curl`,
`gh`, `uv` GIẢ (script shell trong PATH): thứ tự bước, biến shell cho từng cổng, bước 8 luôn trả về `.env` sau bước 3, dừng ở
bước đỏ đầu tiên, summary cho agent đọc. Không đụng stack, không đọc `.env` (thư mục tạm không có `.env`).
"""

import os
import re
import shutil
import stat
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "verify.sh"

MAKE_STUB = r"""#!/usr/bin/env bash
echo "make $*" >>"$STUB_LOG"
target="$1"
case "$target" in
  test) printf '3166 passed in 90.98s (0:01:30)\n94 passed in 5.17s\n77 passed, 5 deselected in 0.49s\n' ;;
  gate2|gate3|gate4|gate5) echo "==== 8 PASS, 0 FAIL ====" ;;
  ingest) echo "kb_version=abc" ;;
esac
case " ${STUB_FAIL:-} " in *" $target "*) echo "giả: $target đỏ" >&2; exit 1 ;; esac
exit 0
"""
COMPOSE_STUB = r"""#!/usr/bin/env bash
echo "compose $* | FAKE_SCENARIO=${FAKE_SCENARIO-<unset>} FAKE_NODE_DELAY=${FAKE_NODE_DELAY-<unset>} SLA=${APPROVAL_SLA_MINUTES_DEV-<unset>}" >>"$STUB_LOG"
if [[ "$*" == *"printenv APP_ENV"* ]]; then echo "${STUB_APPENV:-dev}"; fi
if [[ "${1:-}" == logs ]]; then
  case " ${STUB_FAIL:-} " in *" compose-logs "*) echo "giả: compose logs lỗi" >&2; exit 1 ;; esac
  echo "backend-1  | log giả của container"
fi
exit 0
"""
# V16: gh GIẢ — ghi tham số (+ biểu thức --jq ra file riêng), trả STUB_GH_OUT (dạng đã qua --jq) với mã STUB_GH_RC (mặc định 1 = lỗi).
GH_STUB = r"""#!/usr/bin/env bash
echo "gh $*" >>"$STUB_LOG"
prev=""
for a in "$@"; do
  if [[ "$prev" == "--jq" ]]; then printf '%s' "$a" >"$STUB_LOG.jq"; fi
  prev="$a"
done
if [[ -n "${STUB_GH_OUT:-}" ]]; then printf '%s\n' "$STUB_GH_OUT"; fi
exit "${STUB_GH_RC:-1}"
"""
UV_STUB = r"""#!/usr/bin/env bash
echo "uv $*" >>"$STUB_LOG"
printf '5 KB p50=1.0ms p95=2.0ms\n20 KB p50=2.0ms p95=3.0ms\n50 KB p50=4.0ms p95=6.0ms\n'
"""
# Q-4d-4: hệ điều hành / caffeinate / nguồn điện GIẢ — không để máy chạy test (macOS) gọi caffeinate, pmset thật.
UNAME_STUB = '#!/usr/bin/env bash\necho "${STUB_UNAME:-Linux}"\n'
CAFFEINATE_STUB = '#!/usr/bin/env bash\necho "caffeinate $*" >>"$STUB_LOG"\n'
PMSET_STUB = r"""#!/usr/bin/env bash
printf "Now drawing from '%s'\n -InternalBattery-0 (id=1)\t80%%; discharging\n" "${STUB_POWER:-AC Power}"
"""


def _stub(bin_dir: Path, name: str, body: str) -> Path:
    path = bin_dir / name
    path.write_text(body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _git(work: Path, home: Path, *args: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"}
    out = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
                          *args], cwd=work, env=env, capture_output=True, text=True, check=True)  # fmt: skip
    return out.stdout.strip()


def _run(
    tmp_path: Path, *, g: str, bench: str = "0", fail: str = "", appenv: str = "dev", uname: str = "Linux",
    power: str = "AC Power", git: bool = False, dirty: int = 0, gh_rc: int = 1, gh_out: str = "",
) -> tuple[int, list[str], str]:  # fmt: skip
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    make = _stub(bin_dir, "make", MAKE_STUB)
    compose = _stub(bin_dir, "compose", COMPOSE_STUB)
    _stub(bin_dir, "uv", UV_STUB)
    _stub(bin_dir, "curl", "#!/usr/bin/env bash\nexit 0\n")
    _stub(bin_dir, "gh", GH_STUB)
    _stub(bin_dir, "uname", UNAME_STUB)
    _stub(bin_dir, "pmset", PMSET_STUB)
    _stub(bin_dir, "caffeinate", CAFFEINATE_STUB)
    work = tmp_path / "repo"
    work.mkdir(exist_ok=True)
    if git:  # V16 bước 9: repo thật có 1 commit (`.verify/` bị bỏ qua như repo thật) + `dirty` file chưa commit
        _git(work, tmp_path, "init", "-q", "-b", "dev-test")
        (work / ".gitignore").write_text(".verify/\n", encoding="utf-8")
        _git(work, tmp_path, "add", ".gitignore")
        _git(work, tmp_path, "commit", "-q", "-m", "init")
        for i in range(dirty):
            (work / f"chua-commit-{i}.txt").write_text("x", encoding="utf-8")
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path), "G": g, "BENCH": bench,
        "MAKE_BIN": str(make), "COMPOSE": str(compose), "STUB_LOG": str(log), "STUB_FAIL": fail, "STUB_APPENV": appenv,
        "STUB_UNAME": uname, "STUB_POWER": power, "STUB_GH_RC": str(gh_rc), "STUB_GH_OUT": gh_out,
        "GIT_CEILING_DIRECTORIES": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1",  # không lần lên repo nào ngoài thư mục tạm
        "FAKE_SCENARIO": "tu-shell-cha", "FAKE_NODE_DELAY": "7", "APPROVAL_SLA_MINUTES_DEV": "9",  # biến shell cha — bước 8 phải gỡ
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
    assert _ups(calls) == [  # 4d DỪNG 2: thêm APPROVAL_SLA_MINUTES_DEV — gate2/gate3 rỗng (= 30 phút mặc định), bước 8 gỡ
        "FAKE_SCENARIO=approval FAKE_NODE_DELAY=40 SLA=",  # gate2: đặt
        "FAKE_SCENARIO= FAKE_NODE_DELAY= SLA=",  # gate3: rỗng = không đặt (Settings env_ignore_empty)
        "FAKE_SCENARIO=<unset> FAKE_NODE_DELAY=<unset> SLA=<unset>",  # bước 8: gỡ cả biến của shell cha → đúng .env
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
    assert _ups(calls)[-1] == "FAKE_SCENARIO=<unset> FAKE_NODE_DELAY=<unset> SLA=<unset>"  # bước 8 vẫn chạy
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


@pytest.mark.parametrize("g", ["2a", "6", "1", "46"])  # G rỗng = mặc định 3 (không phải lỗi). T24: 5 = gate5 → hợp lệ
def test_bad_g_rejected_before_anything(tmp_path: Path, g: str) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    out = subprocess.run(["bash", str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
                         env={"PATH": os.environ["PATH"], "G": g, "MAKE_BIN": "false", "COMPOSE": "false"})  # fmt: skip
    assert out.returncode == 2 and not (tmp_path / ".verify").exists()


# ---- Q-4d-4: macOS giữ máy thức + cảnh báo chạy pin ----------------------------------------------------------------------------


def _caffeinate_lines(tmp_path: Path) -> list[str]:
    """`caffeinate` chạy NỀN — đợi tối đa 3 s cho stub ghi xong (script chính có thể thoát trước)."""
    log = tmp_path / "calls.log"
    for _ in range(30):
        found = [c for c in log.read_text(encoding="utf-8").splitlines() if c.startswith("caffeinate")]
        if found:
            return found
        time.sleep(0.1)
    return []


def test_q4d4_darwin_caffeinate_bound_to_script_pid_ac_power_no_warning(tmp_path: Path) -> None:
    rc, _, summary = _run(tmp_path, g="0", uname="Darwin")
    assert rc == 0
    [line] = _caffeinate_lines(tmp_path)
    assert re.fullmatch(r"caffeinate -i -w \d+", line), line  # -w <pid của verify.sh>: hết khi script thoát, không giữ máy
    assert "| 0 | chuẩn bị | PASS |" in summary and "caffeinate bật" in summary and "CẢNH BÁO" not in summary


def test_q4d4_battery_power_warns_in_summary(tmp_path: Path) -> None:
    rc, _, summary = _run(tmp_path, g="0", uname="Darwin", power="Battery Power")
    assert rc == 0 and "CẢNH BÁO chạy pin" in summary
    log = next((tmp_path / "repo" / ".verify").glob("run-*.log")).read_text(encoding="utf-8")
    assert "CẢNH BÁO: máy đang chạy PIN" in log


def test_q4d4_not_macos_no_caffeinate_no_power_note(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="0", uname="Linux", power="Battery Power")
    assert rc == 0 and not [c for c in calls if c.startswith("caffeinate")]
    assert "caffeinate" not in summary and "CẢNH BÁO" not in summary


# ---- 4d DỪNG 2: cổng 4 (P6, PLAN-4d TQ-12) ------------------------------------------------------------------------------------


def test_g234_gate4_sla_2_only_for_gate4_ingest_once_restore(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="234")
    assert rc == 0
    makes = [c for c in calls if c.startswith("make ")]
    assert makes == ["make lint", "make test", "make up", "make gate2 S=all",
                     "make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated", "make gate3 S=all",
                     "make gate4 S=all"]  # fmt: skip  # ingest MỘT lần trước cổng đầu cần KB (3)
    assert _ups(calls) == [
        "FAKE_SCENARIO=approval FAKE_NODE_DELAY=40 SLA=",
        "FAKE_SCENARIO= FAKE_NODE_DELAY= SLA=",
        "FAKE_SCENARIO= FAKE_NODE_DELAY= SLA=2",  # gate4: CHỈ bước này hạn duyệt 2 phút
        "FAKE_SCENARIO=<unset> FAKE_NODE_DELAY=<unset> SLA=<unset>",  # bước 8: trả về .env
    ]
    for row in ("| 4 | ingest | PASS |", "| 5 | gate3 | PASS |", "| 10 | gate4 | PASS |", "| 8 | trả về .env | PASS |"):
        assert row in summary
    assert summary.count("| 4 | ingest |") == 1 and "KẾT LUẬN: XANH" in summary


def test_g4_alone_ingests_first(tmp_path: Path) -> None:
    rc, calls, _ = _run(tmp_path, g="4")
    makes = [c for c in calls if c.startswith("make ")]
    assert rc == 0 and makes[-2:] == ["make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated", "make gate4 S=all"]


def test_red_gate4_reports_step_10_and_restores(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="34", fail="gate4")
    assert rc != 0 and "KẾT LUẬN: ĐỎ ở bước 10 (gate4)" in summary
    assert _ups(calls)[-1] == "FAKE_SCENARIO=<unset> FAKE_NODE_DELAY=<unset> SLA=<unset>"
    assert "| 8 | trả về .env | PASS |" in summary


# ---- Phase 5 T24 (P8, Q-T24-1): gate5 trên KB THẬT --------------------------------------------------------------------------------

FIXTURE_INGEST = "make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated"
REAL_INGEST = "make ingest KB_DIR=kb"
RESTORED = "FAKE_SCENARIO=<unset> FAKE_NODE_DELAY=<unset> SLA=<unset>"


def test_t24_g2345_real_kb_ingested_right_before_gate5_and_restore(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="2345")
    assert rc == 0
    makes = [c for c in calls if c.startswith("make ")]
    assert makes == ["make lint", "make test", "make up", "make gate2 S=all", FIXTURE_INGEST, "make gate3 S=all",
                     "make gate4 S=all", REAL_INGEST, "make gate5 S=all"]  # fmt: skip
    assert _ups(calls) == [
        "FAKE_SCENARIO=approval FAKE_NODE_DELAY=40 SLA=",
        "FAKE_SCENARIO= FAKE_NODE_DELAY= SLA=",
        "FAKE_SCENARIO= FAKE_NODE_DELAY= SLA=2",
        "FAKE_SCENARIO= FAKE_NODE_DELAY= SLA=",  # gate5: node thật, hạn duyệt mặc định
        RESTORED,
    ]
    for row in ("| 4 | ingest | PASS |", "| 11 | ingest KB thật | PASS |", "| 12 | gate5 | PASS |", "| 8 | trả về .env | PASS |"):
        assert row in summary
    assert "KẾT LUẬN: XANH" in summary


def test_t24_g5_alone_ingests_only_real_kb(tmp_path: Path) -> None:
    rc, calls, _ = _run(tmp_path, g="5")
    makes = [c for c in calls if c.startswith("make ")]
    assert rc == 0 and FIXTURE_INGEST not in makes and makes[-2:] == [REAL_INGEST, "make gate5 S=all"]


def test_t24_g53_reingests_fixture_after_real_kb(tmp_path: Path) -> None:
    """Cổng cần KB khác KB đang nạp → nạp lại (gate3 sau gate5 cần KB fixture)."""
    rc, calls, _ = _run(tmp_path, g="53")
    makes = [c for c in calls if c.startswith("make ")]
    assert rc == 0 and makes[3:] == [REAL_INGEST, "make gate5 S=all", FIXTURE_INGEST, "make gate3 S=all"]


def test_t24_g234_without_5_never_ingests_real_kb(tmp_path: Path) -> None:
    """G không có 5 → hành vi verify.sh giữ nguyên (không nạp KB thật)."""
    _, calls, _ = _run(tmp_path, g="234")
    assert REAL_INGEST not in calls


def test_t24_red_gate5_reports_step_12_and_restores(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="5", fail="gate5")
    assert rc != 0 and "KẾT LUẬN: ĐỎ ở bước 12 (gate5)" in summary
    assert _ups(calls)[-1] == RESTORED and "| 8 | trả về .env | PASS |" in summary


# ---- Chặng V16: gate đỏ → lưu log backend/worker TRƯỚC bước 8; bước 9 CI theo đúng commit HEAD -----------------------------------

SINCE_RE = r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ"  # UTC ISO — giờ bắt đầu bước


@pytest.mark.parametrize(("g", "fail", "step"), [("2", "gate2", 6), ("3", "gate3", 5), ("4", "gate4", 10), ("5", "gate5", 12)])
def test_v16_red_gate_saves_container_logs_before_restore(tmp_path: Path, g: str, fail: str, step: int) -> None:
    rc, calls, summary = _run(tmp_path, g=g, fail=fail)
    assert rc != 0 and f"KẾT LUẬN: ĐỎ ở bước {step} ({fail})" in summary
    [i] = [n for n, c in enumerate(calls) if c.startswith("compose logs")]
    assert re.fullmatch(rf"compose logs --no-color --timestamps --since {SINCE_RE} backend worker", calls[i].split(" | ")[0])
    restore = max(n for n, c in enumerate(calls) if c.startswith("compose up"))
    assert calls[restore].endswith(RESTORED) and i < restore  # log lấy TRƯỚC khi bước 8 tạo lại backend+worker
    [saved] = list((tmp_path / "repo" / ".verify").glob(f"run-*-step{step}-logs.txt"))
    assert "log giả của container" in saved.read_text(encoding="utf-8")
    assert f"log backend/worker của bước {step}: .verify/{saved.name}" in summary.splitlines()


def test_v16_green_gates_never_call_compose_logs(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="2345")
    assert rc == 0 and "KẾT LUẬN: XANH" in summary
    assert not [c for c in calls if c.startswith("compose logs")]
    assert not list((tmp_path / "repo" / ".verify").glob("run-*-step*-logs.txt")) and "log backend/worker" not in summary


def test_v16_compose_logs_error_does_not_stop_verify(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="4", fail="gate4 compose-logs")
    assert rc != 0 and "KẾT LUẬN: ĐỎ ở bước 10 (gate4)" in summary  # vẫn là bước 10, không phải lỗi mới
    assert _ups(calls)[-1] == RESTORED and "| 8 | trả về .env | PASS |" in summary


def _gh_calls(calls: list[str]) -> list[str]:
    return [c for c in calls if c.startswith("gh ")]


@pytest.mark.parametrize(
    ("gh_rc", "gh_out", "result", "note"),
    [
        (1, "", "BỎ QUA", "bỏ qua (gh)"),
        (0, "", "BỎ QUA", "chưa có CI cho HEAD {sha7}"),
        (0, "completed|success|38670134404", "PASS", "success 38670134404 ({sha7})"),
        (0, "completed|failure|222", "FAIL", "failure 222"),
        (0, "completed|cancelled|223", "FAIL", "cancelled 223"),
        (0, "completed||224", "FAIL", "chưa có kết luận 224"),
        (0, "in_progress||333", "ĐANG CHẠY", "in_progress 333"),  # gh trả conclusion ""
        (0, "queued|null|444", "ĐANG CHẠY", "queued 444"),  # jq "\(.conclusion)" của null = "null"
    ],
    ids=["gh-loi", "chua-co-run", "success", "failure", "cancelled", "completed-khong-ket-luan", "dang-chay", "cho-null"],
)
def test_v16_ci_step_filters_by_head_commit(tmp_path: Path, gh_rc: int, gh_out: str, result: str, note: str) -> None:
    rc, calls, summary = _run(tmp_path, g="0", git=True, gh_rc=gh_rc, gh_out=gh_out)
    sha = _git(tmp_path / "repo", tmp_path, "rev-parse", "HEAD")
    assert rc == 0 and "KẾT LUẬN: XANH" in summary  # bước 9 không đổi KẾT LUẬN (kể cả FAIL)
    [gh] = _gh_calls(calls)
    assert gh.startswith(f"gh run list --branch dev-test --commit {sha} -L 1 --json status,conclusion,databaseId --jq "), gh
    assert f"| 9 | CI (gh) | {result} | 0s | {note.format(sha7=sha[:7])} |" in summary.splitlines()
    if result != "PASS":
        assert "| 9 | CI (gh) | PASS |" not in summary


def test_v16_ci_step_dirty_tree_note(tmp_path: Path) -> None:
    rc, _, summary = _run(tmp_path, g="0", git=True, dirty=2, gh_rc=0, gh_out="completed|success|111")
    sha7 = _git(tmp_path / "repo", tmp_path, "rev-parse", "--short=7", "HEAD")
    assert rc == 0 and "dirty=2" in summary
    assert f"| 9 | CI (gh) | PASS | 0s | success 111 ({sha7}); CI của HEAD; cây có 2 thay đổi chưa commit |" in summary


def test_v16_ci_step_without_git_skips_and_never_calls_gh(tmp_path: Path) -> None:
    rc, calls, summary = _run(tmp_path, g="0", gh_rc=0, gh_out="completed|success|111")
    assert rc == 0 and _gh_calls(calls) == []
    assert "| 9 | CI (gh) | BỎ QUA | 0s | bỏ qua (không có git) |" in summary.splitlines()


@pytest.mark.skipif(shutil.which("jq") is None, reason="cần jq để chạy biểu thức --jq thật")
def test_v16_ci_jq_expression_shapes(tmp_path: Path) -> None:
    """Biểu thức `--jq` mà verify.sh truyền cho gh, chạy bằng jq thật: ra đúng dạng mà các ca trên giả lập."""
    _run(tmp_path, g="0", git=True, gh_rc=0)
    expr = (tmp_path / "calls.log.jq").read_text(encoding="utf-8")
    samples = {
        "[]": "",
        '[{"status":"completed","conclusion":"success","databaseId":38670134404}]': "completed|success|38670134404",
        '[{"status":"in_progress","conclusion":"","databaseId":333}]': "in_progress||333",
        '[{"status":"queued","conclusion":null,"databaseId":444}]': "queued|null|444",
    }
    for doc, want in samples.items():
        out = subprocess.run(["jq", "-r", expr], input=doc, capture_output=True, text=True, check=True)
        assert out.stdout.strip() == want, (doc, out.stdout)
