"""Phụ thuộc của node (`NodeDeps`) + phần GIẢ của Phase 2 (P1: "khung, node giả"). Phase 3+ thay từng
node bằng node thật. Node thật từ 2b: `b01_identity` (dùng `identity`, `directory`, `alerts`, `lockout`),
`b20_audit` (dùng `tickets`, `escalations`, `templates`, `notifier`). `ml` (3a): `MlClient` thật dựng ở
`graph/wiring.py`, test truyền `FakeMlService` (`tests/fakes/fake_ml.py`) — chưa node nào dùng ở 3a. `llm` (3d):
`LLMClient` dựng ở `graph/wiring.py` (`llm/wiring.open_llm`) — chưa node nào gọi ở 3d.

`FakeScenario` chọn kết quả của mỗi node theo ticket (mặc định = đường vui dừng ở chờ duyệt), để test
đi được mọi nhánh ra của mọi node. Kết quả đặc biệt `"raise"` → node ném `ValueError` (TC29 → E9).
`hook(state, label)` cho test chèn việc vào giữa node (vd. giết process ngay sau `approval_create`).
Trên stack compose (2b-4) dùng `StackScenario`: chọn preset theo thẻ `[fake:<preset>]` trong câu yêu cầu,
kết quả suy từ state (không từ bộ nhớ process), dừng `FAKE_NODE_DELAY` giây ở điểm preset khai báo.

Các port side effect (`Notifier`, `Approvals`, `DeadlineStore`) luôn được node gọi QUA `effects.once`.
"""

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.approval.store import ApprovalRow, NoticeKind
from app.auth.ports import AdUser
from app.core.fake_tag import FAKE_TAG
from app.domain.action import Action, ActionMeta
from app.domain.approval import Lookup, Roster
from app.domain.context import RequesterContext
from app.domain.policy import BusinessHours
from app.domain.ticket_state import ExecutionResult, RiskDecision
from app.executor.errors import ExecutionInterrupted
from app.executor.txlog import TxLog
from app.graph.ports import (
    AlertSink,
    DeadlineStore,
    EscalationStore,
    IdentityReads,
    SecurityEvents,
    TicketStore,
    ToolCaller,
    ToolResult,
)
from app.guard.output import OutputGuard, default_output_guard
from app.guard.privacy import TextRedactor, guard_from_settings
from app.llm import LlmPort
from app.ml import MlPort
from app.rag.ports import RagPort
from app.risk.calibrator import Calibrator
from app.risk.estimator import DisabledEstimator, RiskEstimator
from app.settings import (
    EscalationTemplates,
    PolicyConstants,
    SlotsFile,
    get_action_metadata,
    get_policy,
    get_settings,
    get_slots,
)


class Notifier(Protocol):
    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str: ...


class Approvals(Protocol):
    async def create(
        self,
        ticket_id: str,
        approver_id: str,
        deadline: datetime,
        action_plan_hash: str,
        *,
        backup_approver_id: str | None,
        conflict_detected: bool,
        conflict_type: str | None,
    ) -> str:
        """B15 (qua `effects.once("approval_create")`). Phase 4 4b P8: 3 tham số keyword BẮT BUỘC (TQ-9)."""
        ...

    async def notify_approver(self, approval_id: str, approver_id: str, kind: NoticeKind = "new") -> str:
        """B15 (qua `effects.once("notify_approver")`, `kind` mặc định `new`). 4c P3: `reminder_1`/`reminder_2` do worker gửi."""
        ...

    async def close(
        self,
        approval_id: str,
        result: str,
        at: datetime,
        *,
        decided_by: str | None = None,
        note: str | None = None,
    ) -> int:
        """B16 ghi kết quả vào phiếu (idempotent: chỉ đổi phiếu đang `pending`; đặt `decided_at`). Trả số dòng đổi (0/1) — 4c P2
        `close_applied`."""
        ...

    async def get_status(self, approval_id: str) -> str | None:
        """B17 (3h, phase3 11.4 bước 1; P8): trạng thái phiếu trong BẢNG — "đã duyệt" = state + bảng + hash. None = không có."""
        ...

    async def get(self, approval_id: str) -> ApprovalRow | None:
        """Phase 4 4b: B15 đọc lại phiếu sau `once` / nhánh `peek` (báo `a.approver_id`, điểm log 5); B17 lấy `decided_by` (P13)."""
        ...


