"""Gói 2b — chống spam (D-54 a): cấu hình triển khai và đường nới ngưỡng (đặc tả `claude/dac-ta-bat-2-model.md` 4.8 "Ngưỡng",
"Không có giá trị tắt"; 8 "`verify.sh` nới ngưỡng"; PLAN-2B1 G11, 3.5, ca U16–U18).

- U16: compose truyền 3 biến vào backend + worker dạng `${X:-}` (rỗng = mặc định `settings.py`, G4); `.env.example` để trống.
- U17: `scripts/verify.sh` nới bằng `LOOSE_RATES` ở MỌI lần tạo lại backend+worker ngay trước một cổng (`recreate` của gate2–5);
  bước 3 `make up` KHÔNG nới (Q-2B1-7 A — bước 3 đỏ thì không có bước 8 trả về `.env`); bước 8 gỡ cả 3 biến (Q-2B1-5). Đọc tĩnh + chạy THẬT với `make`/`compose` GIẢ riêng của file này (khuôn
  `test_verify_script.py`, không sửa file đó) — stub ghi giá trị 3 biến mà lệnh nhìn thấy.
- U18: `make … RATE=loose` export đúng 3 biến, cùng số với `LOOSE_RATES` của `verify.sh` (số 100000 nằm 2 chỗ — Q-2B1-2 A).
  Chạy `make` với một target in biến thêm bằng `--eval` — KHÔNG chạy `make up` thật, không đụng Docker.
"""

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
VERIFY = REPO / "scripts" / "verify.sh"
RATE_VARS = ("TICKET_RATE_10MIN", "TICKET_RATE_HOUR", "MESSAGE_RATE_10MIN")
LOOSE = "100000"  # 4.8: "nới bằng số lớn (vd 100000)"; hợp đồng LOOSE_RATES của PLAN-2B1 3.5
LOOSE_REF = re.compile(r"\$\{?LOOSE_RATES\}?")


def compose() -> dict[str, Any]:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))


def loose_rates() -> dict[str, str]:
    """Giá trị gán cho `LOOSE_RATES` trong `verify.sh` → {biến: số}."""
    text = VERIFY.read_text(encoding="utf-8")
    found = re.search(r"""^\s*(?:readonly\s+|declare\s+-r\s+)?LOOSE_RATES=(["']?)(.*?)\1\s*(?:#.*)?$""", text, re.MULTILINE)
    assert found, "verify.sh không có LOOSE_RATES=…"
    return dict(pair.split("=", 1) for pair in found.group(2).split())


def logical_lines(text: str) -> list[str]:
    """Gộp dòng nối tiếp (`\\` cuối dòng) — `recreate`/`step_restore` viết `env … \\` rồi `$COMPOSE up …` ở dòng sau."""
    return [line.strip() for line in re.sub(r"\\\n\s*", " ", text).splitlines()]


# ---- U16: compose + .env.example -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("var", RATE_VARS)
def test_u16_compose_passes_rate_vars_empty_default(var: str) -> None:
    """U16 (4.8: biến thêm vào `x-backend-env`; G4 rỗng = mặc định `settings.py`): backend và worker cùng giá trị; ml-service không có."""
    c = compose()
    expected = f"${{{var}:-}}"
    assert c["x-backend-env"][var] == expected
    for name in ("backend", "worker"):
        assert c["services"][name]["environment"][var] == expected
    assert var not in c["services"]["ml-service"]["environment"]


@pytest.mark.parametrize("var", RATE_VARS)
def test_u16_env_example_declares_blank(var: str) -> None:
    """U16 (4.8; PLAN 3.5): `.env.example` có dòng `X=` để trống (không giá trị "tắt", không số lớn)."""
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    assert f"{var}=" in lines
    assert not [line for line in lines if re.match(rf"^\s*{var}=\S", line)]


# ---- U17: verify.sh tĩnh ---------------------------------------------------------------------------------------------------------


def test_u17_loose_rates_three_assignments() -> None:
    """U17: `LOOSE_RATES` = đúng 3 phép gán `= 100000`."""
    assert loose_rates() == dict.fromkeys(RATE_VARS, LOOSE)


