"""Cổng 5 thủ công trên stack với LLM thật (phase5 mục 1.3, 7.13; PLAN-LLMG3 §4) — `make probe F=<bộ câu .jsonl>`. TỐN TIỀN.

Mỗi câu = MỘT ticket mới của một người dùng thường (`an.nv`), câu KHÔNG có thẻ preset, ≤ 4 ticket song song; chờ LƯỢT ĐẦU đóng rồi
chỉ đọc: trạng thái + `exit_code` + tin `escalation` (khi E0); dòng audit B2 (lớp quyết định) và B3/B4/B5 (điểm log 1: intent, tách ý,
E1); `side_effects.child_create` (loại từng ý); thời gian node B3 (`spans`); `llm_calls` của lượt (chi phí, lỗi). KHÔNG đọc audit từ
B6 trở đi, KHÔNG in câu người dùng hay chữ LLM. Chấm điểm: `cong5_score.py`. Kết quả: `.verify/cong5/<giờ>/ket-qua.json`.

Chốt an toàn — TRƯỚC mọi ticket (không qua → exit 2, 0 lời gọi LLM): bộ câu đúng định dạng; như vpn-smoke (APP_ENV dev, URL 127.0.0.1,
cấm xoá volume, không FAKE_SCENARIO; cấu hình LLM đọc TRONG container backend) nhưng trần `spend.cap_usd` ≤ 2 (Q-LLMG3-5 — trần có thể
được nâng tạm lên 2 cho lượt này); model có pricing; còn ≥ 0,3 USD tới trần; ENABLED_INTENTS đủ 4; KB đang chạy = KB thật `kb/`.
`LLM_BACKEND=scripted` cũng chạy được (chạy khô, 0 USD — câu không thẻ → preset default).

Lượt hợp lệ (`run_valid`): có `LLMBudgetExceeded` → KHÔNG hợp lệ (exit 3, chạy lại CẢ lượt sau khi nạp/nâng trần); có `LLMUnavailable`
→ `can_xem` (exit 3, in ticket + tên lỗi — người quyết, không tự chạy lại). Mã thoát 0 = lượt hợp lệ, KHÔNG so tiêu chí cổng.
"""

import hashlib
import json
import os
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx
from tests.probe import cong5_score as sc
from tests.stack import gate2, gate3, gate4, gate5, vpn_smoke
from tests.stack.gate2 import Report, Run, Shell, StackError, Unsafe, q, subprocess_run

REPO = Path(__file__).resolve().parents[3]
OUT_DIR = REPO / ".verify" / "cong5"
CAP_MAX_USD = 2.0
MIN_LEFT_USD = 0.3
MAX_PARALLEL = 4
USER = gate3.AN  # một người dùng thường (nv001)
LOAD_NOTE = f"p95 B3 đo dưới tải {MAX_PARALLEL} luồng"  # Q-LLMG3-4

TICKETS_SQL = """
SELECT coalesce(json_object_agg(t.id, json_build_object(
  'audit', (SELECT coalesce(json_agg(json_build_object('step', a.step, 'event', a.event, 'intent', a.intent,
              'layer', a.detail->'screening'->>'layer_decided') ORDER BY a.log_id), '[]')
            FROM audit_logs a WHERE a.ticket_id = t.id AND a.step IN ('B2', 'B3', 'B4', 'B5')),
  'children', (SELECT coalesce(json_agg(s.result_ref ORDER BY s.created_at), '[]') FROM side_effects s
               WHERE s.ticket_id = t.id AND s.kind = 'child_create'),
  'b3_ms', (SELECT coalesce(json_agg(sp.duration_ms ORDER BY sp.started_at), '[]') FROM spans sp
            JOIN turns tu ON tu.turn_id = sp.turn_id WHERE tu.ticket_id = t.id AND sp.name = 'node:b03_classify')
)), '{{}}') FROM (VALUES {values}) AS t(id)
"""
LLM_SQL = """
SELECT json_build_object('calls', count(*), 'cost_usd', coalesce(sum(c.cost_usd), 0),
  'models', coalesce(json_agg(DISTINCT c.model), '[]'),
  'errors', coalesce(json_agg(json_build_object('ticket', tu.ticket_id, 'error', c.error)) FILTER (WHERE c.error IS NOT NULL), '[]'))
FROM llm_calls c JOIN spans s ON s.span_id = c.span_id JOIN turns tu ON tu.turn_id = s.turn_id WHERE c.call_id > {marker}
"""


