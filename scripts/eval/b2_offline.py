"""B2 offline ở τ' thấp hơn τ_run (D-70) — tính lại tập E1 `injection_suspected` của các lượt M8 ĐÃ CHẠY từ audit B2, không chạy lại.

  EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/b2_offline.py --run <thư mục lượt> [--run …] \
      --scenarios eval/the100 --tau-run 0.9999 --out .verify/b2off/<tên> [--tau 0.5 --tau 0.999 --tau 0.9999]

Logic (đối chiếu `backend/app/guard/b2_review.py:42-54`, `backend/app/graph/nodes/b02_screen.py` trên tag v1.0-freeze):
- Mỗi ticket có ĐÚNG một dòng audit `step = 'B2'` — câu đầu. B2 chỉ tới từ B1 (`graph/routing.py:21-22`); câu trả lời chỉ qua L0+L2
  regex ở `graph/nodes/clarify_wait.py:46-54` (step B11, không có p_mal) → không tính lại được ở lượt sau; ticket con được gieo ở B3,
  không qua B2 (`graph/children.py:12-13, 63`). Ticket có ≥ 2 dòng B2 → DỪNG (in ticket_id). Cột `luot_b2_vuot` vì vậy chỉ là `0`
  (ticket — hoặc cha của nó — là E1 ở τ' theo B2) hoặc trống.
- Phán quyết ở τ' = gọi lại CHÍNH `after_judge("review", …, tau=τ')` trên `detail.screening` (`p_mal`, `ml_error`, `llm_is_attack`,
  `llm_category` — `b02_screen.py:74-75, 92-98`): biên p = τ' → E1; `too_many_windows` → E1 như gốc; LLM nói tấn công hoặc
  `category ≠ none` → E0 như gốc; lỗi ml khác / p rỗng → qua như gốc. Ticket gốc `screened` mà ra E1 ở τ' là E1 MỚI: dừng ở B2,
  chuyển L2 (kết quả `E1`).
- Không có phán quyết L4 (E0 regex `b02_screen.py:60-61`, E2 `guard_unavailable` `:83-91`, `turn_budget_exceeded` `:64-69`, không có
  dòng B2) → giữ nguyên kết quả gốc (code không phụ thuộc τ).
- Ticket CHA nhiều ý mà thành E1 ở τ' → các lá con KHÔNG được tạo: mọi dòng outcomes của cha và của các lá (qua
  `tickets.parent_ticket_id`) ra E1 theo cha; file ticket_id chứa cả cha lẫn mọi lá.
- Chỉ nhận τ' ∈ [0,5; 0,9999] và τ' ≤ τ_run: τ' > τ_run cần dựng lại phần sau B2 của ca đã E1 — không làm được.
- τ_run không có trong manifest (`app/eval/runner.py` `LATER` → `b2_tau` null) → truyền tay `--tau-run`. Chốt duy nhất là KIỂM TÁI LẬP:
  ở τ_run, `after_judge` phải ra ĐÚNG kết cục B2 gốc trên mọi ticket có phán quyết L4 (`injection_suspected` ↔ E1, `screened` ↔ qua,
  `injection_detected` ↔ E0) — lệch → DỪNG, in ticket_id lệch, không ghi file. `manifest.clf_mode ≠ review` → DỪNG.
  Không "đúng vì rỗng" (ĐP 31/10): in số ca E1 thật (0 cũng in), min p_mal của ca E1 thật, max p_mal của ca LLM nói không mà KHÔNG E1
  (`screened`); kiểm ĐỘC LẬP với `after_judge` (so thẳng số): max_khong_E1 < τ_run ≤ min_E1 (đúng điều kiện p ≥ τ của code). Một phía
  không có ca → in "không có ca", kiểm phía còn lại; cả hai phía không có ca → DỪNG (không có gì chứng τ_run).
- Tóm tắt có số ticket CHA nhiều ý mới thành E1 ở τ' và số lá của chúng (`cha_nhieu_y_e1`, `la_cua_cha_e1`) — bộ 100 thẻ đều một
  intent nên kỳ vọng 0; khác 0 vẫn in (dấu hiệu B3 tách sai).
- Chi phí + độ trễ của ca MỚI thành E1: chỉ giữ phần tới hết B2 (phần sau B2 của lượt gốc không xảy ra ở τ'). Script này KHÔNG tính
  hai số đó — nơi tính phải cắt theo file `e1-moi-<τ'>.txt`.

- Ca MỚI thành E1 ở τ': `route = null`, `m5_aborted = false` (= `out` của `app.eval.predictions.m5_outcome`, `predictions.py:164-175` —
  quy tắc `offline.py` và `report.py` đang dùng) → cột `route_tau`, `m5_aborted_tau`; ca không đổi giữ giá trị gốc của
  `predictions.jsonl` (ca không có bản ghi — cha nhiều ý, lỗi, hết giờ — để trống).

Lượt = THƯ MỤC `--run` (run_id sinh từ cấu hình nên KHÔNG duy nhất — hai lượt cùng cấu hình trùng run_id): nhãn lượt = tên thư mục
(trùng tên → DỪNG), tập ticket = `outcomes.jsonl` của thư mục đó (ticket của `predictions.jsonl` phải nằm trong tập này); DB lọc theo
danh sách ticket_id, không theo run_id. Cùng ticket_id ở hai thư mục → DỪNG (dữ liệu chồng).
Nguồn: `outcomes.jsonl` (scenario_id, ticket_id, hours_class — bỏ dòng `skipped_hours` / không có ticket) + `predictions.jsonl` (route,
m5_aborted) + `manifest.json` (run_id — chỉ để tham khảo, clf_mode, dataset_sha256) của từng `--run`; intent của thẻ = `gold.intents` (`app.eval.dataset.load_scenarios`, nhiều ý nối `+`; sha lệch
manifest → DỪNG); khung giờ = `hours_class` (`trong`/`ngoai`, G7). DB qua `app.eval.stack.Shell` (psql trong container postgres,
transaction CHỈ ĐỌC, không đọc `.env`) — chỉ `tickets` (id, cha, exit_code, final_state) và `audit_logs` B2 (`event`,
`detail->'screening'`); KHÔNG chọn `redacted_request`. Không gọi LLM, không gọi ml-service, không ghi DB, không in câu người dùng.

Đầu ra (`--out` dưới `.verify/`, không commit), mỗi τ': `ca-<τ'>.csv` (từng ca, không có câu người dùng), `e1-moi-<τ'>.txt` (ticket_id
mới thành E1, mỗi dòng một id, hợp các lượt — cho `offline.py` và `--exclude-tickets` của rq2); chung: `tom-tat.json` (số ca / số thẻ
thành E1 theo từng lượt (tên thư mục, kèm run_id) + dòng cộng, tách theo intent và khung giờ; dòng cộng đếm mỗi thẻ một lần dù chạy ở nhiều lượt).
(4) `<tên thư mục lượt>/predictions-tau<τ'>.jsonl` cho MỖI `--run` (offline.py, report.py trên tag chỉ nhận file predictions, không có
tuỳ chọn loại ticket): bản sao `predictions.jsonl` của lượt; dòng của ticket MỚI E1 → `route`, `decided_by`, `raw_prob`,
`calibrated_prob`, `p_method`, `kb_gap` = null (`predictions._RISK_FIELDS`, validator `_no_m5_no_risk`) và `m5_aborted = false`; dòng khác
chép NGUYÊN BYTE (không parse-rồi-dump). Đọc lại bằng `load_predictions` — lỗi → xoá file, DỪNG. Lượt không có bản ghi nào → không ghi.
KHÔNG có manifest dẫn xuất: offline.py / report.py không so sha predictions với manifest — chỉ run_id + strategy của manifest với dòng
đầu predictions (`app/eval/offline.py:149-151`, `app/eval/report.py:193-194`), dataset_sha256 giữa các lượt (`offline.py:165-166`,
`report.py:260-261`), policy_sha256 với file `--policy` (`offline.py:180-184`); `load_manifest` (`report.py:143-170`) không đọc `counts`
→ dùng NGUYÊN manifest gốc của lượt (run_id giữ nguyên). File gốc của lượt không bị sửa.
Mã thoát: 0 xong · 2 dừng (dòng cuối `DỪNG: …`).
"""