def test_u17_every_build_or_recreate_has_loose_rates_restore_unsets() -> None:
    """U17 (G11, Q-2B1-7 A): `recreate` của gate2–5 (`$COMPOSE up`) có `$LOOSE_RATES`; bước 3 (`"$MAKE" up`) KHÔNG có; bước 8
    (`step_restore`) KHÔNG nới mà `env -u` cả 3 biến — stack sau verify chạy theo `.env` (Q-2B1-5)."""
    commands = [
        line for line in logical_lines(VERIFY.read_text(encoding="utf-8"))
        if line and not line.startswith(("#", "add_row", "say", "echo"))
        and re.search(r'(\$COMPOSE|\$\{COMPOSE\}|"\$MAKE"|\$MAKE)\s+up\b', line)
    ]  # fmt: skip
    restore = [line for line in commands if "env -u" in line]
    builds = [line for line in commands if "env -u" not in line]
    assert len(restore) == 1 and len(builds) == 2, commands  # step_up + recreate | step_restore
    [step_up] = [line for line in builds if re.search(r'"?\$MAKE"?\s+up\b', line)]
    [recreate] = [line for line in builds if line is not step_up]
    assert LOOSE_REF.search(recreate), recreate
    assert not LOOSE_REF.search(step_up), step_up  # Q-2B1-7 A: bước 3 đỏ không được bỏ lại stack đã nới
    [line] = restore
    for var in RATE_VARS:
        assert re.search(rf"-u\s+{var}\b", line), line
    assert not LOOSE_REF.search(line)


# ---- U17: verify.sh chạy thật với stub -------------------------------------------------------------------------------------------

_SEEN = " ".join(f"${{{v}-<unset>}}" for v in RATE_VARS)
MAKE_STUB = f"""#!/usr/bin/env bash
echo "make $* | {_SEEN}" >>"$STUB_LOG"
exit 0
"""
COMPOSE_STUB = f"""#!/usr/bin/env bash
echo "compose $* | {_SEEN}" >>"$STUB_LOG"
if [[ "$*" == *"printenv APP_ENV"* ]]; then echo dev; fi
exit 0
"""
STUBS = {
    "make": MAKE_STUB,
    "compose": COMPOSE_STUB,
    "uv": "#!/usr/bin/env bash\nexit 0\n",
    "curl": "#!/usr/bin/env bash\nexit 0\n",
    "gh": "#!/usr/bin/env bash\nexit 1\n",
    "uname": "#!/usr/bin/env bash\necho Linux\n",
    "pmset": "#!/usr/bin/env bash\nexit 0\n",
    "caffeinate": "#!/usr/bin/env bash\nexit 0\n",
}  # fmt: skip
SHELL_VALUE = "11"  # giá trị của shell cha (như `.env`/biến người chạy đã đặt) — bước 8 phải gỡ, bước dựng phải đè