class ApproverUsers(Protocol):
    """Phase 4 4b P5 (Q-4-N, TQ-3): người duyệt/dự phòng B15 vừa chọn phải có dòng `users` TRƯỚC khi tạo phiếu (FK
    `approvals.approver_id`, `backup_approver_id`, `audit_logs.approver_id`) — kể cả người chưa từng đăng nhập. Bản thật
    `auth.user_sync.AuthApproverUsers` bọc `AdUserSync` (MỘT định nghĩa với đăng nhập): chuỗi quản lý qua `lookup` (có cache của
    node, registry bước `B15_APPROVER`), mang khoá trượt của username ma khi dòng vừa tạo; KHÔNG tạo phiên, KHÔNG phát token,
    không đổi `token_version` khi role không đổi. Không gọi qua `effects.once` (đồng bộ idempotent, không side effect ra ngoài)."""

    @property
    def available(self) -> bool:
        """False = tiến trình thiếu `JWT_SIGNING_KEY` (khoá HMAC username ma) → B15 E2 `approver_sync_unavailable` TRƯỚC
        `ensure`, 0 phiếu (Q-4b-5)."""
        ...

    async def ensure(self, ad_user: AdUser, lookup: Lookup[AdUser], *, now: datetime) -> None:
        """Lỗi tra AD trong chuỗi quản lý → `ApproverLookupError` lan ra (B15 → E2)."""
        ...


class Executor(Protocol):
    """Điểm ghi duy nhất (B17, 3h — phase3 11.4): chạy `PLAN[action.type]` qua registry GHI (token svc_executor), mỗi bước có
    dòng `transaction_log` `begun` TRƯỚC lời gọi; lỗi bước → hoàn tác nếu `reversible` → `ExecutionResult(success=False,
    handoff_note=4 phần)`. Ticket đã có `begun` (mọi lượt) → ném `executor.errors.ExecutionInterrupted` (0 lời gọi ghi; B17
    đã hỏi `NodeDeps.txlog` ở bước 0 — đây là lớp thứ hai). Không đủ TRỌN timeout ghi cho cả kế hoạch → `TurnBudgetExceeded` TRƯỚC `begun` (P4). Thật: `executor/vpn.py`
    (chỉ API process — P7); worker và API thiếu token: `RefusingExecutor`."""

    async def execute(self, ticket_id: str, turn_id: str, action: Action) -> ExecutionResult: ...


DEFAULT_OUTCOMES: Mapping[str, str] = {
    "b02_screen": "ok",
    "b03_classify": "single",
    "b06_diagnose": "ok",
    "b08_retrieve": "ok",
    "b10_route": "action",
    "b11_slots": "complete",
    "b12_assess": "hitl",
    "b15_prepare_approval": "ok",
    "b17_execute": "ok",
    "parent_wait": "wait",
}

type Hook = Callable[[Mapping[str, Any]], Any]


