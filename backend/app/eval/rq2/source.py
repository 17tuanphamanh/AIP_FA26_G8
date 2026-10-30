"""Đầu vào B14 của lượt S1 (hybrid) — đọc lại từ DB, CHỈ ĐỌC (`Shell.sql`: transaction READ ONLY, `app/eval/stack.py`).

Nguồn (kiểm trên tag v1.0-freeze):
- `llm_calls.prompt_full` = `json.dumps(rendered.messages)`, chỉ ghi khi `EVAL_MODE=true` (`app/llm/client.py:213-214`), ghi TRƯỚC khi
  tra cache → lời gọi trúng cache vẫn có. Lá → dòng: `llm_calls.span_id → spans.turn_id → turns.ticket_id`. Lượt S1 chạy `sampling_k5`
  nên mỗi lá đi lớp LLM có đúng 5 dòng `prompt_id = 'b14_risk_vote'` (`sample_idx` 0…4), KHÔNG có dòng `b14_risk_estimate`.
- Số khối bằng chứng gateway cắt: `spans.attributes->>'trimmed_evidence'` (`client.py` `_record`). Khối đã cắt không còn trong
  `prompt_full` → không dựng lại được → loại.

Dựng biến (`rebuild`): template `user` của `b14_risk_estimate` là tiền tố đúng từng byte của template `user` của `b14_risk_vote` (vote
thêm dòng `sample_idx`). `intended_action`, `risk_context` render thành một dòng JSON (`_fmt`: sort_keys, gọn — `llm/context.py:81-86`)
→ `json.loads` lấy lại. `evidence` render thành `[id] title › heading\\ntext` nối bằng dòng trống, KHÔNG có `score`
(`llm/context.py:73-74`) → tách theo đầu khối; `score` chỉ dùng để chọn khối bị cắt (thấp nhất trước, hoà → khối sau) nên đặt bằng nhau
cho mọi khối: thứ tự cắt = khối cuối trước = đúng thứ tự gốc (estimator đã sắp giảm dần theo score, `estimator_vars`).
Kiểm byte: render lại `b14_risk_vote` từ biến đã dựng với từng `sample_idx` (hàm `render` của gateway, không gọi LLM) phải BẰNG `prompt_full`
của dòng đó, và không khối nào bị cắt. Lệch → `Rejected` (lá bị loại khỏi (a), đếm ở manifest), không đoán.
Tách khối chỉ mơ hồ khi chính đoạn trích chứa `\\n\\n[x] … › …\\n`; khi đó cách tách nào cũng render ra cùng byte; > `MAX_EVIDENCE` khối
→ loại (estimator không bao giờ gửi quá 3).
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.eval.stack import Sql, quote
from app.llm.context import EMPTY, render
from app.llm.registry import PLACEHOLDER, Prompt
from app.risk.estimator import MAX_EVIDENCE, K

VOTE_PROMPT: Final = "b14_risk_vote"
ESTIMATE_PROMPT: Final = "b14_risk_estimate"
B14_INPUT_METHOD: Final = "vote_prompt_full_reparse+rerender_check"
JSON_VARS: Final = frozenset({"intended_action", "risk_context"})
SAMPLE_VAR: Final = "sample_idx"
EVIDENCE_SCORE: Final = 1.0  # mọi khối bằng nhau — xem docstring

type RejectReason = Literal[
    "vote_calls_count", "vote_call_error", "prompt_full_missing", "mixed_target", "trimmed_evidence", "trimmed_unknown",
    "parse", "sample_idx", "too_many_evidence", "inconsistent_votes", "rerender_mismatch",
]  # fmt: skip

VOTE_FIELDS = ("'call_id', c.call_id, 'provider', c.provider, 'model', c.model, 'prompt_version', c.prompt_version, "
               "'prompt_full', c.prompt_full, 'error', c.error, 'trimmed_evidence', s.attributes->>'trimmed_evidence'")  # fmt: skip


class Rejected(Exception):
    """Lá không dựng lại được đầu vào B14 — `reason` là mã cố định, không chứa dữ liệu."""

    def __init__(self, reason: RejectReason) -> None:
        super().__init__(reason)
        self.reason: RejectReason = reason


@dataclass(frozen=True)
class VoteCall:
    """Một dòng `llm_calls` `b14_risk_vote` của lá."""

    call_id: int
    provider: str
    model: str
    prompt_version: str
    prompt_full: str | None
    error: str | None
    trimmed_evidence: int | None  # None = span không có khoá (không biết)

    @property
    def messages(self) -> list[dict[str, str]]:
        if self.prompt_full is None:
            raise Rejected("prompt_full_missing")
        return list(json.loads(self.prompt_full))


@dataclass(frozen=True)
class B14Input:
    ticket_id: str
    provider: str
    model: str
    variables: dict[str, Any]  # biến chung của B14 (không có `sample_idx`) — đầu vào `_self_report`
    messages: tuple[list[dict[str, str]], ...]  # messages của phiếu theo `sample_idx` 0…K-1


def fetch_vote_calls(sql: Sql, ticket_id: str) -> list[VoteCall]:
    rows = sql(
        f"SELECT coalesce(json_agg(json_build_object({VOTE_FIELDS}) ORDER BY c.call_id), '[]') "
        "FROM llm_calls c JOIN spans s ON s.span_id = c.span_id JOIN turns t ON t.turn_id = s.turn_id "
        f"WHERE t.ticket_id = {quote(ticket_id)} AND c.prompt_id = '{VOTE_PROMPT}'"
    )  # fmt: skip
    out = []
    for r in rows or []:
        trimmed = r["trimmed_evidence"]
        out.append(VoteCall(int(r["call_id"]), r["provider"], r["model"], r["prompt_version"], r["prompt_full"], r["error"],
                            None if trimmed is None else int(trimmed)))  # fmt: skip
    return out


def fetch_cache(sql: Sql, keys: Sequence[str]) -> dict[str, dict[str, Any]]:
    """`llm_cache.response_json` (mode `eval`, prompt vote) theo khoá; khoá không có dòng → vắng."""
    if not keys:
        return {}
    listed = ", ".join(quote(k) for k in keys)
    got = sql(
        "SELECT coalesce(json_object_agg(cache_key, response_json), '{}') FROM llm_cache "
        f"WHERE mode = 'eval' AND prompt_id = '{VOTE_PROMPT}' AND cache_key IN ({listed})"
    )  # fmt: skip
    return dict(got or {})


def _user_pattern(prompt: Prompt) -> re.Pattern[str]:
    parts: list[str] = []
    pos = 0
    for m in PLACEHOLDER.finditer(prompt.spec.user):
        parts.append(re.escape(prompt.spec.user[pos : m.start()]))
        name = m.group(1)
        if name in JSON_VARS:
            parts.append(f"(?P<{name}>[^\\n]*)")
        elif name == SAMPLE_VAR:
            parts.append(f"(?P<{name}>[0-9]+)")
        else:
            parts.append(f"(?P<{name}>.*?)")
        pos = m.end()
    parts.append(re.escape(prompt.spec.user[pos:]))
    return re.compile("".join(parts), re.DOTALL)


_HEADER = re.compile(r"(?:^|\n\n)\[(?P<id>[^\]\n]+)\] (?P<title>[^\n]*?) › (?P<head>[^\n]*)\n")


def parse_evidence(text: str) -> list[dict[str, Any]]:
    """Ngược của `llm/context._fmt_evidence`. Không có đầu khối ở vị trí 0 → `Rejected("parse")`."""
    if text == EMPTY:
        return []
    heads = list(_HEADER.finditer(text))
    if not heads or heads[0].start() != 0:
        raise Rejected("parse")
    blocks = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        blocks.append({"anchor_chunk_id": h["id"], "title": h["title"], "heading_path": h["head"], "text": text[h.end() : end],
                       "score": EVIDENCE_SCORE})  # fmt: skip
    return blocks


def parse_vote_user(prompt: Prompt, content: str) -> tuple[dict[str, Any], int]:
    """Tin `user` của một phiếu → (biến chung, `sample_idx`)."""
    m = _user_pattern(prompt).fullmatch(content)
    if m is None:
        raise Rejected("parse")
    try:
        variables: dict[str, Any] = {name: json.loads(m[name]) for name in JSON_VARS}
    except json.JSONDecodeError:
        raise Rejected("parse") from None
    variables["evidence"] = parse_evidence(m["evidence"])
    return variables, int(m[SAMPLE_VAR])


def sample_index(prompt: Prompt, call: VoteCall) -> int:
    """`sample_idx` của một dòng phiếu — chỉ khớp khuôn template, không dựng biến (cho (c): messages dùng NGUYÊN `prompt_full`)."""
    m = _user_pattern(prompt).fullmatch(_user(call.messages))
    if m is None:
        raise Rejected("parse")
    return int(m[SAMPLE_VAR])


def _user(messages: Sequence[Mapping[str, str]]) -> str:
    users = [m["content"] for m in messages if m.get("role") == "user"]
    if len(users) != 1:
        raise Rejected("parse")
    return users[0]


def rebuild(ticket_id: str, calls: Sequence[VoteCall], vote_prompt: Prompt, *, budget_in: int) -> B14Input:
    """5 dòng phiếu của một lá → biến B14 đã kiểm byte. Mọi lý do loại là `Rejected` (mã cố định)."""
    if len(calls) != K:
        raise Rejected("vote_calls_count")
    if any(c.error is not None for c in calls):
        raise Rejected("vote_call_error")
    if len({(c.provider, c.model, c.prompt_version) for c in calls}) != 1 or calls[0].prompt_version != vote_prompt.version:
        raise Rejected("mixed_target")
    if any(c.trimmed_evidence is None for c in calls):
        raise Rejected("trimmed_unknown")
    if any(c.trimmed_evidence for c in calls):
        raise Rejected("trimmed_evidence")
    by_idx: dict[int, VoteCall] = {}
    shared: dict[str, Any] | None = None
    for c in calls:
        variables, idx = parse_vote_user(vote_prompt, _user(c.messages))
        if idx in by_idx or not 0 <= idx < K:
            raise Rejected("sample_idx")
        if shared is None:
            shared = variables
        elif variables != shared:
            raise Rejected("inconsistent_votes")
        by_idx[idx] = c
    assert shared is not None
    if len(shared["evidence"]) > MAX_EVIDENCE:
        raise Rejected("too_many_evidence")
    for idx, c in by_idx.items():
        again = render(vote_prompt, {**shared, SAMPLE_VAR: idx}, budget_in=budget_in)
        if again.trimmed_evidence or json.dumps(again.messages, ensure_ascii=False) != c.prompt_full:
            raise Rejected("rerender_mismatch")
    return B14Input(ticket_id, calls[0].provider, calls[0].model, shared, tuple(by_idx[i].messages for i in range(K)))