import argparse
import csv
import json
import os
import shlex
import sys
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.eval.dataset import load_scenarios, load_seed_users
from app.eval.predictions import _RISK_FIELDS, load_predictions
from app.eval.stack import Shell, StackError, quote
from app.guard.b2_review import after_judge

REPO = Path(__file__).resolve().parents[2]
VERIFY_DIR = REPO / ".verify"
DEFAULT_SEED = REPO / "mock_services" / "seed.json"  # như `runner.DEFAULT_SEED`
TAU_MIN, TAU_MAX = 0.5, 0.9999  # khoảng của B2_TAU_REVIEW (`settings.py:203`)
REPORT_TAUS = (0.5, 0.999, 0.9999)
E1 = "E1"
SUSPECTED = "injection_suspected"
SCREENED = "screened"
SKIPPED = "skipped_hours"
B2_OUTCOME = {SCREENED: "pass", SUSPECTED: E1, "injection_detected": "E0"}  # event B2 có thể đã qua L4 → kết cục `after_judge`
CSV_COLUMNS = ("scenario_id", "luot", "run_id", "ticket_id", "intent_the", "khung_gio", "luot_b2_vuot", "p_mal", "ket_qua_goc",
               "ket_qua_tau", "e1_moi", "route_tau", "m5_aborted_tau")  # fmt: skip