class FakeScenario:
    def __init__(self, default: Mapping[str, str] | None = None) -> None:
        self._default = {**DEFAULT_OUTCOMES, **(default or {})}
        self._plans: dict[tuple[str, str], list[str]] = {}
        self._template: dict[str, list[str]] = {}  # `plan_all`: áp cho ticket chưa có kịch bản riêng
        self._hooks: dict[tuple[str, str], Hook] = {}
        self._all_hooks: dict[str, Hook] = {}

    def plan(self, ticket_id: str, **outcomes: str | list[str]) -> "FakeScenario":
        """Kết quả cho ticket: một chuỗi, hoặc danh sách dùng lần lượt (phần tử cuối lặp lại)."""
        for node, value in outcomes.items():
            self._plans[(ticket_id, node)] = [value] if isinstance(value, str) else list(value)
        return self

    def plan_all(self, **outcomes: str | list[str]) -> "FakeScenario":
        """Như `plan` nhưng cho MỌI ticket (id do API sinh, test không biết trước). Mỗi ticket nhận
        một bản sao riêng của danh sách."""
        for node, value in outcomes.items():
            self._template[node] = [value] if isinstance(value, str) else list(value)
        return self

    def on(self, ticket_id: str, label: str, fn: Hook) -> "FakeScenario":
        self._hooks[(ticket_id, label)] = fn
        return self

    def on_all(self, label: str, fn: Hook) -> "FakeScenario":
        self._all_hooks[label] = fn
        return self

    def pick(self, state: Mapping[str, Any], node: str) -> str:
        key = (state["ticket_id"], node)
        if key not in self._plans and node in self._template:
            self._plans[key] = list(self._template[node])
        seq = self._plans.get(key)
        outcome = (seq.pop(0) if len(seq) > 1 else seq[0]) if seq else self._default[node]
        if outcome == "raise":
            raise ValueError(f"lỗi giả tại {node}")  # TC29: exception không lường trước
        return outcome

    async def hook(self, state: Mapping[str, Any], label: str) -> None:
        fn = self._hooks.get((state["ticket_id"], label)) or self._all_hooks.get(label)
        if fn is not None:
            result = fn(state)
            if inspect.isawaitable(result):
                await result

    async def pause(self, state: Mapping[str, Any], point: str) -> None:
        """Điểm dừng trước node giả (`builder.fake_nodes`) — bản test không dừng."""


# ---- Kịch bản trên stack compose (2b-4): FAKE_SCENARIO + thẻ [fake:<preset>], FAKE_NODE_DELAY ----

# Node giả được phép làm điểm dừng: không có node thật (b01, b20) và node chờ (dừng ở đó chỉ làm
# chậm lượt resume, không mở ra khe hở nào mới). Cộng hook sau khi tạo phiếu (D-18).
PAUSABLE_NODES = frozenset({
    "b02_screen", "b03_classify", "b06_diagnose", "b08_retrieve", "b10_route", "b11_slots",
    "b12_assess", "b15_prepare_approval", "b17_execute",
})  # fmt: skip
PAUSE_POINTS = PAUSABLE_NODES | {"after_approval_create"}


@dataclass(frozen=True)
class StackPreset:
    # node → kết quả đánh chỉ số theo `clarification_turns` của STATE (phần tử cuối lặp lại) — không theo
    # bộ nhớ process: backend, worker, trước/sau restart đều chọn như nhau.
    outcomes: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    pause_at: str | None = None  # điểm dừng FAKE_NODE_DELAY giây (để SIGKILL giữa lượt)


STACK_PRESETS: Mapping[str, StackPreset] = {
    "approval": StackPreset(),  # đường mặc định: dừng ở chờ duyệt
    "clarify": StackPreset({"b11_slots": ("missing", "complete")}),
    "confirm": StackPreset({"b10_route": ("info",)}),
    "raise": StackPreset({"b06_diagnose": ("raise",)}),  # TC29 → E9
    "kill_b06": StackPreset(pause_at="b06_diagnose"),
    "kill_b15": StackPreset(pause_at="after_approval_create"),
}

type Sleep = Callable[[float], Awaitable[None]]


