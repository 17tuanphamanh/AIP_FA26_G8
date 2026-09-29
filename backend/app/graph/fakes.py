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
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.domain.action import Action, ActionMeta
from app.domain.context import RequesterContext
from app.domain.ticket_state import RiskDecision
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
from app.settings import (
    EscalationTemplates,
    PolicyConstants,
    SlotsFile,
    get_action_metadata,
    get_settings,
    get_slots,
)


class Notifier(Protocol):
    async def notify_user(self, ticket_id: str, text: str, needs: str = "none") -> str: ...


class Approvals(Protocol):
    async def create(
        self, ticket_id: str, approver_id: str, deadline: datetime, action_plan_hash: str
    ) -> str: ...

    async def notify_approver(self, approval_id: str, approver_id: str) -> str: ...

    async def close(
        self,
        approval_id: str,
        result: str,
        at: datetime,
        *,
        decided_by: str | None = None,
        note: str | None = None,
    ) -> None:
        """B16 ghi kết quả vào phiếu (idempotent: chỉ đổi phiếu đang `pending`)."""
        ...


class Executor(Protocol):
    async def execute(self, ticket_id: str, action: Action | None) -> bool: ...


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
FAKE_TAG = re.compile(r"\[fake:([a-z0-9_]+)\]")


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
    # 3g: output guard (phase3 10.3) — MỌI chữ LLM sắp lưu/gửi (thân B10, câu hỏi B11) qua đây (P4). Privacy guard THUẦN
    # (`redact_text`) — `clarify_wait` che lại câu trả lời trước khi gửi LLM/lưu (P3, Q-3g-4). Mặc định = cấu hình repo
    # (guard regex; KHÔNG BAO GIỜ mặc định bản không che); runtime dựng tường minh theo Settings (`graph/wiring._open`).
    output_guard: OutputGuard = field(default_factory=default_output_guard)
    privacy: TextRedactor = field(default_factory=lambda: guard_from_settings(get_settings()))


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


class RefusingExecutor:
    """Không thực thi gì: B17 thật (credential svc_executor) làm ở Phase 3."""

    async def execute(self, ticket_id: str, action: Action | None) -> bool:
        return False



class UnconfiguredDirectory:
    """Thiếu SVC_AGENT_TOKEN: không gọi được AD — trả lỗi hệ thống (B1 → E2), không kết luận gì về
    người dùng. Dùng thay vì để runtime không khởi động được."""

    error = "not_configured: SVC_AGENT_TOKEN"

    async def call(self, name: str, args: Mapping[str, Any], *, caller_step: str) -> ToolResult:
        return ToolResult(name, None, self.error, 0, False)