SUMMARY = "tom-tat.json"

TICKETS_SQL = (
    "SELECT coalesce(json_agg(json_build_object('ticket_id', ticket_id, 'parent_ticket_id', parent_ticket_id, "
    "'exit_code', exit_code, 'final_state', final_state) ORDER BY ticket_id), '[]') FROM tickets WHERE {where}"
)
B2_SQL = (
    "SELECT coalesce(json_agg(json_build_object('ticket_id', ticket_id, 'log_id', log_id, 'event', event, "
    "'screening', detail->'screening') ORDER BY ticket_id, log_id), '[]') FROM audit_logs WHERE step = 'B2' AND ticket_id IN ({ids})"
)


class Stop(Exception):
    """Dừng cả lần chạy, mã 2 — không ghi file kết quả nào sau điểm dừng."""


@dataclass(frozen=True)
class Case:
    """Một dòng `outcomes.jsonl` có ticket của một lượt (+ route, m5_aborted của bản ghi predictions nếu có)."""

    label: str  # tên thư mục lượt
    run_id: str
    scenario_id: str
    ticket_id: str
    intent: str
    hours: str
    route: str | None = None
    m5_aborted: bool | None = None


@dataclass(frozen=True)
class Db:
    tickets: Mapping[str, Mapping[str, Any]]  # ticket_id → {parent_ticket_id, exit_code, final_state}
    children: Mapping[str, tuple[str, ...]]  # cha → các lá
    b2: Mapping[str, Mapping[str, Any]]  # ticket đã chạy B2 → dòng B2 duy nhất {event, screening}


# ---- phán quyết (thuần) ----------------------------------------------------------------------------------------------


def check_tau(tau: float, tau_run: float) -> None:
    if not TAU_MIN <= tau_run <= TAU_MAX:
        raise Stop(f"τ_run = {tau_run:g} ngoài [{TAU_MIN:g}; {TAU_MAX:g}]")
    if not TAU_MIN <= tau <= TAU_MAX:
        raise Stop(f"τ' = {tau:g} ngoài [{TAU_MIN:g}; {TAU_MAX:g}]")
    if tau > tau_run:
        raise Stop(f"τ' = {tau:g} > τ_run = {tau_run:g} — không dựng lại được phần sau B2 của ca đã E1")


def judge(row: Mapping[str, Any] | None, tau: float) -> str | None:
    """Kết cục `after_judge` ở τ của dòng B2; None khi không có phán quyết L4 (E0 regex, E2, hết hạn lượt, không có dòng)."""
    if row is None or row.get("event") not in B2_OUTCOME:
        return None
    s = row.get("screening") or {}
    if "llm_is_attack" not in s:  # E0 regex: không qua L3/L4
        return None
    p = s.get("p_mal")
    return after_judge(
        "review", p_mal=None if p is None else float(p), ml_error=s.get("ml_error"), is_attack=bool(s["llm_is_attack"]),
        category=str(s.get("llm_category")), tau=tau,
    ).outcome  # fmt: skip