class StackScenario(FakeScenario):
    """Kịch bản node giả chọn theo ticket bằng thẻ `[fake:<preset>]` trong `redacted_request` (chỉ dựng
    khi `FAKE_SCENARIO` đặt, dev/test — `graph/wiring.fake_scenario`). Không thẻ → preset `default`.
    Thẻ lạ → `ValueError` trong node giả → E9 qua boundary (thấy được, không lặng lẽ về mặc định).
    Chỉ node giả gọi `deps.scenario`; node thật B1/B20 không đọc thẻ."""

    def __init__(self, default: str, *, delay: float = 0.0, sleep: Sleep = asyncio.sleep) -> None:
        if default not in STACK_PRESETS:
            raise ValueError(f"FAKE_SCENARIO={default!r} lạ — chọn một trong {sorted(STACK_PRESETS)}")
        if delay < 0:
            raise ValueError("FAKE_NODE_DELAY phải ≥ 0")
        super().__init__()
        self.default = default
        self.delay = delay
        self._sleep = sleep

    def preset(self, state: Mapping[str, Any]) -> StackPreset:
        found = FAKE_TAG.search(str(state.get("redacted_request") or ""))
        name = found.group(1) if found else self.default
        if name not in STACK_PRESETS:
            raise ValueError(f"thẻ [fake:{name}] lạ — chọn một trong {sorted(STACK_PRESETS)}")
        return STACK_PRESETS[name]

    def pick(self, state: Mapping[str, Any], node: str) -> str:
        seq = self.preset(state).outcomes.get(node)
        if not seq:
            return DEFAULT_OUTCOMES[node]
        outcome = seq[min(int(state.get("clarification_turns") or 0), len(seq) - 1)]
        if outcome == "raise":
            raise ValueError(f"lỗi giả tại {node}")  # TC29: exception không lường trước
        return outcome

    async def hook(self, state: Mapping[str, Any], label: str) -> None:
        await self.pause(state, label)

    async def pause(self, state: Mapping[str, Any], point: str) -> None:
        if self.delay > 0 and self.preset(state).pause_at == point:
            await self._sleep(self.delay)


