"""`GET /api/tickets/{id}/trace` — "Nhật ký quyết định" của một ticket, CHỈ ĐỌC (L1, L2, Trưởng BP IT).

Thứ tự kiểm (khuôn `api/tickets.py`): 401 → `require("ticket:read:any")` (nhân viên → 403 + `permission_denied`) → không có
ticket → 404 → manager (`audit:read:all`) đọc mọi ticket; L1/L2 phải qua `can_read_ticket` — sai → CÙNG 404 với "không có"
(D-02, TC30) + `permission_denied`. Không ghi gì khác: không audit, không checkpoint, không gọi LLM.

Danh sách TRẮNG (`build_trace`, hàm thuần): mỗi bước chỉ `step`, `event`, `at` + đúng các trường dưới, đọc từ cột audit hoặc khoá
`detail` đã biết tên. Không bao giờ trả `redacted_request`, `query`, `note`, `reason`, prompt, tham số hành động, traceback hay
`detail` thô. Mọi chuỗi lấy từ audit phải là định danh (`_IDENT`) — chuỗi lạ (câu chữ) bị bỏ, không cắt bớt. Xác suất làm tròn 2 số;
ngoài [0, 1] hoặc không phải số → bỏ. Trường thiếu → None / rỗng, không lỗi.
- B2: lớp chặn (`regex` | `model` | `llm`), `p_injection` (L3), `decision` (theo `event`).
- B3/B4/B5: intent + confidence của LLM, `model_probs` (nhãn → p), `model_version`, `is_multi`.
- B6/B7: tên khoá `facts` (không giá trị).
- B10: `doc_id` + tiêu đề (`kb_documents`) của chunk đã trích dẫn (`detail.cited` = `<doc_id>#v<version>#<seq>`).
- B13/B14 (B12): `rule_id`, `policy_decision`, `risk_level`, `decided_by`, `raw_prob`, `calibrated_prob`; mô tả luật lấy từ
  `config/policy.json` theo `rule_id` (không từ cột `reason` — ca LLM cột đó có chữ của mô hình). `matched_rules` (mọi luật khớp,
  `api/matched_rules.py` — chung với màn duyệt): dòng không có `detail.all_matched` dạng list → BỎ khoá (`response_model_exclude_unset`;
  mọi trường khác luôn được gán tường minh nên không bị bỏ).
- B15/B16: phiếu duyệt — người duyệt (id + họ tên từ `users`), kết quả, thời điểm (bảng `approvals`).
- B17/B18: loại hành động (`intended_action.type` — SQL chỉ chọn khoá này), kết quả từng lời gọi ghi, trạng thái hoàn tác.
- B20: `route` (= `resolution_path`), `exit_code`. Dòng `escalation_closed` (L2 đóng ca, `db/escalations.close_audit_row`) thêm
  `close_result` ∈ {completed, confirmed_denial, reopened_as_new} lấy từ `detail.close_result` (giá trị lạ → null); KHÔNG `closed_by`,
  ghi chú hay độ dài ghi chú. Dòng B20 khác không gán khoá này → route bỏ khoá (`response_model_exclude_unset`).
Ticket cha (`is_parent`): kèm danh sách con (id, intent, exit_code).
"""

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.alerts import ErrorDetail
from app.api.matched_rules import MatchedRule, RuleRef, matched_rules, rule_index
from app.auth.authz import can_read_ticket
from app.auth.deps import deny, require
from app.auth.models import Principal
from app.db.escalations import CLOSE_EVENT
from app.domain.escalation_close import CLOSE_RESULT_VALUES, CloseResult

router = APIRouter()

