"""Smoke luồng VPN với LLM đang cấu hình (phase3 mục 11.9; PLAN-3h S15b) — `make vpn-smoke` sau `make up`.

Chạy tc02, tc04, tc05, tc06 của `gate3.py` trên stack compose thật với `LLM_BACKEND` HIỆN HÀNH của container backend, rồi in
từ `llm_calls` (chỉ các dòng của lần chạy này): tỉ lệ JSON hợp lệ lần đầu, số lần sửa schema, p95 độ trễ theo prompt, tổng
`cost_usd`. `scripted`: thẻ preset `[fake:tcXX]` như gate3. `real`: câu KHÔNG có thẻ (không gửi chữ lạ cho LLM thật); dòng
PASS/FAIL của kịch bản là để đọc — LLM thật lệch route là tín hiệu sửa prompt/schema (11.9 bước 4), không phải lỗi script.

Chốt an toàn — TRƯỚC mọi HTTP/ticket (không qua → exit 2, 0 lời gọi LLM):
1. Như gate3: APP_ENV `dev`, URL `127.0.0.1`, cấm xoá volume, không đặt `FAKE_SCENARIO`.
2. Cấu hình LLM đọc TRONG container backend (config mà process ĐANG nạp — không đọc file trên đĩa repo; chốt Q-3h-8):
   `real` mà `spend.cap_usd` > 1 → TỪ CHỐI; `real` mà model đang dùng (FAST/STRONG + fallback) chưa có dòng `pricing` →
   TỪ CHỐI; không đọc được cấu hình / backend lạ → TỪ CHỐI. Script trong container chỉ in JSON gồm nhãn backend, `cap_usd`,
   cờ `pricing_ok` — không in tên model, URL hay khoá (lỗi → chỉ tên lớp lỗi).
Trần chi là `spend.cap_usd` của `config/llm.yaml` (Q-3d-3: không nội suy env — spec 11.9 ghi `LLM_SPEND_CAP_USD` là cũ). Hạ tạm
về 1 trên máy người chạy, KHÔNG commit — các bước ở `README.md` mục "Chạy smoke LLM thật".
"""

import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import httpx
from tests.stack import gate2, gate3
from tests.stack.gate2 import Report, Run, Shell, StackError, subprocess_run

SMOKE = ["preflight", "tc02", "tc04", "tc05", "tc06"]
CAP_MAX_USD = 1.0

# Chạy trong container backend (`python -c`): chỉ in MỘT dòng JSON — nhãn backend, cap_usd, pricing_ok; lỗi → tên lớp lỗi.
PROBE = """
import json
try:
    from app.llm.config import ROLES, SCRIPTED_MODEL, load_llm_config
    from app.settings import get_settings
    s = get_settings()
    cfg = load_llm_config(s.config_dir / "llm.yaml")
    backend = s.llm_backend if s.llm_backend in ("scripted", "real") else "?"
    if backend == "real":
        models = [getattr(s, cfg.roles[r].model_setting) for r in ROLES] + [f.model for r in ROLES for f in cfg.fallback[r]]
    else:
        models = [SCRIPTED_MODEL]
    out = {"backend": backend, "cap_usd": float(cfg.spend.cap_usd),
           "pricing_ok": all(bool(m) and m in cfg.pricing for m in models)}
except Exception as e:
    out = {"error": type(e).__name__}
print(json.dumps(out))
"""

STATS_SQL = """
SELECT coalesce(json_agg(r ORDER BY r.prompt_id), '[]') FROM (
  SELECT prompt_id,
         count(*) AS calls,
         count(*) FILTER (WHERE NOT cache_hit AND json_valid_first_try IS NOT NULL) AS parsed,
         count(*) FILTER (WHERE NOT cache_hit AND json_valid_first_try) AS valid_first,
         count(*) FILTER (WHERE NOT cache_hit AND json_valid_first_try = false) AS repaired,
         count(*) FILTER (WHERE cache_hit) AS cache_hits,
         count(*) FILTER (WHERE error IS NOT NULL) AS errors,
         percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) FILTER (WHERE NOT cache_hit) AS p95_ms,
         coalesce(sum(cost_usd), 0) AS cost_usd
  FROM llm_calls WHERE call_id > {marker} GROUP BY prompt_id) r
"""


def llm_probe(shell: Shell) -> dict[str, Any]:
    out = shell.compose("exec", "-T", "backend", "python", "-c", PROBE)
    lines = [line for line in out.strip().splitlines() if line.strip()]
    try:
        data = json.loads(lines[-1]) if lines else None
    except json.JSONDecodeError:
        data = None
    return data if isinstance(data, dict) else {"error": "khong_doc_duoc_ket_qua"}