@dataclass
class NodeDeps:
    notifier: Notifier
    approvals: Approvals
    executor: Executor
    # B17 bước 0 (chốt DỪNG 2, NGHI-2): ticket đã có `begun` ở bất kỳ lượt nào → E7 TRƯỚC mọi bước kiểm lại. Bắt buộc, không
    # bản mặc định (mặc định "chưa có gì" = fail-open).
    txlog: TxLog
    deadlines: DeadlineStore
    constants: PolicyConstants
    identity: IdentityReads  # B1: sessions + users.locked_until
    directory: ToolCaller  # B1: `ad_get_user` qua ToolRegistry (retry, breaker)
    alerts: AlertSink  # B1: cảnh báo dò mật khẩu (P9 luật 3)
    lockout: timedelta  # LOCKOUT_MINUTES — B1 suy thời điểm bắt đầu khoá từ `locked_until`
    tickets: TicketStore  # B20: created_at, số lượt, ghi kết quả cuối một lần
    escalations: EscalationStore  # B20: hàng đợi L2 (qua effects.once)
    templates: EscalationTemplates  # B20: thông báo + next_for_l2 theo mã E
    ml: MlPort  # ml-service qua MlClient (3-Q7): B8 (3c), B2/B3 (3e/3f). Bắt buộc, không bản giả mặc định
    rag: RagPort  # B8 (3c): retrieve/expand_for_answer. Bắt buộc, không bản giả mặc định
    # LLM gateway (3d, P2): B2 L4 (3e), B3 (3f), B10/B11 (3g). Bắt buộc, không bản giả mặc định — test dùng
    # `LLMClient` thật với ScriptedLLM làm provider (`tests/fakes/llm.make_gateway`, phase3 7.3).
    llm: LlmPort
    # `security_events(injection_detected)` của B2 / tin trả lời (3e) — CHỈ qua `effects.once("security_event")`.
    security_events: SecurityEvents
    # Phase 4 4b (P1, P5): roster người duyệt theo intent (`config/approvers.yaml`, đã kiểm lúc khởi động) + đồng bộ dòng `users`
    # của người duyệt. Bắt buộc, không mặc định (mặc định = người duyệt "ai đó" / bỏ qua FK = fail-open).
    approvers: Mapping[str, Roster]
    approver_users: ApproverUsers
    scenario: FakeScenario = field(default_factory=FakeScenario)
    # B15 GIẢ: người duyệt cố định (`FAKE_APPROVER_ID`, chỉ dev/test). None → B15 ném → E9.
    approver_id: str | None = "l1-fake"
    # 3-Q13: slot nối vào câu truy hồi RAG (`build_query`, B8) — một nguồn `config/slots.yaml`.
    query_slots: tuple[str, ...] = field(default_factory=lambda: tuple(get_slots().query_slots))
    # 3f: slot theo intent (B3 `sanitize_slots`), metadata hành động (B11 `build_action`, 3g), intent đang bật (B3, 3-Q27 —
    # frozenset thay vì cả `Settings`: node chỉ cần đúng tập này), cờ ablation RQ3 (B6). Mặc định = cấu hình repo / Settings.
    slots: SlotsFile = field(default_factory=get_slots)
    action_metadata: Mapping[str, Mapping[str, ActionMeta]] = field(
        default_factory=lambda: get_action_metadata().root
    )
    enabled_intents: frozenset[str] = frozenset({"vpn"})
    enable_proactive_diagnosis: bool = True
    # Phase 4 S0-P11: `GROUNDING_GATE_ACTIONS` (ablation) — B10 áp B9 cho cả nhánh hành động. Mặc định = Settings (tắt).
    grounding_gate_actions: bool = False
    # Phase 4 P4: `lineage.commit_sha` (B10, B12) = `Settings.app_git_sha` (None = không biết — build từ cây bẩn/test).
    commit_sha: str | None = None
    # 3g: output guard (phase3 10.3) — MỌI chữ LLM sắp lưu/gửi (thân B10, câu hỏi B11) qua đây (P4). Privacy guard THUẦN
    # (`redact_text`) — `clarify_wait` che lại câu trả lời trước khi gửi LLM/lưu (P3, Q-3g-4). Mặc định = cấu hình repo
    # (guard regex; KHÔNG BAO GIỜ mặc định bản không che); runtime dựng tường minh theo Settings (`graph/wiring._open`).
    output_guard: OutputGuard = field(default_factory=default_output_guard)
    privacy: TextRedactor = field(default_factory=lambda: guard_from_settings(get_settings()))
    # 3h (phase3 11.2, 11.3): giờ hành chính của luật R18 (`config/policy.json` — một nguồn). Lớp 2 của M5 (B14): mặc định
    # `DisabledEstimator` (ném → E5 `llm_layer_disabled`); runtime (`graph/wiring._open`, Phase 6 6C) dựng `LlmRiskEstimator`.
    business_hours: BusinessHours = field(default_factory=lambda: get_policy().business_hours)
    estimator: RiskEstimator = field(default_factory=DisabledEstimator)
    # Phase 6 6C (P1, P10): calibrator nạp lúc khởi động (`m5.calibrator_version`) — None = chưa hiệu chỉnh → không bao giờ AUTO
    # (D-38); `eval_mode` = `Settings.eval_mode`. D-60: chiến lược M5 KHÔNG còn ở đây — B12 đọc chiến lược đã chụp trên ticket
    # (`TicketStore.strategy_of`); điểm log 4 luôn ghi `detail.strategy`. Mặc định = an toàn (không AUTO do LLM).
    calibrator: Calibrator | None = None
    eval_mode: bool = False
    # Phase 4 4b P12: hạn duyệt (phút) HIỆU LỰC = `APPROVAL_SLA_MINUTES_DEV` (chỉ dev/test) hoặc `SLA_MINUTES` của policy.json — wiring
    # tính, node không đọc Settings. Mặc định = policy.json.
    approval_sla_minutes: int = field(default_factory=lambda: get_policy().constants.SLA_MINUTES)


