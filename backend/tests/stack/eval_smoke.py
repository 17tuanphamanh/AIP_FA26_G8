"""Smoke harness G2 trên stack compose THẬT — không nằm trong `make test` (cần `make up`, gói luật giả `.luat-gia/kiem.py` ĐẠT,
`LLM_BACKEND=scripted`).

    EVAL_MODE=true EVAL_PASSWORD=… PYTHONPATH=backend uv run python -m tests.stack.eval_smoke --timeout-s 120 \
        [--keep-out ~/eval-runs/smoke] [--per-case]

Kịch bản TỔNG HỢP (không phải kịch bản thật), sinh vào thư mục tạm (hoặc `--keep-out`). Người gửi / preset chọn theo bảng của gói
luật GIẢ (`.luat-gia/BANG-LUAT-GIA.md`); câu đầu có thẻ `[fake:<preset>]` (LLM giả chỉ trả lời câu có thẻ — `kiem.py:154`):
- `SMOKE-K1`, `SMOKE-K2`: ca 1, ca 2 của `.luat-gia/kiem.py:28-31` (binh.tt gia_tk → R83 chuyển L2; an.nv gia_vpn → LLM giả chuyển L2)
  → tới điểm log 4.
- `SMOKE-A`: son.nt (Sales) gia_tk → R82 chờ duyệt (BANG-LUAT-GIA.md:9), `approver_decision: approve` → SimApprover duyệt trên stack
  → ca phải kết thúc (`done`, `final_state` có), `has_approval = true`, route HITL.
- Lượt PHỤ (thư mục con `timeout/`): 1 ca `SMOKE-TO` = bản sao SMOKE-A với `approver_decision: ignore`, `--timeout-s 3` → ca chờ duyệt,
  không ai bấm (SLA duyệt 30 phút) → `timeout`, bản ghi `final_state = None`, runner exit 1.

KHÔNG có ca hỏi lại: trên gói luật giả (b582058) preset `gia_hoi_lai` đi B10:needs_action → B11:output_guard_block → E3 (câu hỏi lại
của preset bị output guard chặn — đã báo Tuấn Anh). Đọc `detail->>'turn'` ở B11 chỉ được kiểm bằng unit test + đột biến M-G2-4/5/13.

Kiểm: mã thoát ∈ {0, 1}; đủ 3 file; `load_predictions` qua; `outcomes.jsonl` đủ dòng; manifest `loaded` đúng; ≥ 2 bản ghi có route;
`SMOKE-A` done + `has_approval` + route HITL; lượt phụ exit 1 + `timeout` + `final_state = None`; có request HTTP (đối chứng > 0) và 0 request tới đường dẫn có `/policy` (Rev 27).

In: 7 dòng tổng hợp của runner (lượt phụ có tiền tố `[phụ]`) + dòng `smoke:` + PASS/FAIL. `--per-case` (CHỈ vì đây là kịch bản tổng
hợp trên gói luật giả; không áp cho kịch bản thật): thêm mỗi ca `scenario_id outcome final_state exit_code route has_approval
clarification_turns`.
"""

import argparse
import json
import sys
import tempfile
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx
import yaml
from app.eval import runner
from app.eval.predictions import PredictionRecord, load_predictions

APPROVE_CASE = "SMOKE-A"
TIMEOUT_ID = "SMOKE-TO"
SUB_TIMEOUT_S = 3
# .luat-gia/kiem.py:28-31 — (tên đăng nhập, preset, câu)
KIEM_CA1 = ("binh.tt", "gia_tk", "Mình quên mật khẩu tài khoản AD, nhờ đặt lại giúp mình.")
KIEM_CA2 = ("an.nv", "gia_vpn", "Kiểm tra giúp mình tình trạng VPN trên máy với.")
# BANG-LUAT-GIA.md:9 — Sales + gia_tk → R82 chờ duyệt
HITL_CASE = ("son.nt", "gia_tk", "Mình quên mật khẩu tài khoản AD, nhờ đặt lại giúp mình.")


def _one(sid: str, user: str, text: str, intent: str, decision: str | None = None) -> dict[str, Any]:
    gold: dict[str, Any] = {"intents": [intent], "expected_route": "HITL"}
    if decision is not None:
        gold["approver_decision"] = decision
    return {"id": sid, "family": f"F-{sid}", "requester": user, "turns": [text], "gold": gold}


def _tagged(case: tuple[str, str, str]) -> tuple[str, str]:
    user, preset, text = case
    return user, f"{text} [fake:{preset}]"


def scenarios() -> list[dict[str, Any]]:
    return [
        _one("SMOKE-K1", *_tagged(KIEM_CA1), "account", "approve"),
        _one("SMOKE-K2", *_tagged(KIEM_CA2), "vpn", "approve"),
        _one(APPROVE_CASE, *_tagged(HITL_CASE), "account", "approve"),
    ]


def timeout_scenario() -> dict[str, Any]:
    return _one(TIMEOUT_ID, *_tagged(HITL_CASE), "account", "ignore")


def _write(scen: Path, items: list[dict[str, Any]]) -> None:
    scen.mkdir(parents=True)
    for i, item in enumerate(items):
        (scen / f"smoke-{i}.yaml").write_text(yaml.safe_dump(item, allow_unicode=True), encoding="utf-8")


