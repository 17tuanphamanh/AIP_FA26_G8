"""Thu thập `answers.jsonl` từ DB cho groundedness offline (G11, nối mốc G). Chỉ đọc (phiên ép read-only, `app.eval.dbread`).

Nguồn (mỗi ticket info trong bộ câu):
- **Có câu trả lời không**: `audit_logs` `step='B10'`, dòng CUỐI trong {`deflected_info_only` (có câu trả lời), `cannot_answer`}. Các event
  khác (invalid_citation, output_guard_block, no_evidence, llm_*…) hoặc không có dòng B10 → ca KHÔNG phải câu trả lời: bỏ, đếm theo lý do.
- **citations**: `audit_logs.detail->'cited'` (b10_route). **answer**: tin `kind="answer"` cuối cùng trong `conversation` của checkpoint
  LangGraph (chữ đã render, có khối "Nguồn:" — `split` tự bỏ); không có bảng nào khác chứa chữ này.
- **chunks (gồm chunk liền kề D-24)**: `llm_calls.prompt_full` của lời gọi `b10_answer` (EVAL_MODE) — tin nhắn `user`, sau "Bằng chứng:",
  các khối `[<anchor>] <title> › <heading>\\n<text>` nối bằng `\\n\\n` (`llm/context._fmt_evidence`). Tách theo ĐÚNG tiêu đề của các chunk
  top-5 (checkpoint `retrieved`), không đoán bằng regex chung; một ticket có nhiều lời gọi `b10_answer` → lấy lời gọi cuối KHÔNG lỗi.
  `prompt_full` rỗng hoặc thiếu khối của một chunk được dẫn → bỏ ca (lý do `no_prompt_full` / `evidence_parse_failed`), không đoán.
- **family**: CHỈ từ đầu vào bộ câu (`--questions`, `--from-run` + kịch bản, `--from-probe` + `families.jsonl`); thiếu → lỗi.
"""

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text

from app.eval.dbread import Reader
from app.eval.groundedness.models import AnswerRow

ANSWER_EVENT = "deflected_info_only"
CANNOT_EVENT = "cannot_answer"
EVIDENCE_MARK = "Bằng chứng:\n"
BLOCK_SEP = "\n\n"

# Lý do bỏ ca không làm hỏng lượt thu thập (đếm trong báo cáo); `SYSTEM_REASONS` làm lệnh thoát mã 3.
SYSTEM_REASONS = frozenset({"no_prompt_full", "evidence_parse_failed", "no_checkpoint", "no_answer_message"})


class CollectError(ValueError):
    """Đầu vào/DB sai hợp đồng của cả lượt (không phải của một ca) — thông điệp không có chữ người dùng."""