@dataclass
class Sent:
    item: sc.Item
    ticket: str | None = None
    status: str | None = None
    exit_code: str | None = None
    e0_texts: tuple[str, ...] = ()
    wait_error: str | None = None


def refusal(probe: Mapping[str, Any]) -> str | None:
    """Như `vpn_smoke.refusal` nhưng trần ≤ `CAP_MAX_USD` (2)."""
    if "error" in probe or probe.get("backend") not in ("scripted", "real"):
        return vpn_smoke.refusal(probe)
    if probe["backend"] == "scripted":
        return None
    cap = probe.get("cap_usd")
    if type(cap) not in (int, float) or not cast(float, cap) <= CAP_MAX_USD:  # NaN, thiếu, > 2 → từ chối
        return f"LLM_BACKEND=real mà spend.cap_usd = {cap} > {CAP_MAX_USD:g} (config backend đang nạp)"
    if probe.get("pricing_ok") is not True:
        return "LLM_BACKEND=real mà model đang dùng chưa có dòng pricing trong config/llm.yaml"
    return None


def _send(item: sc.Item, *, url: str, shell: Shell, tokens: Mapping[str, Mapping[str, str]], password: str) -> Sent:
    """Một ticket: gửi câu (không thẻ), chờ lượt đầu đóng, giữ trạng thái + tin E0. Lỗi script/quá giờ → ghi lại, không ném."""
    sent = Sent(item)
    with httpx.Client(base_url=url, timeout=15) as http:
        ctx = gate3.Ctx(shell=shell, http=http, report=Report(echo=lambda _: None), password=password, tagged=False,
                        tokens={k: dict(v) for k, v in tokens.items()})  # fmt: skip
        try:
            sent.ticket = ctx.open(USER, item.id, item.text)
            try:
                v = ctx.settle(sent.ticket, 0)
            except StackError as exc:
                sent.wait_error = str(exc).splitlines()[0]
                v = ctx.view(sent.ticket)
        except (StackError, httpx.HTTPError, KeyError, ValueError) as exc:
            sent.wait_error = f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else ''}"
            return sent
    sent.status, sent.exit_code = v.get("status"), v.get("exit_code")
    if sent.exit_code == "E0":
        sent.e0_texts = tuple(str(m.get("text")) for m in gate3.msgs(v, "escalation"))
    return sent


def evaluate(sent: Sequence[Sent], db: Mapping[str, Any], template: str) -> dict[str, Any]:
    """Ghép kết quả gửi + DB → số đo (hàm thuần trên dữ liệu đã đọc)."""
    rows: list[dict[str, Any]] = []
    intent_pairs: list[tuple[str, tuple[str, ...]]] = []
    atk: list[tuple[str, str | None, str | None]] = []
    normal: list[tuple[str, str | None]] = []
    multi: dict[str, Any] = {"ok": 0, "total": 0, "sai": []}
    e0: dict[str, Any] = {"dung": 0, "sai": []}
    b3_ms: list[float] = []
    for s in sent:
        d = db.get(s.ticket or "", {}) if s.ticket else {}
        audit = list(d.get("audit") or [])
        b2 = [r for r in audit if r.get("step") == "B2"]
        layer = b2[-1].get("layer") if b2 else None
        pred = sc.predict([r for r in audit if r.get("step") in ("B3", "B4", "B5")], list(d.get("children") or []), s.exit_code)
        if d.get("b3_ms"):
            b3_ms.append(float(d["b3_ms"][0]))
        it = s.item
        if it.kind == "intent":
            intent_pairs.append((str(it.gold), pred.labels))
        elif it.kind == "multi":
            ok = sc.multi_ok(tuple(it.gold), pred.labels)
            multi["total"] += 1
            multi["ok"] += ok
            if not ok:
                multi["sai"].append(it.id)
        elif it.kind == "attack":
            atk.append((it.id, s.exit_code, layer))
        else:
            normal.append((it.id, s.exit_code))
        if s.exit_code == "E0":
            if sc.e0_message_ok(s.e0_texts, template):
                e0["dung"] += 1
            else:
                e0["sai"].append(it.id)
        rows.append({"id": it.id, "kind": it.kind, "gold": it.gold, "labels": list(pred.labels), "outcome": pred.outcome,
                     "ticket": s.ticket, "status": s.status, "exit_code": s.exit_code, "b2_layer": sc.layer_name(layer) if layer else None,
                     "b3_ms": d.get("b3_ms"), "wait_error": s.wait_error})  # fmt: skip
    score = sc.score_intent(intent_pairs)
    return {
        "intent": {
            "n": len(intent_pairs), "macro_f1_5": score.macro_f1_5, "macro_f1_4": score.macro_f1_4,
            "per_class": {c: {"tp": x.tp, "fp": x.fp, "fn": x.fn, "precision": x.precision, "recall": x.recall, "f1": x.f1}
                          for c, x in score.per_class.items()},
            "matrix": {g: dict(cnt) for g, cnt in score.matrix.items()},
        },
        "attack": sc.attacks(atk), "normal": sc.false_blocks(normal), "e0_message": e0, "multi": multi,
        "b3_p95_ms": sc.p95(b3_ms), "b3_n": len(b3_ms), "b3_note": LOAD_NOTE, "rows": rows,
    }  # fmt: skip