def single_b2(rows: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    by: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        by.setdefault(str(r["ticket_id"]), []).append(r)
    many = sorted(t for t, rs in by.items() if len(rs) > 1)
    if many:
        raise Stop(f"ticket có ≥ 2 dòng B2 (giả định một B2 mỗi ticket — câu đầu): {', '.join(many)}")
    return {t: rs[0] for t, rs in by.items()}


def reproduce(b2: Mapping[str, Mapping[str, Any]], tau_run: float) -> list[str]:
    """ticket_id mà `after_judge` ở τ_run KHÔNG ra đúng kết cục B2 gốc (rỗng = tái lập được)."""
    bad = []
    for tid, row in b2.items():
        got = judge(row, tau_run)
        if (got is not None and got != B2_OUTCOME[row["event"]]) or (row.get("event") == SUSPECTED and got != E1):
            bad.append(tid)
    return sorted(bad)


def _p(row: Mapping[str, Any]) -> float | None:
    p = (row.get("screening") or {}).get("p_mal")
    return None if p is None else float(p)


def bounds(b2: Mapping[str, Mapping[str, Any]]) -> tuple[int, float | None, float | None]:
    """(số ca E1 thật, min p_mal của ca E1 thật có p, max p_mal của ca LLM nói không mà không E1). Không có ca có p → None."""
    e1 = [r for r in b2.values() if r.get("event") == SUSPECTED]
    p_e1 = [p for r in e1 if (p := _p(r)) is not None]
    p_pass = [p for r in b2.values()
              if r.get("event") == SCREENED and "llm_is_attack" in (r.get("screening") or {}) and (p := _p(r)) is not None]  # fmt: skip
    return len(e1), min(p_e1, default=None), max(p_pass, default=None)


def check_bounds(min_e1: float | None, max_pass: float | None, tau_run: float) -> None:
    """max_khong_E1 < τ_run ≤ min_E1 — so thẳng số, không qua `after_judge`."""
    if min_e1 is None and max_pass is None:
        raise Stop("KIỂM TÁI LẬP: không có ca có p_mal ở cả hai phía — không chứng được τ_run")
    if max_pass is not None and not max_pass < tau_run:
        raise Stop(f"KIỂM TÁI LẬP LỆCH: max p_mal ca LLM nói không mà không E1 = {max_pass!r} ≥ τ_run = {tau_run!r}")
    if min_e1 is not None and not tau_run <= min_e1:
        raise Stop(f"KIỂM TÁI LẬP LỆCH: min p_mal ca E1 thật = {min_e1!r} < τ_run = {tau_run!r}")


def _flag(v: bool | None) -> str:
    return "" if v is None else str(v).lower()


def decide(cases: Sequence[Case], db: Db, tau: float) -> list[dict[str, Any]]:
    """Một dòng mỗi ca ở τ'. Ca mới E1: `route = null`, `m5_aborted = false` (`m5_outcome` → `out`). Khoá `_…` chỉ dùng nội bộ."""
    out = []
    for c in cases:
        t = db.tickets[c.ticket_id]
        root = str(t.get("parent_ticket_id") or c.ticket_id)  # lá → B2 của cha
        row = db.b2.get(root)
        e1 = judge(row, tau) == E1
        new = e1 and row is not None and row["event"] == SCREENED
        goc = str(t.get("exit_code") or t.get("final_state") or "")
        p = ((row or {}).get("screening") or {}).get("p_mal")
        out.append({
            "scenario_id": c.scenario_id, "luot": c.label, "run_id": c.run_id, "ticket_id": c.ticket_id, "intent_the": c.intent,
            "khung_gio": c.hours, "luot_b2_vuot": 0 if e1 else "", "p_mal": "" if p is None else p, "ket_qua_goc": goc,
            "ket_qua_tau": E1 if new else goc, "e1_moi": int(new),
            "route_tau": "" if new else (c.route or ""), "m5_aborted_tau": _flag(False if new else c.m5_aborted),
            "_e1": e1, "_root": root, "_b2": row is not None, "_n_la": len(db.children.get(root, ())),
        })  # fmt: skip
    return out


def new_e1_ids(rows: Iterable[Mapping[str, Any]], db: Db) -> list[str]:
    """Cha (ticket chạy B2) mới thành E1 + mọi lá của nó."""
    roots = {str(r["_root"]) for r in rows if r["e1_moi"]}
    return sorted({*roots, *(c for r in roots for c in db.children.get(r, ()))})


def _count(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    def the(rs: Iterable[Mapping[str, Any]]) -> int:
        return len({r["scenario_id"] for r in rs})

    e1 = [r for r in rows if r["_e1"]]
    new = [r for r in rows if r["e1_moi"]]
    parents = {r["_root"]: r["_n_la"] for r in new if r["_n_la"]}  # cha nhiều ý mới E1 → số lá
    return {"ca": len(rows), "the": the(rows), "ca_e1": len(e1), "the_e1": the(e1), "ca_e1_moi": len(new),
            "the_e1_moi": the(new), "ca_khong_b2": sum(not r["_b2"] for r in rows),
            "cha_nhieu_y_e1": len(parents), "la_cua_cha_e1": sum(parents.values())}  # fmt: skip


def _split(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, int]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        groups.setdefault(str(r[key]), []).append(r)
    return {k: _count(v) for k, v in sorted(groups.items())}


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {**_count(rows), "theo_intent": _split(rows, "intent_the"), "theo_khung_gio": _split(rows, "khung_gio")}


def summary_for(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Tách theo lượt = tên thư mục (run_id không duy nhất — chỉ kèm để tham khảo) + dòng cộng."""
    labels = list(dict.fromkeys(r["luot"] for r in rows))
    by = {lb: [r for r in rows if r["luot"] == lb] for lb in labels}
    return {"theo_luot": {lb: {"run_id": rs[0]["run_id"], **summarize(rs)} for lb, rs in by.items()}, "cong": summarize(rows)}


# ---- I/O -------------------------------------------------------------------------------------------------------------


def _jsonl(path: Path) -> list[Any]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _read_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        outcomes, predictions = _jsonl(run_dir / "outcomes.jsonl"), _jsonl(run_dir / "predictions.jsonl")
    except (OSError, ValueError):
        raise Stop(f"{run_dir.name}: thiếu / hỏng manifest.json, outcomes.jsonl hoặc predictions.jsonl") from None
    if not isinstance(manifest, dict) or not all(isinstance(o, dict) for o in (*outcomes, *predictions)):
        raise Stop(f"{run_dir.name}: manifest.json / outcomes.jsonl / predictions.jsonl sai dạng")
    return manifest, outcomes, predictions


def load_cases(runs: Sequence[Path], scenarios: Path, seed: Path) -> list[Case]:
    try:
        users = load_seed_users(seed)
    except ValueError as exc:
        raise Stop(str(exc)) from None
    datasets: dict[bool, Any] = {}
    labels: set[str] = set()
    owned: set[str] = set()  # ticket_id của các lượt trước (phát hiện dữ liệu chồng)
    cases: list[Case] = []
    for run_dir in runs:
        label = run_dir.resolve().name
        if label in labels:
            raise Stop(f"hai --run cùng tên thư mục {label} — nhãn lượt phải khác nhau")
        labels.add(label)
        manifest, outcomes, predictions = _read_run(run_dir)
        rid = manifest.get("run_id")
        if not isinstance(rid, str) or not rid:
            raise Stop(f"{label}: manifest thiếu run_id")
        if manifest.get("clf_mode") != "review":
            raise Stop(f"{label}: manifest.clf_mode ≠ review — lượt này không có E1 injection_suspected để tính lại")
        allow = bool((manifest.get("ignored_fields") or {}).get("allowed"))  # nạp kịch bản như lúc chạy
        if allow not in datasets:
            try:
                datasets[allow] = load_scenarios(scenarios, users=users, allow_extra=allow)
            except ValueError:
                raise Stop("--scenarios không nạp được (chạy runner --check-only để xem lỗi)") from None
        ds = datasets[allow]
        if manifest.get("dataset_sha256") != ds.sha256:
            raise Stop(f"{label}: sha của --scenarios khác manifest.dataset_sha256")
        intents = {s.id: "+".join(s.gold.intents) for s in ds.scenarios}
        records = {str(r.get("ticket_id")): r for r in predictions}
        mine: list[str] = []
        for o in outcomes:
            tid = o.get("ticket_id")
            if o.get("outcome") == SKIPPED or not tid:
                continue
            sid = str(o.get("scenario_id"))
            if sid not in intents:
                raise Stop(f"{label}: outcomes có scenario_id không có trong --scenarios")
            rec = records.get(str(tid)) or {}
            mine.append(str(tid))
            cases.append(Case(label=label, run_id=rid, scenario_id=sid, ticket_id=str(tid), intent=intents[sid],
                              hours=str(o.get("hours_class") or ""), route=rec.get("route"),
                              m5_aborted=rec.get("m5_aborted")))  # fmt: skip
        if stray := sorted(set(records) - set(mine)):
            raise Stop(f"{label}: predictions có ticket_id không có trong outcomes: {', '.join(stray)}")
        if overlap := sorted({t for t in mine if t in owned or mine.count(t) > 1}):
            raise Stop(f"{label}: ticket_id trùng — đã có ở lượt khác hoặc hai lần trong lượt (dữ liệu chồng): {', '.join(overlap)}")
        owned.update(mine)
    return cases


def _in(ids: Collection[str]) -> str:
    return ", ".join(quote(i) for i in sorted(ids))


def fetch(sql: Callable[[str], Any], ticket_ids: Collection[str]) -> Db:
    """Ba câu SELECT: ticket của outcomes (lấy cha) → cha + lá → dòng B2 của ticket đã chạy B2 (cha, hoặc chính nó)."""
    first = {str(t["ticket_id"]): t for t in sql(TICKETS_SQL.format(where=f"ticket_id IN ({_in(ticket_ids)})")) or []}
    missing = sorted(set(ticket_ids) - set(first))
    if missing:
        raise Stop(f"ticket của outcomes không có trong bảng tickets: {', '.join(missing)}")
    roots = {str(first[t].get("parent_ticket_id") or t) for t in ticket_ids}
    ids = _in(roots)
    family = list(sql(TICKETS_SQL.format(where=f"ticket_id IN ({ids}) OR parent_ticket_id IN ({ids})")) or [])
    children: dict[str, list[str]] = {}
    for t in family:
        parent = t.get("parent_ticket_id")
        if parent is not None and str(parent) in roots:
            children.setdefault(str(parent), []).append(str(t["ticket_id"]))
    return Db(
        tickets={**first, **{str(t["ticket_id"]): t for t in family}},
        children={k: tuple(sorted(v)) for k, v in children.items()},
        b2=single_b2(sql(B2_SQL.format(ids=ids)) or []),
    )


def derive_predictions(raw: bytes, new_e1: Collection[str]) -> tuple[bytes, int]:
    """(bản dẫn xuất, số dòng đổi): dòng của ticket mới E1 → route + trường điểm log 4 = null, `m5_aborted = false` (`m5_outcome` → `out`);
    dòng khác chép nguyên byte."""
    out: list[bytes] = []
    n = 0
    for line in raw.splitlines(keepends=True):  # JSON không có xuống dòng thô trong chuỗi → tách theo byte an toàn
        rec = json.loads(line) if line.strip() else None
        if not isinstance(rec, dict) or str(rec.get("ticket_id")) not in new_e1:
            out.append(line)
            continue
        rec.update({"route": None, **dict.fromkeys(_RISK_FIELDS), "m5_aborted": False})  # một nguồn với `_no_m5_no_risk`
        out.append(json.dumps(rec, ensure_ascii=False).encode("utf-8") + b"\n")
        n += 1
    return b"".join(out), n


def write_derived(dest: Path, src: Path, new_e1: Collection[str]) -> int | None:
    """Ghi + đọc lại bằng `load_predictions`; lỗi → xoá file dở, DỪNG. Nguồn rỗng → None (không ghi)."""
    try:
        raw = src.read_bytes()
    except OSError:
        raise Stop(f"{src.parent.name}: không đọc được predictions.jsonl") from None
    if not raw.strip():
        return None
    data, n = derive_predictions(raw, new_e1)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    try:
        load_predictions(dest)
    except (ValueError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise Stop(f"{dest.parent.name}/{dest.name}: bản dẫn xuất không qua load_predictions ({exc}) — đã xoá") from None
    return n


def _tag(tau: float) -> str:
    return f"{tau:g}"


def require_out(out: Path, taus: Sequence[float], labels: Sequence[str] = ()) -> Path:
    resolved = out.resolve()
    if not resolved.is_relative_to(VERIFY_DIR.resolve()):
        raise Stop(f"--out phải nằm dưới {VERIFY_DIR.name}/ (gitignore, không commit)")
    names = [SUMMARY, *(f"ca-{_tag(t)}.csv" for t in taus), *(f"e1-moi-{_tag(t)}.txt" for t in taus),
             *(f"{lb}/predictions-tau{_tag(t)}.jsonl" for lb in labels for t in taus)]
    if any((resolved / n).exists() for n in names):
        raise Stop("--out đã có file kết quả — chọn thư mục khác")
    return resolved


def _run(args: argparse.Namespace, sql: Callable[[str], Any], echo: Callable[[str], None]) -> int:
    taus = sorted(set(args.tau or REPORT_TAUS))
    for t in taus:
        check_tau(t, args.tau_run)
    dirs = {Path(d).resolve().name: Path(d) for d in args.run}
    out = require_out(args.out, taus, list(dirs))
    cases = load_cases(args.run, args.scenarios, args.seed)
    if not cases:
        raise Stop("outcomes không có ca nào có ticket")
    db = fetch(sql, {c.ticket_id for c in cases})
    n_e1, min_e1, max_pass = bounds(db.b2)

    def show(p: float | None) -> str:
        return "không có ca" if p is None else repr(p)

    echo(f"E1 thật {n_e1} ca · min p_mal E1 thật = {show(min_e1)} · max p_mal LLM nói không mà không E1 = {show(max_pass)} · "
         f"τ_run = {args.tau_run!r}")  # fmt: skip
    bad = reproduce(db.b2, args.tau_run)
    if bad:
        raise Stop(f"KIỂM TÁI LẬP LỆCH ở τ_run = {_tag(args.tau_run)} ({len(bad)} ticket): {', '.join(bad)}")
    check_bounds(min_e1, max_pass, args.tau_run)
    n_l4 = sum(judge(r, args.tau_run) is not None for r in db.b2.values())
    echo(f"{len(args.run)} lượt · {len(cases)} ca · tái lập ở τ_run = {_tag(args.tau_run)}: khớp {n_l4} ticket có phán quyết L4")
    out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"tau_run": args.tau_run, "luot": {c.label: c.run_id for c in cases},
                               "theo_tau": {}}  # fmt: skip
    for t in taus:
        rows = decide(cases, db, t)
        with (out / f"ca-{_tag(t)}.csv").open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
        ids = new_e1_ids(rows, db)
        (out / f"e1-moi-{_tag(t)}.txt").write_text("".join(f"{i}\n" for i in ids), encoding="utf-8")
        for label, run_dir in dirs.items():
            new = set(new_e1_ids([r for r in rows if r["luot"] == label], db))
            n = write_derived(out / label / f"predictions-tau{_tag(t)}.jsonl", run_dir / "predictions.jsonl", new)
            echo(f"  {label}: predictions-tau{_tag(t)}.jsonl " + ("không ghi (predictions rỗng)" if n is None else f"đổi {n} dòng"))
        s = summary_for(rows)
        summary["theo_tau"][_tag(t)] = s
        c = s["cong"]
        echo(f"τ' = {_tag(t)}: ca E1 {c['ca_e1']}/{c['ca']} (mới {c['ca_e1_moi']}) · thẻ E1 {c['the_e1']}/{c['the']} "
             f"(mới {c['the_e1_moi']}) · cha nhiều ý E1 {c['cha_nhieu_y_e1']} ({c['la_cua_cha_e1']} lá) · ticket_id mới {len(ids)}")  # fmt: skip
    (out / SUMMARY).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    echo(f"files: {out}")
    return 0


def main(argv: Sequence[str], *, sql: Callable[[str], Any] | None = None, echo: Callable[[str], None] = print) -> int:
    p = argparse.ArgumentParser(prog="b2_offline")
    p.add_argument("--run", type=Path, action="append", required=True)
    p.add_argument("--scenarios", type=Path, required=True)
    p.add_argument("--tau-run", type=float, required=True)
    p.add_argument("--tau", type=float, action="append")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    try:
        args = p.parse_args(list(argv))
    except SystemExit as exc:
        return int(exc.code or 2)
    if sql is None:
        sql = Shell(shlex.split(os.environ.get("COMPOSE", "docker compose"))).sql  # như `runner.real_deps`
    try:
        return _run(args, sql, echo)
    except (Stop, StackError) as exc:
        echo(f"DỪNG: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
