"""Stack giả cho test harness G2 — không Docker.

`FakeDb` là callable `sql(query)` thay `Shell.sql`: đọc ĐÚNG câu SQL harness phát ra (lọc `ticket_id = '…'`, `step = '…'`, chiếu các
cặp `'khoá', biểu_thức` của `json_build_object`) trên bảng trong bộ nhớ, và ghi lại mọi câu (`queries`) để test soát (chỉ đọc, khoá
`detail` được phép). `detail->>'k'` trả CHUỖI như Postgres (`->>` ra text). Câu lạ → `AssertionError` (không trả bừa).

`FakeApi` = `httpx.MockTransport` ghi lại mọi request; route nào test cần thì đặt handler.
"""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

# ---- kịch bản tổng hợp theo CẤU TRÚC THẬT (g2-chot.md:11-17 — chỉ tên trường + kiểu) -----------------------------------

SEED_USERS: Mapping[str, str] = {"u_sentinel": "SENTINEL_USER", "u_an": "an.nv", "u_ha": "ha.lt"}  # user_id → username


def reply(text: str, slot: str = "device_id") -> dict[str, Any]:
    return {"on_question_about": slot, "reply": text}


def confirm(value: bool = True) -> dict[str, Any]:
    return {"on_confirm": value}


def real_scenario(sid: str = "SENTINEL_ID_1", *, family: str | None = None, user_id: str = "u_sentinel",
                  turns: Sequence[Any] | None = None, expected_route: str | None = None, decision: str | None = "approve",
                  intents: Sequence[str] = ("vpn",), gold_doc_ids: Sequence[str] = ("SENTINEL_DOC",),
                  drop_action: Sequence[str] = (), **gold_over: Any) -> dict[str, Any]:  # fmt: skip
    """Một kịch bản tổng hợp đủ khoá thật; mọi giá trị chữ có chuỗi canh `SENTINEL_`. Mặc định `expected_route = None` (chưa
    nhãn — như dữ liệu thật tới 25/10). `drop_action`: bỏ khoá khỏi `gold.action` (dữ liệu thật thiếu `requested_for`/`params`)."""
    gold: dict[str, Any] = {
        "intents": list(intents), "need_type": "SENTINEL_NEED", "expected_route": expected_route, "expected_exit": None,
        "approver_decision": decision, "gold_doc_ids": list(gold_doc_ids),
        "action": {"type": "SENTINEL_ACT", "target": "SENTINEL_TGT", "requested_for": "SENTINEL_FOR",
                   "params": {"p": "SENTINEL_P", "n": 1}},
        "facts": {"f": "SENTINEL_FACT", "b": True},
    }  # fmt: skip
    for key in drop_action:
        del gold["action"][key]
    gold.update(gold_over)
    return {
        "id": sid, "family": family or f"SENTINEL_FAM_{sid}", "source": "SENTINEL_SRC", "at": "2026-10-20T09:00:00+07:00",
        "faults": [], "requester": {"user_id": user_id, "role": "employee", "dept": "SENTINEL_DEPT", "tenure_days": 400},
        "turns": list(turns) if turns is not None else ["SENTINEL_TXT_mo dau"], "gold": gold,
        "labels": {"annotator_1": None, "annotator_2": None},
    }  # fmt: skip


def write_seed(path: Path, users: Mapping[str, str] = SEED_USERS) -> Path:
    """Seed tổng hợp cùng dạng `mock_services/seed.json` (`users[*].user_id`, `users[*].username`)."""
    path.write_text(json.dumps({"users": [{"user_id": u, "username": n} for u, n in users.items()]}), encoding="utf-8")
    return path


_TID = re.compile(r"ticket_id = '([^']+)'")
_STEP = re.compile(r"step = '([^']+)'")
_PAIR = re.compile(r"'(\w+)',\s*(detail->>'\w+'|\w+)")
_USER = re.compile(r"user_id = '([^']+)'")
_TO_JSON = re.compile(r"SELECT to_json\((\w+)\) FROM tickets")