def fake_requester(user_id: str, now: datetime) -> RequesterContext:
    return RequesterContext(
        user_id=user_id, role="employee", department="it", manager_id=None,
        employment_status="active", tenure_days=365, is_privileged_account=False, captured_at=now,
    )  # fmt: skip


FAKE_ACTION = Action(
    type="vpn_reset_session", target="user:fake", requested_for="fake", scope="single_account",
    privilege_level="standard_user", reversible=True, reversibility="full",
    data_sensitivity="low", params={}, facts={},
)  # fmt: skip


def fake_risk(route: str) -> RiskDecision:
    decision = {"AUTO": "allow", "HITL": "approval_required", "ESCALATE_L2": "deny"}[route]
    level = {"AUTO": "low", "HITL": "medium", "ESCALATE_L2": "high"}[route]
    return RiskDecision(
        decided_by="rule", policy_decision=decision, matched_rule_id="FAKE", raw_prob=None,  # type: ignore[arg-type]
        calibrated_prob=None, p_method=None, risk_level=level, route=route,  # type: ignore[arg-type]
        reason="node giả (Phase 2)", thresholds=None,
    )  # fmt: skip


# ---- Bản không làm gì — dùng khi dựng runtime thật ở Phase 2 (chưa có notify/approval thật) ----


class LoggingNotifier:
    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str:
        return f"noop:{ticket_id}"


REFUSED_NOTE = (
    "Đã làm: chưa bước nào. Lỗi ở bước: — (tiến trình không có credential ghi SVC_EXECUTOR_TOKEN). Hoàn tác: không cần. "
    "L2 cần làm tay: thực hiện hành động dự kiến trên hệ thống đích."
)


class RefusingExecutor:
    """Không thực thi gì (0 lời gọi ghi): worker (D-03, P7) và API thiếu `SVC_EXECUTOR_TOKEN` → B17 E7 `exec_failed`.

    Soát S12 NGHI-3: checkpoint LangGraph mặc định `durability="async"` — API có thể chết SAU khi đã gửi lời gọi ghi của B17
    mà checkpoint của node đứng trước (vd `approval_wait`) chưa lưu xong → worker phục hồi, chạy lại tới B17 NGAY trong worker.
    Có `txlog` → đọc `transaction_log`: ticket đã có `begun` (mọi lượt) → `ExecutionInterrupted` (E7 `exec_interrupted`, "kiểm
    tra trạng thái thật"), KHÔNG trả "chưa bước nào… làm tay" (L2 có thể làm lần 2). B17 bước 0 đã chặn trước — lớp thứ hai.
    `txlog` BẮT BUỘC (soát lại DỪNG 2 NGHI-b: mặc định "không có txlog" = fail-open)."""

    def __init__(self, txlog: TxLog) -> None:
        self._txlog = txlog

    async def execute(self, ticket_id: str, turn_id: str, action: Action) -> ExecutionResult:
        if await self._txlog.has_begun(ticket_id):
            raise ExecutionInterrupted(f"ticket {ticket_id}: transaction_log đã có begun")
        return ExecutionResult(
            success=False, steps_done=[], failed_step=None, rollback_status="not_attempted", rollback_details=[],
            action_plan_hash_matched=None, handoff_note=REFUSED_NOTE,
        )  # fmt: skip



class UnconfiguredDirectory:
    """Thiếu SVC_AGENT_TOKEN: không gọi được AD — trả lỗi hệ thống (B1 → E2), không kết luận gì về
    người dùng. Dùng thay vì để runtime không khởi động được."""

    error = "not_configured: SVC_AGENT_TOKEN"

    async def call(self, name: str, args: Mapping[str, Any], *, caller_step: str) -> ToolResult:
        return ToolResult(name, None, self.error, 0, False)