NOT_FOUND = "not_found"
_IDENT = re.compile(r"[A-Za-z0-9_.:@/+-]{1,64}")
_CHUNK = re.compile(r"(?P<doc>[A-Za-z0-9_.:@/+-]{1,64})#v(?P<ver>[0-9]{1,9})#[0-9]{1,9}")
_LAYER: dict[str, Literal["regex", "model", "llm"]] = {"regex": "regex", "classifier": "model", "llm": "llm"}
type ScreenDecision = Literal["safe", "attack", "suspected", "unavailable"]
_SCREEN: dict[str, ScreenDecision] = {
    "screened": "safe", "injection_detected": "attack", "injection_suspected": "suspected",
    "guard_unavailable": "unavailable", "turn_budget_exceeded": "unavailable",
}  # fmt: skip
type ApprovalResult = Literal["pending", "approved", "rejected", "timeout"]
_APPROVAL_RESULTS: dict[Any, ApprovalResult] = {"approved": "approved", "rejected": "rejected", "timeout": "timeout"}
_CLASSIFY_STEPS = frozenset({"B3", "B4", "B5"})
_DIAGNOSE_STEPS = frozenset({"B6", "B7"})
_POLICY_STEP = "B13/B14"
_EXECUTE_STEPS = frozenset({"B17", "B18"})


# ---- nguồn dữ liệu ------------------------------------------------------------------------------


@dataclass(frozen=True)
class TicketHead:
    """Phần dòng `tickets` cần cho quyền (`can_read_ticket` chỉ đọc `requester_id`) và đầu trang."""

    ticket_id: str
    requester_id: str
    parent_ticket_id: str | None
    is_parent: bool


@dataclass(frozen=True)
class TraceData:
    """Dữ liệu thô ĐÃ chọn cột của một ticket — `audit` mỗi dòng là cột `audit_logs` (+ `intended_action` chỉ có `type`)."""

    ticket: TicketHead
    audit: Sequence[Mapping[str, Any]]
    approvals: Sequence[Mapping[str, Any]] = ()  # approval_id, approver_id, decided_by, status, decided_at, created_at
    children: Sequence[Mapping[str, Any]] = ()  # ticket_id, intent, exit_code
    kb_titles: Mapping[tuple[str, int], str] = field(default_factory=dict)
    names: Mapping[str, str] = field(default_factory=dict)  # user_id → họ tên


class TraceSource(Protocol):
    async def head(self, ticket_id: str) -> TicketHead | None: ...

    async def load(self, ticket: TicketHead) -> TraceData: ...


def cited_docs(audit: Iterable[Mapping[str, Any]]) -> list[tuple[str, int]]:
    """(doc_id, version) của chunk B10 đã trích dẫn, giữ thứ tự, không lặp. Chunk id sai mẫu → bỏ."""
    out: dict[tuple[str, int], None] = {}
    for row in audit:
        if row.get("step") != "B10":
            continue
        cited = _detail(row).get("cited")
        for cid in cited if isinstance(cited, list) else ():
            if isinstance(cid, str) and (m := _CHUNK.fullmatch(cid)):
                out[(m["doc"], int(m["ver"]))] = None
    return list(out)


_HEAD = text("SELECT ticket_id, requester_id, parent_ticket_id, is_parent FROM tickets WHERE ticket_id = :tid")
# `intended_action` chỉ lấy khoá `type` — tham số hành động không bao giờ rời DB qua route này.
_AUDIT = text(
    "SELECT log_id, created_at, step, event, intent, confidence, decided_by, policy_decision, risk_level, matched_rule_id, "
    "raw_prob, calibrated_prob, approver_id, approval_result, exit_code, "
    "CASE WHEN intended_action IS NULL THEN NULL ELSE jsonb_build_object('type', intended_action -> 'type') END "
    "AS intended_action, detail "
    "FROM audit_logs WHERE ticket_id = :tid ORDER BY created_at, log_id"
)
_APPROVALS = text(
    "SELECT approval_id, approver_id, decided_by, status, decided_at, created_at FROM approvals "
    "WHERE ticket_id = :tid ORDER BY created_at, approval_id"
)
_CHILDREN = text(
    "SELECT ticket_id, intent, exit_code FROM tickets WHERE parent_ticket_id = :tid ORDER BY created_at, ticket_id"
)
_TITLES = text(
    "SELECT doc_id, version, title FROM kb_documents WHERE (doc_id || '#' || version::text) IN :keys"
).bindparams(bindparam("keys", expanding=True))
_NAMES = text("SELECT user_id, full_name FROM users WHERE user_id IN :ids").bindparams(bindparam("ids", expanding=True))