def _results(out: Path) -> tuple[list[PredictionRecord], dict[str, dict[str, Any]], dict[str, Any]] | None:
    files = [out / f for f in runner.OUT_FILES]
    if not all(f.exists() for f in files):
        return None
    text = files[0].read_text(encoding="utf-8")
    records = load_predictions(files[0]) if text else []
    outcomes = [json.loads(x) for x in files[1].read_text(encoding="utf-8").splitlines()]
    return records, {o["scenario_id"]: o for o in outcomes}, json.loads(files[2].read_text(encoding="utf-8"))


def _base(keep: Path | None, stack: Any) -> Path:
    if keep is None:
        return Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="g2-smoke-")))
    keep = keep.expanduser()
    if keep.exists() and any(keep.iterdir()):
        raise SystemExit("DỪNG: --keep-out phải là thư mục mới hoặc rỗng")
    keep.mkdir(parents=True, exist_ok=True)
    return keep


def main(argv: Sequence[str], *, echo: Callable[[str], None] = print) -> int:
    p = argparse.ArgumentParser(prog="python -m tests.stack.eval_smoke")
    p.add_argument("--timeout-s", type=int, required=True)
    p.add_argument("--url", default=runner.DEFAULT_URL)
    p.add_argument("--keep-out", type=Path)
    p.add_argument("--per-case", action="store_true")
    args = p.parse_args(list(argv))
    items = scenarios()
    paths: list[str] = []

    def make_deps(url: str) -> runner.Deps:
        deps = runner.real_deps(url)

        def record(request: httpx.Request) -> None:
            paths.append(request.url.path)

        deps.http.event_hooks["request"].append(record)
        return deps

    def run(scen: Path, out: Path, timeout_s: int, prefix: str = "") -> int:
        return runner.main(["--scenarios", str(scen), "--out", str(out), "--strategy", "hybrid", "--split", "test",
                            "--timeout-s", str(timeout_s), "--url", args.url], make_deps=make_deps,
                           out=lambda line: echo(prefix + line))  # fmt: skip

    checks: dict[str, bool] = {}
    with ExitStack() as stack:
        base = _base(args.keep_out, stack)
        # ---- lượt chính ----
        _write(base / "scen", items)
        code = run(base / "scen", base / "out", args.timeout_s)
        echo(f"smoke: runner exit={code}")
        checks["exit 0/1"] = code in (0, 1)
        try:
            res = _results(base / "out")
            checks["đủ 3 file"] = res is not None
            checks["load_predictions qua"] = res is not None
        except ValueError:
            res, checks["load_predictions qua"] = None, False
        if res is not None:
            records, by_id, manifest = res
            recs = {r.scenario_id: r for r in records}
            routed = sum(r.route is not None for r in records)
            checks[f"outcomes đủ {len(items)} dòng"] = len(by_id) == len(items)
            checks[f"manifest loaded={len(items)}"] = manifest["counts"]["loaded"] == len(items)
            checks["≥ 2 bản ghi tới điểm log 4 (route khác None)"] = routed >= 2
            a = recs.get(APPROVE_CASE)
            checks[f"{APPROVE_CASE} done sau khi duyệt (has_approval, route HITL, final_state có)"] = (
                by_id.get(APPROVE_CASE, {}).get("outcome") == "done" and a is not None and a.has_approval
                and a.route == "HITL" and a.final_state is not None)  # fmt: skip
            echo(f"smoke: records={len(records)} routed={routed} commit_verified={manifest['commit_verified']} "
                 f"git_dirty={manifest['git_dirty']}")  # fmt: skip
            if args.per_case:  # CHỈ kịch bản tổng hợp của smoke
                echo("smoke ca: scenario_id outcome final_state exit_code route has_approval clarification_turns")
                for sid, o in by_id.items():
                    r = recs.get(sid)
                    cols = (r.final_state, r.exit_code, r.route, r.has_approval, r.clarification_turns) if r else ("-",) * 5
                    echo(f"  {sid} {o['outcome']} {' '.join(map(str, cols))}{' ' + o['error_type'] if o['error_type'] else ''}")
        # ---- lượt phụ: hết giờ ----
        sub = base / "timeout"
        _write(sub / "scen", [timeout_scenario()])
        sub_code = run(sub / "scen", sub / "out", SUB_TIMEOUT_S, prefix="[phụ] ")
        echo(f"smoke: runner phụ exit={sub_code}")
        try:
            sub_res = _results(sub / "out")
        except ValueError:
            sub_res = None
        to = sub_res[0][0] if sub_res and sub_res[0] else None
        checks[f"lượt phụ {TIMEOUT_ID}: exit 1 + timeout + final_state None"] = (
            sub_code == 1 and sub_res is not None and sub_res[1].get(TIMEOUT_ID, {}).get("outcome") == "timeout"
            and to is not None and to.final_state is None)  # fmt: skip
        n_policy = sum("/policy" in x for x in paths)
        checks["có request HTTP (đối chứng)"] = len(paths) > 0
        checks["không gọi /policy"] = n_policy == 0
        echo(f"smoke: http_requests={len(paths)} policy_requests={n_policy}")
        if args.keep_out is not None:
            echo(f"smoke: giữ kết quả ở {base}")
    for name, ok in checks.items():
        echo(f"{'PASS' if ok else 'FAIL'} {name}")
    passed = all(checks.values())
    echo("SMOKE ĐẠT" if passed else "SMOKE KHÔNG ĐẠT")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
