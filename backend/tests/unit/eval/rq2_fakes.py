"""Dữ liệu GIẢ cho test RQ2: biến B14, dòng phiếu S1 (`prompt_full` render bằng chính `render` của gateway), DB giả, phản hồi logprobs."""

import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.eval.rq2.source import VOTE_PROMPT, VoteCall
from app.eval.rq2.votes import vote_key
from app.llm.config import load_llm_config
from app.llm.context import render
from app.llm.registry import Prompt
from app.risk.estimator import K
from tests.fakes.llm import REPO_CONFIG, repo_registry

STRONG = load_llm_config(REPO_CONFIG / "llm.yaml").roles["strong"]
BUDGET_IN = STRONG.budget_in
MODEL = "deepseek-flash"
PROVIDER = "cloud_a"


def vote_prompt() -> Prompt:
    return repo_registry().get(VOTE_PROMPT)


def variables(evidence: Sequence[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    ev = [
        {"anchor_chunk_id": "kb-vpn-01#2", "title": "Quy định VPN", "heading_path": "Cấp quyền › Nhân viên mới",
         "text": "Nhân viên thử việc cần trưởng phòng duyệt.\nThời hạn tối đa 30 ngày.", "score": 0.91},
        {"anchor_chunk_id": "kb-vpn-02#1", "title": "Ngoài giờ", "heading_path": "Ngoại lệ",
         "text": "Ngoài giờ hành chính phải có người trực duyệt.", "score": 0.72},
    ] if evidence is None else list(evidence)  # fmt: skip
    return {
        "intended_action": {"type": "grant_vpn", "target": "user", "params": {"duration_days": 30}, "facts": {"in_catalog": True}},
        "risk_context": {"requester": {"role": "employee", "department": "IT", "employment_status": "probation",
                                       "tenure_days": 12, "is_privileged_account": False},
                         "within_business_hours": False, "target_is_other": False},
        "evidence": ev,
    }  # fmt: skip


def prompt_full(prompt: Prompt, vars_: Mapping[str, Any], *, budget_in: int = BUDGET_IN) -> str:
    return json.dumps(render(prompt, vars_, budget_in=budget_in).messages, ensure_ascii=False)


def vote_calls(vars_: Mapping[str, Any] | None = None, *, trimmed: int | None = 0, model: str = MODEL,
               order: Sequence[int] = (3, 0, 4, 1, 2)) -> list[VoteCall]:  # fmt: skip
    v = variables() if vars_ is None else dict(vars_)
    p = vote_prompt()
    return [VoteCall(100 + i, PROVIDER, model, p.version, prompt_full(p, {**v, "sample_idx": i}), None, trimmed) for i in order]


def cache_for(calls: Sequence[VoteCall], votes: Mapping[int, bool], *, model_version: str | None = None) -> dict[str, dict[str, Any]]:
    """`llm_cache` giả: phiếu theo `sample_idx`."""
    out = {}
    for c in calls:
        idx = int(re.search(r"số ([0-9]+)\.\n?$", c.messages[1]["content"]).group(1))  # type: ignore[union-attr]
        out[vote_key(c, model_version=model_version)] = {"needs_human": votes[idx], "factors": []}
    return out


class FakeSql:
    """`Sql` giả cho `fetch_vote_calls` / `fetch_cache`: trả theo loại câu; đếm số câu."""

    def __init__(self, calls_by_ticket: Mapping[str, Sequence[VoteCall]], cache: Mapping[str, Mapping[str, Any]]) -> None:
        self.calls_by_ticket = calls_by_ticket
        self.cache = cache
        self.queries: list[str] = []

    def __call__(self, query: str) -> Any:
        self.queries.append(query)
        if "FROM llm_cache" in query:
            keys = re.findall(r"'([0-9a-f]{64})'", query)
            return {k: dict(self.cache[k]) for k in keys if k in self.cache}
        ticket = re.search(r"t\.ticket_id = '([^']+)'", query).group(1)  # type: ignore[union-attr]
        return [{"call_id": c.call_id, "provider": c.provider, "model": c.model, "prompt_version": c.prompt_version,
                 "prompt_full": c.prompt_full, "error": c.error,
                 "trimmed_evidence": None if c.trimmed_evidence is None else str(c.trimmed_evidence)}
                for c in self.calls_by_ticket.get(ticket, [])]  # fmt: skip


def logprob_response(tokens: Sequence[tuple[str, Mapping[str, float]]], *, model: str = MODEL) -> dict[str, Any]:
    """`tokens` = (token đã chọn, {token thay thế: xác suất}) — logprob = ln(xác suất)."""
    content = []
    for tok, alts in tokens:
        top = [{"token": t, "logprob": math.log(p)} for t, p in alts.items()]
        chosen = alts.get(tok, 0.5)
        content.append({"token": tok, "logprob": math.log(chosen), "top_logprobs": top})
    text = "".join(t for t, _ in tokens)
    return {"model": model, "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                                         "logprobs": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 800, "completion_tokens": 20}}  # fmt: skip


def vote_tokens(p_true: float, *, chosen: str = " true") -> list[tuple[str, dict[str, float]]]:
    return [('{"', {'{"': 1.0}), ("needs", {"needs": 1.0}), ("_human", {"_human": 1.0}), ('":', {'":': 1.0}),
            (chosen, {" true": p_true, " false": round(1 - p_true - 0.01, 10), " tr": 0.01}), (",", {",": 1.0}),
            (' "factors": []}', {' "factors": []}': 1.0})]  # fmt: skip


class FakeTransport:
    def __init__(self, respond: Callable[[Mapping[str, Any]], dict[str, Any]]) -> None:
        self.respond = respond
        self.bodies: list[dict[str, Any]] = []

    async def post(self, body: Mapping[str, Any]) -> dict[str, Any]:
        self.bodies.append(dict(body))
        return self.respond(body)


assert K == 5