class SqlTraceSource:
    """Đọc bằng `engines.main` trong MỘT giao dịch `REPEATABLE READ, READ ONLY` — chỉ SELECT."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def head(self, ticket_id: str) -> TicketHead | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(_HEAD, {"tid": ticket_id})).mappings().first()
        return TicketHead(**row) if row is not None else None

    async def load(self, ticket: TicketHead) -> TraceData:
        tid = {"tid": ticket.ticket_id}
        async with self._engine.connect() as conn:
            await conn.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
            async with conn.begin():
                audit = [dict(r) for r in (await conn.execute(_AUDIT, tid)).mappings()]
                approvals = [dict(r) for r in (await conn.execute(_APPROVALS, tid)).mappings()]
                children = [dict(r) for r in (await conn.execute(_CHILDREN, tid)).mappings()] if ticket.is_parent else []
                titles: dict[tuple[str, int], str] = {}
                if docs := cited_docs(audit):
                    keys = [f"{d}#{v}" for d, v in docs]
                    for r in (await conn.execute(_TITLES, {"keys": keys})).mappings():
                        titles[(r["doc_id"], r["version"])] = r["title"]
                names: dict[str, str] = {}
                if ids := sorted(_people(audit, approvals)):
                    for r in (await conn.execute(_NAMES, {"ids": ids})).mappings():
                        if r["full_name"]:
                            names[r["user_id"]] = r["full_name"]
        return TraceData(ticket, audit, approvals, children, titles, names)


def _people(audit: Iterable[Mapping[str, Any]], approvals: Iterable[Mapping[str, Any]]) -> set[str]:
    ids = {r.get("approver_id") for r in audit if r.get("step") in ("B15", "B16")}
    ids |= {r.get(k) for r in approvals for k in ("approver_id", "decided_by")}
    return {i for i in ids if isinstance(i, str) and i}


def get_trace_source(request: Request) -> TraceSource:
    source: TraceSource | None = getattr(request.app.state, "trace", None)
    if source is None:
        raise HTTPException(503, "trace_unavailable")
    return source


# ---- thân trả về (response_model — FE sinh kiểu) ------------------------------------------------


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScreenInfo(_Strict):
    layer: Literal["regex", "model", "llm"] | None
    p_injection: float | None
    decision: ScreenDecision | None


class ClassifyInfo(_Strict):
    intent: str | None
    confidence: float | None
    model_probs: dict[str, float] | None
    model_version: str | None
    is_multi: bool | None


class DiagnoseInfo(_Strict):
    fact_keys: list[str]


class KbSource(_Strict):
    doc_id: str
    title: str | None


class PolicyInfo(_Strict):
    rule_id: str | None
    rule_description: str | None
    policy_decision: str | None
    risk_level: str | None
    decided_by: Literal["rule", "llm"] | None
    raw_prob: float | None
    calibrated_prob: float | None
    matched_rules: list[MatchedRule] | None = None  # chỉ gán khi dòng có `all_matched`; không gán → route bỏ khoá


class ApprovalInfo(_Strict):
    approver_id: str | None
    approver_name: str | None
    result: ApprovalResult | None
    at: datetime | None


class ExecCall(_Strict):
    name: str
    result: Literal["ok", "failed"]


class ExecutionInfo(_Strict):
    action: str | None
    success: bool | None
    rollback_status: str | None
    calls: list[ExecCall]


class OutcomeInfo(_Strict):
    route: str | None
    exit_code: str | None
    close_result: CloseResult | None = None  # chỉ gán ở dòng `escalation_closed`; không gán → route bỏ khoá


class TraceStep(_Strict):
    step: str
    event: str
    at: datetime
    screen: ScreenInfo | None
    classify: ClassifyInfo | None
    diagnose: DiagnoseInfo | None
    sources: list[KbSource] | None
    policy: PolicyInfo | None
    approval: ApprovalInfo | None
    execution: ExecutionInfo | None
    outcome: OutcomeInfo | None


class TraceChild(_Strict):
    ticket_id: str
    intent: str | None
    exit_code: str | None


class TicketTrace(_Strict):
    ticket_id: str
    is_parent: bool
    parent_ticket_id: str | None
    steps: list[TraceStep]
    children: list[TraceChild]


# ---- danh sách trắng (thuần) --------------------------------------------------------------------


def _detail(row: Mapping[str, Any]) -> Mapping[str, Any]:
    d = row.get("detail")
    return d if isinstance(d, Mapping) else {}


def _ident(value: Any) -> str | None:
    return value if isinstance(value, str) and _IDENT.fullmatch(value) else None


def _prob(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    p = float(value)
    return round(p, 2) if math.isfinite(p) and 0.0 <= p <= 1.0 else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _screen(row: Mapping[str, Any]) -> ScreenInfo:
    d = _detail(row)
    s = d.get("screening")
    s = s if isinstance(s, Mapping) else d  # nhánh `guard_unavailable` ghi `p_mal` thẳng ở `detail`
    layer = s.get("layer_decided")
    return ScreenInfo(
        layer=_LAYER.get(layer) if isinstance(layer, str) else None, p_injection=_prob(s.get("p_mal")),
        decision=_SCREEN.get(row["event"]),
    )  # fmt: skip


def _classify(row: Mapping[str, Any]) -> ClassifyInfo:
    d = _detail(row)
    raw = d.get("model_probs")
    probs = None
    if isinstance(raw, Mapping):
        probs = {k: p for k, v in raw.items() if _ident(k) is not None and (p := _prob(v)) is not None}
    return ClassifyInfo(
        intent=_ident(d.get("intent")) or _ident(row.get("intent")),
        confidence=_prob(d["confidence"] if d.get("confidence") is not None else row.get("confidence")),
        model_probs=probs, model_version=_ident(d.get("model_version")), is_multi=_bool(d.get("is_multi")),
    )  # fmt: skip


def _diagnose(row: Mapping[str, Any]) -> DiagnoseInfo:
    facts = _detail(row).get("facts")
    keys = [k for k in facts if _ident(k) is not None] if isinstance(facts, Mapping) else []
    return DiagnoseInfo(fact_keys=sorted(keys))


def _sources(row: Mapping[str, Any], titles: Mapping[tuple[str, int], str]) -> list[KbSource]:
    out: dict[str, KbSource] = {}
    for doc, ver in cited_docs([row]):
        if doc not in out:
            out[doc] = KbSource(doc_id=doc, title=titles.get((doc, ver)))
    return list(out.values())


def _policy(row: Mapping[str, Any], rules: Mapping[str, RuleRef]) -> PolicyInfo:
    rule_id = _ident(row.get("matched_rule_id"))
    decided_by = row.get("decided_by")
    ref = rules.get(rule_id) if rule_id else None
    matched = matched_rules(_detail(row).get("all_matched"), rule_id, rules)
    return PolicyInfo(
        rule_id=rule_id, rule_description=ref.description if ref else None,
        policy_decision=_ident(row.get("policy_decision")), risk_level=_ident(row.get("risk_level")),
        decided_by=decided_by if decided_by in ("rule", "llm") else None,
        raw_prob=_prob(row.get("raw_prob")), calibrated_prob=_prob(row.get("calibrated_prob")),
        **({"matched_rules": matched} if matched is not None else {}),
    )  # fmt: skip


def _approval(row: Mapping[str, Any], ticket: Mapping[str, Any] | None, names: Mapping[str, str]) -> ApprovalInfo:
    t = ticket or {}
    result: ApprovalResult | None
    if row["step"] == "B15":
        who, result, at = _ident(row.get("approver_id")) or _ident(t.get("approver_id")), "pending", row.get("created_at")
    else:
        result = _APPROVAL_RESULTS.get(row.get("approval_result"))
        who = _ident(t.get("decided_by")) or _ident(t.get("approver_id")) or _ident(row.get("approver_id"))
        at = t.get("decided_at") or row.get("created_at")
    return ApprovalInfo(
        approver_id=who, approver_name=names.get(who) if who else None, result=result,
        at=at if isinstance(at, datetime) else None,
    )  # fmt: skip


def _execution(row: Mapping[str, Any], action: str | None) -> ExecutionInfo:
    d = _detail(row)
    done = d.get("steps_done")
    calls = [ExecCall(name=n, result="ok") for s in (done if isinstance(done, list) else ()) if (n := _ident(s))]
    if (failed := _ident(d.get("failed_step"))) is not None:
        calls.append(ExecCall(name=failed, result="failed"))
    return ExecutionInfo(
        action=action, success=_bool(d.get("success")), rollback_status=_ident(d.get("rollback_status")), calls=calls,
    )  # fmt: skip


def _action_type(row: Mapping[str, Any]) -> str | None:
    a = row.get("intended_action")
    return _ident(a.get("type")) if isinstance(a, Mapping) else None


_CLOSE_RESULTS: dict[str, CloseResult] = {v: v for v in CLOSE_RESULT_VALUES}


def _outcome(row: Mapping[str, Any], event: str) -> OutcomeInfo:
    d = _detail(row)
    route, exit_code = _ident(d.get("resolution_path")), _ident(row.get("exit_code"))
    if event != CLOSE_EVENT:
        return OutcomeInfo(route=route, exit_code=exit_code)
    raw = d.get("close_result")
    return OutcomeInfo(route=route, exit_code=exit_code, close_result=_CLOSE_RESULTS.get(raw) if isinstance(raw, str) else None)


_EMPTY: dict[str, None] = dict.fromkeys(
    ("screen", "classify", "diagnose", "sources", "policy", "approval", "execution", "outcome")
)


def build_trace(data: TraceData, rules: Mapping[str, RuleRef] | None = None) -> TicketTrace:
    rules = rule_index() if rules is None else rules
    rows = sorted(data.audit, key=lambda r: (r["created_at"], r.get("log_id") or 0))
    approvals = list(data.approvals)
    queued = -1  # chỉ số phiếu của lần B15 gần nhất — B16 sau đó nói về phiếu này
    action: str | None = None
    steps: list[TraceStep] = []
    for row in rows:
        step, event = str(row["step"]), str(row["event"])
        action = _action_type(row) or action
        extra: dict[str, Any] = {}
        if step == "B2":
            extra["screen"] = _screen(row)
        elif step in _CLASSIFY_STEPS:
            extra["classify"] = _classify(row)
        elif step in _DIAGNOSE_STEPS:
            extra["diagnose"] = _diagnose(row)
        elif step == "B10":
            extra["sources"] = _sources(row, data.kb_titles)
        elif step == _POLICY_STEP:
            extra["policy"] = _policy(row, rules)
        elif step in ("B15", "B16"):
            if step == "B15":
                queued = min(queued + 1, len(approvals) - 1)
            ticket = approvals[queued] if 0 <= queued < len(approvals) else (approvals[-1] if approvals else None)
            extra["approval"] = _approval(row, ticket, data.names)
        elif step in _EXECUTE_STEPS:
            extra["execution"] = _execution(row, action)
        elif step == "B20":
            extra["outcome"] = _outcome(row, event)
        steps.append(TraceStep(
            step=_ident(step) or "?", event=_ident(event) or "?", at=row["created_at"], **{**_EMPTY, **extra},
        ))  # fmt: skip
    children = [
        TraceChild(ticket_id=c["ticket_id"], intent=_ident(c.get("intent")), exit_code=_ident(c.get("exit_code")))
        for c in data.children
    ]
    t = data.ticket
    return TicketTrace(
        ticket_id=t.ticket_id, is_parent=t.is_parent, parent_ticket_id=t.parent_ticket_id, steps=steps, children=children,
    )  # fmt: skip


READ_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 404: {"model": ErrorDetail}, 503: {"model": ErrorDetail},
}  # fmt: skip


@router.get(
    "/api/tickets/{ticket_id}/trace", response_model=TicketTrace, responses=READ_ERRORS, response_model_exclude_unset=True,
)
async def ticket_trace(
    ticket_id: str,
    request: Request,
    p: Annotated[Principal, Depends(require("ticket:read:any"))],
    source: Annotated[TraceSource, Depends(get_trace_source)],
) -> TicketTrace:
    head = await source.head(ticket_id)
    if head is None:
        raise HTTPException(404, NOT_FOUND)
    if not p.has("audit:read:all") and not can_read_ticket(p, head):
        await deny(request, p, "ticket:read:any", ticket_id=ticket_id)
        raise HTTPException(404, NOT_FOUND)
    return build_trace(await source.load(head))