@dataclass
class FakeDb:
    tickets: dict[str, dict[str, Any]] = field(default_factory=dict)
    audit: list[dict[str, Any]] = field(default_factory=list)
    approvals: list[dict[str, Any]] = field(default_factory=list)
    users: dict[str, str] = field(default_factory=dict)  # user_id → username
    turns: dict[str, list[bool]] = field(default_factory=dict)  # ticket_id → [đã đóng?]
    queries: list[str] = field(default_factory=list)

    # -- dựng dữ liệu --
    def add_ticket(self, ticket_id: str, **cols: Any) -> None:
        row: dict[str, Any] = {"ticket_id": ticket_id, "parent_ticket_id": None, "is_parent": False, "intent": None,
                               "final_state": None, "exit_code": None, "close_reason": None, "resolution_path": None,
                               "requester_id": "u_requester"}  # fmt: skip
        row.update(cols)
        self.tickets[ticket_id] = row

    def log(self, ticket_id: str, step: str, event: str, detail: dict[str, Any] | None = None, **cols: Any) -> None:
        row: dict[str, Any] = {"ticket_id": ticket_id, "step": step, "event": event, "detail": detail or {},
                               "decided_by": None, "raw_prob": None, "calibrated_prob": None, "p_method": None,
                               "doc_ids": None, "created_at": f"2026-10-19T10:00:{len(self.audit):02d}+07:00",
                               "log_id": len(self.audit) + 1}  # fmt: skip
        row.update(cols)
        self.audit.append(row)

    # -- trả lời SQL --
    def __call__(self, query: str) -> Any:
        self.queries.append(query)
        tid = m.group(1) if (m := _TID.search(query)) else None
        if "FROM audit_logs" in query:
            step = _STEP.search(query)
            assert step is not None, "câu audit_logs phải lọc step"
            rows = sorted((r for r in self.audit if r["ticket_id"] == tid and r["step"] == step.group(1)),
                          key=lambda r: r["log_id"])  # fmt: skip
            return [self._project(query, r) for r in rows]
        if "FROM turns" in query:
            closed = self.turns.get(tid or "", [])
            return {"n": len(closed), "open": sum(1 for c in closed if not c)}
        if "to_json(EXISTS" in query and "FROM approvals" in query:
            return any(a["ticket_id"] == tid for a in self.approvals)
        if "FROM approvals" in query and "status = 'pending'" in query:
            pend = [a for a in self.approvals if a["ticket_id"] == tid and a["status"] == "pending"]
            return None if not pend else {"approval_id": pend[-1]["approval_id"], "approver_id": pend[-1]["approver_id"]}
        if "FROM users" in query:
            uid = _USER.search(query)
            assert uid is not None
            return self.users.get(uid.group(1))
        if "FROM tickets" in query:
            row = self.tickets.get(tid or "")
            if row is not None and (col := _TO_JSON.search(query)):
                return row[col.group(1)]
            return None if row is None else self._project(query, row)
        raise AssertionError("FakeDb: câu SQL lạ")

    @staticmethod
    def _project(query: str, row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, expr in _PAIR.findall(query):
            if expr.startswith("detail->>"):
                v = (row.get("detail") or {}).get(expr.split("'")[1])
                out[key] = None if v is None else (v if isinstance(v, str) else json.dumps(v))
            else:
                out[key] = row[expr]
        return out


type Handler = Callable[[httpx.Request], httpx.Response]


@dataclass
class FakeApi:
    """Ghi lại `(method, path, json)` của MỌI request (cả route không có handler); không handler → `fallback`, không có → 599."""

    routes: dict[tuple[str, str], Handler] = field(default_factory=dict)
    calls: list[tuple[str, str, Any]] = field(default_factory=list)
    fallback: Handler | None = None

    def on(self, method: str, path: str, handler: Handler) -> None:
        self.routes[(method, path)] = handler

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.calls.append((request.method, request.url.path, body))
        handler = self.routes.get((request.method, request.url.path)) or self.fallback
        return handler(request) if handler else httpx.Response(599)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://127.0.0.1:8000", transport=httpx.MockTransport(self.handle))


def login_ok(token: str = "tok") -> Handler:
    return lambda request: httpx.Response(200, json={"access_token": token})


def accepted(**body: Any) -> Handler:
    return lambda request: httpx.Response(202, json=body)


@dataclass
class FakeClock:
    now: float = 0.0
    slept: list[float] = field(default_factory=list)

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


# ---- stack giả đủ luồng cho runner ------------------------------------------------------------------------------------

_FLOW = re.compile(r"flow=(\w+)")
_TICKET_PATH = re.compile(r"^/api/tickets/([^/]+)(/messages|/confirm)?$")
_DECISION_PATH = re.compile(r"^/api/approvals/([^/]+)/decision$")
APPROVER_ID, APPROVER = "l1_01", "ha.lt"
GIT_SHA = "c0ffee" + "0" * 34


@dataclass
class SimStack:
    """Backend + DB giả: luồng của ticket chọn theo `flow=<tên>` trong câu đầu (kịch bản tổng hợp). Mỗi hành động thêm một lượt
    ĐÃ đóng → `wait_turn_closed` qua ngay. Luồng:

    direct (rule AUTO, đóng ngay) · clarify (hỏi → trả lời → chờ duyệt → duyệt → xác nhận → đóng) · reject (chờ duyệt → từ chối) ·
    ignore (chờ duyệt; đồng hồ giả qua `sla_s` → worker E6) · stuck (hỏi lại, không bao giờ đóng) · multi (ticket cha, chờ reply) ·
    badstrategy / nostrategy (log 4 strategy sai / thiếu) · calib (log 4 có calibrated_prob) · boom (POST /api/tickets → 500).

    Người quyết phiếu phải là người được giao (`ha.lt`) — khác → 403 (như `approval_role`)."""

    clock: FakeClock
    password: str = "SENTINEL_PW"
    sla_s: float = 10.0
    info_over: dict[str, Any] = field(default_factory=dict)
    app_env_value: str | None = "dev"
    health_runtime: str = "up"
    warmup_fails: bool = False
    login_status: int | None = None  # đặt → MỌI lần đăng nhập trả mã này (giả lỗi khác 401)
    login_network_error: bool = False  # True → đăng nhập ném httpx.ConnectError
    db: FakeDb = field(default_factory=FakeDb)
    api: FakeApi = field(default_factory=FakeApi)
    tokens: dict[str, str] = field(default_factory=dict)
    flows: dict[str, str] = field(default_factory=dict)
    waiting: dict[str, str | None] = field(default_factory=dict)
    created_at: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.db.users[APPROVER_ID] = APPROVER
        self.api.fallback = self._route

    # -- phía compose / container --
    def app_env(self) -> str | None:
        return self.app_env_value

    def info(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "app_env": "dev", "strategy": "hybrid", "eval_mode": True, "llm_cache_mode": "eval",
            "enable_proactive_diagnosis": True, "b2_classifier_mode": "shadow", "approval_sla_minutes_dev": 2,
            "llm_backend": "scripted", "fast_model": "m-fast", "strong_model": "m-strong", "app_git_sha": GIT_SHA,
            "rag_rerank_k": 20, "policy_sha256": "ab" * 32,
        }  # fmt: skip
        base.update(self.info_over)
        return base

    def warmup(self, rounds: int) -> dict[str, Any]:
        self.api.calls.append(("EXEC", "warmup", rounds))
        if self.warmup_fails:
            from app.eval.stack import StackError

            raise StackError("warmup lỗi")
        return {"rounds": rounds, "first_ms": 120, "last_ms": 40}

    def sql(self, query: str) -> Any:
        return self.db(query)

    def client(self) -> httpx.Client:
        return self.api.client()

    # -- phía HTTP --
    def _user(self, request: httpx.Request) -> str | None:
        return self.tokens.get(request.headers.get("Authorization", ""))

    def _turn(self, tid: str) -> None:
        self.db.turns.setdefault(tid, []).append(True)

    def _close(self, tid: str, final: str, resolution: str, close: str | None = None, exit_code: str | None = None) -> None:
        self.db.tickets[tid].update(final_state=final, resolution_path=resolution, close_reason=close, exit_code=exit_code)
        self.waiting[tid] = None

    def _log4(self, tid: str, route: str, strategy: str | None = "hybrid", **cols: Any) -> None:
        detail: dict[str, Any] = {"route": route, "factors": {"SENTINEL_FACTOR": 1}}
        if strategy is not None:
            detail["strategy"] = strategy
        base: dict[str, Any] = {"decided_by": "llm", "raw_prob": 0.4, "p_method": "self_report"}
        base.update(cols)
        self.db.log(tid, "B13/B14", "risk_decided", detail, **base)

    def _approval(self, tid: str) -> None:
        self._log4(tid, "HITL")
        self.db.approvals.append({"ticket_id": tid, "approval_id": f"A-{tid}", "approver_id": APPROVER_ID, "status": "pending"})
        self.waiting[tid] = "approval"

    def _create(self, tid: str, flow: str, requester: str) -> None:
        self.db.add_ticket(tid, intent="vpn", requester_id=next(u for u, n in self.db.users.items() if n == requester))
        self.db.log(tid, "B8", "retrieved", doc_ids=["SENTINEL_DOC_ret"])
        self.waiting[tid] = None
        if flow in ("direct", "badstrategy", "nostrategy", "calib"):
            strategy = {"badstrategy": "llm_only", "nostrategy": None}.get(flow, "hybrid")
            if flow == "calib":
                self._log4(tid, "AUTO", calibrated_prob=0.3)
            else:
                self._log4(tid, "AUTO", strategy, decided_by="rule", raw_prob=None, p_method=None)
            self._close(tid, "S_RESOLVED", "auto", "resolved_user_confirmed")
        elif flow in ("clarify", "stuck"):
            self.db.log(tid, "B11", "asked", {"turn": 0})
            self.waiting[tid] = "clarify"
        elif flow in ("reject", "ignore"):
            self._approval(tid)
        elif flow == "multi":
            self.db.tickets[tid]["is_parent"] = True
            self.waiting[tid] = "reply"
        else:
            raise AssertionError(f"flow lạ: {flow}")

    def _route(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if (method, path) == ("POST", "/api/auth/login"):
            if self.login_network_error:
                raise httpx.ConnectError("SENTINEL_NET không kết nối được", request=request)
            if self.login_status is not None:
                return httpx.Response(self.login_status)
            if body.get("password") != self.password:
                return httpx.Response(401)
            token = f"Bearer tok-{body['username']}"
            self.tokens[token] = body["username"]
            if body["username"] not in self.db.users.values():
                self.db.users[f"u_{body['username']}"] = body["username"]
            return httpx.Response(200, json={"access_token": token.removeprefix("Bearer ")})
        if (method, path) == ("GET", "/api/health"):
            return httpx.Response(200, json={"status": "ok", "runtime": self.health_runtime})
        user = self._user(request)
        if (method, path) == ("POST", "/api/tickets"):
            if user is None:
                return httpx.Response(401)
            flow = m.group(1) if (m := _FLOW.search(body["text"])) else "direct"
            if flow == "boom":
                return httpx.Response(500)
            tid = f"SENTINEL_TID-{len(self.flows) + 1}"
            self.flows[tid] = flow
            self.created_at[tid] = self.clock.now
            self._turn(tid)
            self._create(tid, flow, user)
            return httpx.Response(202, json={"ticket_id": tid, "status": "S_NEW", "notices": []})
        if m := _TICKET_PATH.fullmatch(path):
            tid, sub = m.group(1), m.group(2)
            if tid not in self.flows or user is None:
                return httpx.Response(404)
            if sub is None and method == "GET":
                return httpx.Response(200, json=self._view(tid))
            if sub == "/messages" and self.waiting[tid] == "clarify":
                self._turn(tid)
                if self.flows[tid] == "clarify":
                    self.db.log(tid, "B11", "action_built", {"turn": 1})
                    self._approval(tid)
                return httpx.Response(202, json={})
            if sub == "/confirm" and self.waiting[tid] == "confirm":
                self._turn(tid)
                if body["confirmed"]:
                    self._close(tid, "S_RESOLVED", "approved", "resolved_user_confirmed")
                else:
                    self._close(tid, "S_ESCALATED", "escalated", exit_code="E5")
                return httpx.Response(202, json={})
            return httpx.Response(409)
        if m := _DECISION_PATH.fullmatch(path):
            appr = next((a for a in self.db.approvals if a["approval_id"] == m.group(1)), None)
            if appr is None:
                return httpx.Response(404)
            if user != self.db.users[appr["approver_id"]]:
                return httpx.Response(403)
            if appr["status"] != "pending":
                return httpx.Response(409)
            tid = appr["ticket_id"]
            self._turn(tid)
            if body["decision"] == "approved":
                appr["status"] = "approved"
                self.waiting[tid] = "confirm"
            else:
                if not body.get("note"):
                    return httpx.Response(422)
                appr["status"] = "rejected"
                self._close(tid, "S_REJECTED", "rejected", "rejected_by_approver")
            return httpx.Response(202, json={})
        return httpx.Response(404)

    def _view(self, tid: str) -> dict[str, Any]:
        if self.flows[tid] == "ignore" and self.waiting[tid] == "approval" and self.clock.now - self.created_at[tid] >= self.sla_s:
            self.db.approvals[-1]["status"] = "timeout"
            self._turn(tid)
            self._close(tid, "S_ESCALATED", "escalated", exit_code="E6")
        row = self.db.tickets[tid]
        return {"ticket_id": tid, "status": row["final_state"] or "S_WAIT", "waiting_for": self.waiting[tid],
                "final_state": row["final_state"], "exit_code": row["exit_code"], "close_reason": row["close_reason"]}  # fmt: skip