def refusal(probe: Mapping[str, Any]) -> str | None:
    """Lý do TỪ CHỐI chạy (None = được chạy). Chặt: thiếu trường hay kiểu lạ cũng là từ chối."""
    if "error" in probe:
        return f"không đọc được cấu hình LLM trong container backend ({probe['error']})"
    backend = probe.get("backend")
    if backend not in ("scripted", "real"):
        return "LLM_BACKEND của container backend không phải scripted/real"
    if backend == "scripted":
        return None
    cap = probe.get("cap_usd")
    if type(cap) not in (int, float) or not cap <= CAP_MAX_USD:  # NaN, thiếu, > 1 → từ chối
        return (f"LLM_BACKEND=real mà spend.cap_usd = {cap} > {CAP_MAX_USD:g} (config backend đang nạp) — hạ tạm "
                "cap_usd trong config/llm.yaml rồi build lại (README mục \"Chạy smoke LLM thật\")")  # fmt: skip
    if probe.get("pricing_ok") is not True:
        return "LLM_BACKEND=real mà model đang dùng chưa có dòng pricing trong config/llm.yaml"
    return None


def _num(value: Any, fmt: str) -> str:
    return "—" if value is None else format(value, fmt)


def render_stats(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Bảng theo prompt + dòng tổng. Tỉ lệ JSON hợp lệ lần đầu tính trên lời gọi KHÔNG trúng cache có phản hồi."""
    lines = ["prompt_id | lời gọi | JSON hợp lệ lần đầu | sửa schema | cache | lỗi | p95 ms | cost_usd"]
    for r in rows:
        lines.append(f"{r['prompt_id']} | {r['calls']} | {r['valid_first']}/{r['parsed']} | {r['repaired']} | "
                     f"{r['cache_hits']} | {r['errors']} | {_num(r['p95_ms'], '.0f')} | {r['cost_usd']:.6f}")  # fmt: skip
    parsed = sum(int(r["parsed"]) for r in rows)
    valid = sum(int(r["valid_first"]) for r in rows)
    ratio = f"{valid}/{parsed} ({valid / parsed:.1%})" if parsed else "0/0 (—)"
    lines.append(f"TỔNG: {sum(int(r['calls']) for r in rows)} lời gọi · JSON hợp lệ lần đầu {ratio} · sửa schema "
                 f"{sum(int(r['repaired']) for r in rows)} · cost_usd {sum(float(r['cost_usd']) for r in rows):.6f}")  # fmt: skip
    return lines


def main(argv: Sequence[str], *, run: Run = subprocess_run, env: Mapping[str, str] = os.environ,
         echo: Callable[[str], None] = print) -> int:  # fmt: skip
    opened = gate3.open_ctx(["all"], SMOKE, run=run, env=env, echo=echo, name="vpn_smoke", require_scripted=False)
    if isinstance(opened, int):
        return opened
    names, shell, url, flags = opened
    try:
        probe = llm_probe(shell)
    except StackError as exc:
        echo(f"TỪ CHỐI: không chạy được kiểm cấu hình LLM trong container backend ({type(exc).__name__})")
        return 2
    reason = refusal(probe)
    if reason is not None:
        echo(f"TỪ CHỐI: {reason}")
        return 2
    backend = str(probe["backend"])
    echo(f"vpn-smoke: LLM_BACKEND={backend}, spend.cap_usd={probe['cap_usd']:g} (config container backend)")
    report = Report(echo=echo)
    marker = int(shell.sql("SELECT coalesce(max(call_id), 0) FROM llm_calls"))
    with httpx.Client(base_url=url, timeout=15) as http:
        ctx = gate3.Ctx(shell=shell, http=http, report=report, tagged=backend == "scripted",
                        password=env.get("GATE3_PASSWORD") or gate2.password_from(env))  # fmt: skip
        gate3.header(ctx)
        gate3.warnings(ctx, flags)
        stopped = gate3.run_scenarios(ctx, names)
        if stopped is not None:
            return stopped
    rows = list(shell.sql(STATS_SQL.format(marker=marker)) or [])
    echo("\n==== llm_calls của lần chạy này ====")
    for line in render_stats(rows):
        echo(line)
    report.check("-", "llm_calls có dòng mới", bool(rows), "> 0 dòng", len(rows))
    return report.summary()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