def render(res: Mapping[str, Any]) -> list[str]:
    it = res["intent"]
    cols = [*sc.LABELS, sc.MULTI_COL, sc.NONE_COL]
    lines = [f"Intent ({it['n']} câu): macro-F1 5 lớp {it['macro_f1_5']:.4f} · 4 lớp {it['macro_f1_4']:.4f}",
             "lớp | TP | FP | FN | P | R | F1"]  # fmt: skip
    for c, x in it["per_class"].items():
        lines.append(f"{c} | {x['tp']} | {x['fp']} | {x['fn']} | {x['precision']:.3f} | {x['recall']:.3f} | {x['f1']:.3f}")
    lines.append("ma trận (hàng = gold): " + " | ".join(cols))
    for g, cnt in it["matrix"].items():
        lines.append(f"{g}: " + " | ".join(str(cnt.get(c, 0)) for c in cols))
    a, n, e0, m = res["attack"], res["normal"], res["e0_message"], res["multi"]
    lines += [
        f"Tấn công bị chặn: {a['blocked']}/{a['total']} theo lớp {a['by_layer']} · không chặn: {a['not_blocked']}",
        f"Câu thường bị chặn nhầm: {n['blocked']}/{n['total']} {n['ids']}",
        f"Tin E0 trùng mẫu user_message E0: đúng {e0['dung']}, sai {len(e0['sai'])} {e0['sai']}",
        f"Nhiều ý tách đúng: {m['ok']}/{m['total']} · sai: {m['sai']}",
        f"p95 thời gian B3: {'—' if res['b3_p95_ms'] is None else format(res['b3_p95_ms'], '.0f')} ms ({res['b3_n']} ticket; {LOAD_NOTE})",
    ]  # fmt: skip
    return lines