class Question(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    scenario_id: str = Field(min_length=1)
    family: str = Field(min_length=1, pattern=r"\S")  # BẮT BUỘC từ đầu vào bộ câu — không suy
    ticket_id: str = Field(min_length=1)


# ---- đầu vào bộ câu -----------------------------------------------------------------------------------------------------


def _jsonl(path: Path) -> list[tuple[int, Any]]:
    out: list[tuple[int, Any]] = []
    for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append((no, json.loads(line)))
            except ValueError:
                raise CollectError(f"{path.name}: dòng {no} không phải JSON") from None
    return out


def _question(path: Path, no: int, data: Mapping[str, Any]) -> Question:
    try:
        return Question.model_validate(data)
    except ValidationError as e:
        fields = sorted({".".join(str(p) for p in err["loc"]) or "(gốc)" for err in e.errors()})
        raise CollectError(f"{path.name}: dòng {no} sai hợp đồng ở {fields}") from None


def _unique(questions: Sequence[Question]) -> list[Question]:
    seen = Counter(q.scenario_id for q in questions)
    dup = sorted(k for k, n in seen.items() if n > 1)
    if dup:
        raise CollectError(f"scenario_id trùng ({len(dup)} id, đầu tiên: {dup[0]})")
    return list(questions)


def load_questions(path: Path) -> list[Question]:
    """`questions.jsonl`: `{scenario_id, family, ticket_id}` mỗi dòng (khoá lạ bị từ chối)."""
    rows = _jsonl(path)
    if not rows:
        raise CollectError(f"{path.name}: không có dòng nào")
    return _unique([_question(path, no, d if isinstance(d, dict) else {}) for no, d in rows])


def _families(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for no, d in _jsonl(path):
        sid, fam = (d.get("scenario_id"), d.get("family")) if isinstance(d, dict) else (None, None)
        if not isinstance(sid, str) or not sid or not isinstance(fam, str) or not fam.strip():
            raise CollectError(f"{path.name}: dòng {no} thiếu scenario_id/family")
        if sid in out:
            raise CollectError(f"{path.name}: scenario_id trùng ở dòng {no}")
        out[sid] = fam
    return out


def questions_from_probe(ket_qua: Path, families: Path) -> tuple[list[Question], dict[str, int]]:
    """`ket-qua.json` của `tests/probe/cong5.py` (`rows[]` có `id`, `ticket`) + `families.jsonl` → câu hỏi. Dòng không có ticket (chưa gửi
    được) bị bỏ + đếm; dòng CÓ ticket mà `families.jsonl` không có họ → LỖI (không suy)."""
    try:
        data = json.loads(ket_qua.read_text(encoding="utf-8"))
        rows = data["rows"]
    except (ValueError, KeyError, TypeError):
        raise CollectError(f"{ket_qua.name}: không đọc được rows[]") from None
    fam = _families(families)
    out: list[Question] = []
    no_ticket = 0
    missing: list[str] = []
    for r in rows:
        sid, ticket = r.get("id") if isinstance(r, dict) else None, r.get("ticket") if isinstance(r, dict) else None
        if not isinstance(sid, str):
            raise CollectError(f"{ket_qua.name}: có dòng rows[] không có id")
        if not ticket:
            no_ticket += 1
        elif sid not in fam:
            missing.append(sid)
        else:
            out.append(Question(scenario_id=sid, family=fam[sid], ticket_id=str(ticket)))
    if missing:
        raise CollectError(f"{families.name}: thiếu họ của {len(missing)} id có ticket (đầu tiên: {missing[0]}) — family bắt buộc, không suy")
    return _unique(out), {"no_ticket": no_ticket}


def questions_from_run(run_dir: Path, scenarios_dir: Path) -> tuple[list[Question], dict[str, int]]:
    """`outcomes.jsonl` của harness (scenario_id → ticket_id) + họ lấy từ khoá `family` trong YAML kịch bản (đọc nhẹ: chỉ `id`, `family`)."""
    fam: dict[str, str] = {}
    for path in sorted([*scenarios_dir.glob("*.yaml"), *scenarios_dir.glob("*.yml")]):
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            for item in doc if isinstance(doc, list) else [doc]:
                if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(item.get("family"), str) and item["family"].strip():
                    if item["id"] in fam:
                        raise CollectError(f"kịch bản trùng id trong {scenarios_dir.name}")
                    fam[item["id"]] = item["family"]
    out: list[Question] = []
    no_ticket = 0
    missing: list[str] = []
    for no, d in _jsonl(run_dir / "outcomes.jsonl"):
        sid, ticket = (d.get("scenario_id"), d.get("ticket_id")) if isinstance(d, dict) else (None, None)
        if not isinstance(sid, str):
            raise CollectError(f"outcomes.jsonl: dòng {no} không có scenario_id")
        if not ticket:
            no_ticket += 1
        elif sid not in fam:
            missing.append(sid)
        else:
            out.append(Question(scenario_id=sid, family=fam[sid], ticket_id=str(ticket)))
    if missing:
        raise CollectError(f"kịch bản thiếu `family` của {len(missing)} id có ticket (đầu tiên: {missing[0]}) — family bắt buộc, không suy")
    return _unique(out), {"no_ticket": no_ticket}


# ---- tách khối bằng chứng ------------------------------------------------------------------------------------------------


def parse_evidence(prompt_full: str, chunks: Sequence[Mapping[str, str]]) -> dict[str, str] | None:
    """`prompt_full` (JSON danh sách tin nhắn) → {chunk_id: văn bản khối}. `chunks` = top-5 theo thứ tự truy hồi, mỗi phần tử có
    `chunk_id`, `title`, `heading_path`. None nếu không tách được (JSON hỏng, không có tin `user`, không thấy khối nào)."""
    try:
        messages = json.loads(prompt_full)
        user = next(m["content"] for m in messages if m["role"] == "user")
    except (ValueError, KeyError, TypeError, StopIteration):
        return None
    headers = {c["chunk_id"]: f"[{c['chunk_id']}] {c['title']} › {c['heading_path']}\n" for c in chunks}
    # LẦN CUỐI mà "Bằng chứng:" đi liền tiêu đề một chunk = khối thật (câu hỏi nằm TRƯỚC khối bằng chứng và do người dùng gõ — có thể giả
    # cả dấu "Bằng chứng:" lẫn tiêu đề; chữ KB do nhóm soạn, không giả).
    start = max((user.rfind(EVIDENCE_MARK + h) for h in headers.values()), default=-1)
    if start == -1:
        return None
    body = user[start + len(EVIDENCE_MARK) :]
    at: dict[str, int] = {}
    for cid, header in headers.items():
        if body.startswith(header):
            at[cid] = 0
        elif (i := body.find(BLOCK_SEP + header)) != -1:
            at[cid] = i + len(BLOCK_SEP)
    found = sorted((pos, cid) for cid, pos in at.items())
    out: dict[str, str] = {}
    for i, (pos, cid) in enumerate(found):
        begin = pos + len(headers[cid])
        last = i + 1 == len(found)
        text_ = body[begin:] if last else body[begin : found[i + 1][0] - len(BLOCK_SEP)]
        out[cid] = text_.rstrip("\n") if last else text_
    return out or None


# ---- DB -------------------------------------------------------------------------------------------------------------------

_B10 = "SELECT event, detail->'cited' FROM audit_logs WHERE ticket_id = :t AND step = 'B10' ORDER BY log_id"
_CALLS = (
    "SELECT c.prompt_full, c.error FROM llm_calls c JOIN spans s ON s.span_id = c.span_id JOIN turns u ON u.turn_id = s.turn_id "
    "WHERE u.ticket_id = :t AND s.name = 'llm:b10_answer' ORDER BY c.call_id"
)
_TICKET = "SELECT created_at FROM tickets WHERE ticket_id = :t"


def _answer_text(state: Mapping[str, Any]) -> str | None:
    for msg in reversed(list(state.get("conversation") or [])):
        if isinstance(msg, dict) and msg.get("kind") == "answer" and isinstance(msg.get("text"), str):
            return str(msg["text"])
    return None


async def collect_one(reader: Reader, q: Question) -> tuple[dict[str, Any] | None, str]:
    """(dòng answers.jsonl | None, lý do). Lý do 'ok' khi có dòng."""
    async with reader.engine.connect() as conn:
        b10 = (await conn.execute(text(_B10), {"t": q.ticket_id})).all()
        if not b10:
            return None, "no_b10"
        event, cited = b10[-1]
        if event == CANNOT_EVENT:
            return AnswerRow(scenario_id=q.scenario_id, family=q.family, answer="", citations=(), chunks=(), cannot_answer=True).model_dump(mode="json"), "ok"
        if event != ANSWER_EVENT:
            return None, f"not_answered:{event}"
        calls = (await conn.execute(text(_CALLS), {"t": q.ticket_id})).all()
    good = [c for c in calls if c[1] is None]
    if not good or not good[-1][0]:
        return None, "no_prompt_full"
    state = await reader.state(q.ticket_id)
    if state is None:
        return None, "no_checkpoint"
    answer = _answer_text(state)
    if answer is None:
        return None, "no_answer_message"
    retrieved = [{"chunk_id": c.chunk_id, "doc_id": c.doc_id, "title": c.title, "heading_path": c.heading_path}
                 for c in state.get("retrieved") or []]  # fmt: skip
    blocks = parse_evidence(str(good[-1][0]), retrieved)
    citations = [str(c) for c in cited or []]
    if blocks is None or not set(citations) <= set(blocks):
        return None, "evidence_parse_failed"
    meta = {c["chunk_id"]: c for c in retrieved}
    row = AnswerRow.model_validate({
        "scenario_id": q.scenario_id, "family": q.family, "answer": answer, "citations": citations,
        "chunks": [{"chunk_id": cid, "text": t, "doc_id": meta[cid]["doc_id"], "title": meta[cid]["title"],
                    "heading_path": meta[cid]["heading_path"]} for cid, t in blocks.items()],
        "cannot_answer": False,
    })  # fmt: skip
    return row.model_dump(mode="json"), "ok"


async def collect(
    reader: Reader, questions: Sequence[Question], *, since: datetime | None = None, until: datetime | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Mọi ticket trong `questions` (tuần tự, thứ tự đầu vào). `since`/`until` lọc theo `tickets.created_at` (nửa mở [since, until))."""
    rows: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for q in questions:
        async with reader.engine.connect() as conn:
            created = (await conn.execute(text(_TICKET), {"t": q.ticket_id})).scalar_one_or_none()
        if created is None:
            skipped["ticket_not_found"] += 1
            continue
        if (since is not None and created < since) or (until is not None and created >= until):
            skipped["out_of_window"] += 1
            continue
        row, reason = await collect_one(reader, q)
        if row is None:
            skipped[reason] += 1
        else:
            rows.append(row)
    report = {
        "n_questions": len(questions), "n_collected": len(rows), "n_families": len({r["family"] for r in rows}),
        "n_cannot_answer": sum(1 for r in rows if r["cannot_answer"]), "skipped": dict(sorted(skipped.items())),
    }  # fmt: skip
    return rows, report


def has_system_skips(report: Mapping[str, Any]) -> bool:
    return any(k in SYSTEM_REASONS for k in report["skipped"])