def _run_verify(tmp_path: Path, g: str) -> tuple[int, list[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    work = tmp_path / "repo"
    work.mkdir()
    log = tmp_path / "calls.log"
    log.write_text("")
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "HOME": str(tmp_path), "G": g, "BENCH": "0",
        "MAKE_BIN": str(bin_dir / "make"), "COMPOSE": str(bin_dir / "compose"), "STUB_LOG": str(log),
        "GIT_CEILING_DIRECTORIES": str(tmp_path), "GIT_CONFIG_NOSYSTEM": "1",
        **dict.fromkeys(RATE_VARS, SHELL_VALUE),
    }  # fmt: skip
    out = subprocess.run(["bash", str(VERIFY)], cwd=work, env=env, capture_output=True, text=True, timeout=60, check=False)
    summary = (work / ".verify" / "summary.txt").read_text(encoding="utf-8")
    return out.returncode, log.read_text(encoding="utf-8").splitlines(), summary


def _seen(line: str) -> list[str]:
    return line.split(" | ", 1)[1].split()


def test_u17_g2345_every_up_sees_loose_restore_sees_unset(tmp_path: Path) -> None:
    """U17: `make verify G=2345` (4.8: không nới thì đỏ — gate2 một mình tạo > 10 ticket cho `an.nv`) — 4 lần `compose up
    --force-recreate` (gate2, gate3, gate4, gate5) thấy 100000; `make up` (bước 3) KHÔNG bị nới — thấy đúng giá trị của shell cha
    (Q-2B1-7 A); bước 8 thấy `<unset>` cả 3 (stack về `.env`)."""
    rc, calls, summary = _run_verify(tmp_path, "2345")
    assert rc == 0, summary
    assert "KẾT LUẬN: XANH" in summary and "| 8 | trả về .env | PASS |" in summary
    [make_up] = [c for c in calls if c.startswith("make up")]
    assert _seen(make_up) == [SHELL_VALUE] * 3, make_up
    ups = [c for c in calls if c.startswith("compose up")]
    assert len(ups) == 5, ups
    assert all("--force-recreate" in c and " backend worker |" in c for c in ups), ups
    for line in ups[:-1]:
        assert _seen(line) == [LOOSE] * 3, line
    assert _seen(ups[-1]) == ["<unset>"] * 3, ups[-1]


def test_u17_g0_touches_nothing(tmp_path: Path) -> None:
    """Đối chứng: G=0 chỉ lint + test, không dựng stack → không lệnh `up` nào."""
    rc, calls, _ = _run_verify(tmp_path, "0")
    assert rc == 0
    assert not [c for c in calls if c.startswith(("make up", "compose up"))]


# ---- U18: Makefile RATE=loose --------------------------------------------------------------------------------------------------

_PRINT_RECIPE = "\t@echo " + " ".join(f'"$${{{v}-UNSET}}"' for v in RATE_VARS) + "\n"


def _make_sees(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Chạy `make` trên một makefile tạm `include` Makefile của repo + một target chỉ `echo` 3 biến (make 3.81 của macOS không có
    `--eval`) — không target thật nào chạy. `cwd` = thư mục tạm: `$(wildcard .env)` / `git status` của Makefile nhìn thư mục tạm,
    không đụng `.env` của repo. Môi trường không có 3 biến (conftest gốc đặt = 100000 cho tiến trình test → bỏ đi)."""
    wrapper = cwd / "print-rates.mk"
    wrapper.write_text(f"include {REPO / 'Makefile'}\n\nprint-rates-2b:\n{_PRINT_RECIPE}", encoding="utf-8")
    drop = {*RATE_VARS, "MAKEFLAGS", "MFLAGS", "MAKELEVEL", "RATE"}
    env = {**{k: v for k, v in os.environ.items() if k not in drop}, "GIT_CEILING_DIRECTORIES": str(cwd)}
    return subprocess.run(
        ["make", "-s", "--no-print-directory", "-f", str(wrapper), "print-rates-2b", *args],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip


def test_u18_rate_loose_exports_same_numbers_as_verify(tmp_path: Path) -> None:
    """U18 (Q-2B1-2 A): `RATE=loose` export đúng 3 biến, CÙNG số với `LOOSE_RATES` của `verify.sh`; không có `RATE` → không export."""
    loose = _make_sees(tmp_path, "RATE=loose")
    assert loose.returncode == 0, loose.stderr
    assert loose.stdout.split() == [loose_rates()[v] for v in RATE_VARS] == [LOOSE] * 3
    plain = _make_sees(tmp_path)
    assert plain.returncode == 0, plain.stderr
    assert plain.stdout.split() == ["UNSET"] * 3


def test_u18_rate_other_value_is_error(tmp_path: Path) -> None:
    """PLAN-2B1 3.5: `RATE` khác rỗng/`loose` → lỗi (không lặng lẽ chạy ngưỡng thật khi gõ sai). Giả định: kiểm lúc đọc Makefile
    (`$(error …)`), nên target nào cũng dừng — cần cho `make gate2 S=restart-all RATE=loose` (G11) đi qua `MAKEFLAGS`."""
    bad = _make_sees(tmp_path, "RATE=nhanh")
    assert bad.returncode != 0, bad.stdout