def main(argv: Sequence[str], *, run: Run = subprocess_run, env: Mapping[str, str] = os.environ,
         echo: Callable[[str], None] = print, out_dir: Path = OUT_DIR) -> int:  # fmt: skip
    args = list(argv)
    parallel = MAX_PARALLEL
    if "--song-song" in args:
        i = args.index("--song-song")
        parallel = int(args[i + 1])
        del args[i : i + 2]
    if len(args) != 1 or not 1 <= parallel <= MAX_PARALLEL:
        echo(f"dùng: make probe F=<bộ câu .jsonl> (tuỳ chọn --song-song 1..{MAX_PARALLEL})")
        return 2
    path = Path(args[0])
    try:
        raw = path.read_bytes()
        items = sc.load_items(raw.decode("utf-8").splitlines())
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        echo(f"DỪNG: bộ câu {path}: {exc}")
        return 2
    sha = hashlib.sha256(raw).hexdigest()
    counts = sc.count_kinds(items)
    echo(f"bộ câu {path}: sha256 {sha} · {counts}")
    if counts != {"intent": 45, "multi": 10, "attack": 15, "normal": 30}:
        echo("CẢNH BÁO: số câu theo loại khác 45/10/15/30 (phase5 7.13)")

    opened = gate3.open_ctx(["preflight"], ["preflight"], run=run, env=env, echo=echo, name="cong5", require_scripted=False)
    if isinstance(opened, int):
        return opened
    _, shell, url, _flags = opened
    try:
        gate5.intents_gate(shell)
        probe = vpn_smoke.llm_probe(shell)
        reason = refusal(probe)
        spent = float(shell.sql("SELECT coalesce(sum(cost_usd), 0) FROM llm_calls"))
    except (Unsafe, StackError) as exc:
        echo(f"DỪNG (chốt an toàn): {exc}")
        return 2
    if reason is not None:
        echo(f"TỪ CHỐI: {reason}")
        return 2
    backend, cap = str(probe["backend"]), float(probe["cap_usd"])
    if backend == "real" and cap - spent < MIN_LEFT_USD:
        echo(f"TỪ CHỐI: tổng chi {spent:.4f} USD, trần {cap:g} → còn {cap - spent:.4f} < {MIN_LEFT_USD} USD")
        return 2
    echo(f"cong5: LLM_BACKEND={backend}, spend.cap_usd={cap:g}, tổng chi trước lượt {spent:.6f} USD, song song {parallel}")
    password = env.get("GATE5_PASSWORD") or gate2.password_from(env)
    with httpx.Client(base_url=url, timeout=15) as http:
        try:
            gate5.kb_gate(http)
        except Unsafe as exc:
            echo(f"DỪNG (chốt an toàn): {exc}")
            return 2
        login = gate3.Ctx(shell=shell, http=http, report=Report(echo=echo), password=password)
        try:
            login.login(USER)
        except StackError as exc:
            echo(f"DỪNG: {exc}")
            return 2
        tokens = dict(login.tokens)

    marker = int(shell.sql("SELECT coalesce(max(call_id), 0) FROM llm_calls"))
    started = datetime.now(UTC)
    quiet = Shell(shell.compose_base, run=run, echo=lambda _: None)  # chờ lượt: poll psql mỗi giây — không in từng lệnh
    lock, done = threading.Lock(), [0]

    def one(item: sc.Item) -> Sent:
        s = _send(item, url=url, shell=quiet, tokens=tokens, password=password)
        with lock:
            done[0] += 1
            echo(f"[{done[0]}/{len(items)}] {item.id} → {s.ticket} status={s.status} exit={s.exit_code}"
                 + (f" · {s.wait_error}" if s.wait_error else ""))  # fmt: skip
        return s

    with ThreadPoolExecutor(max_workers=parallel) as pool:
        sent = list(pool.map(one, items))
    tickets = [s.ticket for s in sent if s.ticket]
    db: dict[str, Any] = {}
    if tickets:
        values = ", ".join(f"({q(t)})" for t in tickets)
        db = dict(shell.sql(TICKETS_SQL.format(values=values)) or {})
    llm = dict(shell.sql(LLM_SQL.format(marker=marker)) or {})
    status, reasons = sc.run_valid([(str(e["ticket"]), str(e["error"])) for e in llm.get("errors") or []])
    res = evaluate(sent, db, gate3.user_message("E0"))
    res.update({
        "sha256": sha, "file": str(path), "counts": counts, "head": gate4._git(run, "rev-parse", "HEAD"),
        "started": started.isoformat(), "ended": datetime.now(UTC).isoformat(), "llm_backend": backend, "cap_usd": cap,
        "parallel": parallel, "llm_calls": llm.get("calls"), "models": llm.get("models"), "cost_usd": llm.get("cost_usd"),
        "llm_errors": llm.get("errors"), "hop_le": status, "hop_le_ly_do": reasons,
    })  # fmt: skip
    echo("\n==== Kết quả cổng 5 thủ công ====")
    for line in render(res):
        echo(line)
    echo(f"llm_calls của lượt: {res['llm_calls']} dòng · cost_usd {float(res['cost_usd'] or 0):.6f} · model {res['models']}")
    folder = out_dir / started.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ket-qua.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    echo(f"Ghi: {folder / 'ket-qua.json'}")
    if status != "hop_le":
        echo(f"LƯỢT {status.upper()}: {reasons} — DỪNG, báo người (không tự chạy lại, không tự tính kết quả)")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
