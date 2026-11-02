"""Factory gateway THẬT dùng chung cho script đo M8 (G10, G11) — nối mốc G. Chỉ import được khi `EVAL_MODE=true` (qua `app.eval`).

`eval_gateway(run_id)` dựng đúng đường backend dùng (`check_llm` + `open_llm`, cấu hình `config/llm.yaml` + biến môi trường qua
`Settings`) với bốn điểm khác, đều có kiểm:
- **Chỉ đọc biến môi trường**: `Settings(_env_file=None)` — code không đọc `.env` (người chạy tự nạp biến, như compose).
- **Điều kiện bắt buộc** (`EvalConfigError`, 0 lời gọi): `EVAL_MODE=true` (→ `llm_calls.prompt_full` lưu prompt đầy đủ, P2 mục 11),
  `LLM_BACKEND=real`, MỌI vai trò trong `llm.yaml` có `temperature == 0` (prompt đọc nhiệt độ từ vai trò thì tất định). Lưu ý:
  B14 tự đặt nhiệt độ từng lời gọi (self_report 0,0; vote k=5 là 0,7 theo P6) — guard này KHÔNG đổi điều đó.
- **Cache `eval`** (`llm_cache.mode = 'eval'`, không hết hạn): cùng đầu vào + cùng cấu hình → cùng đáp án, chạy lại tái lập (P8 §1, D-39).
- **Store SQL thật**: mọi lời gọi ghi `spans` + `llm_calls` (có `prompt_full`), nên tổng chi `SUM(llm_calls.cost_usd)` — nguồn của trần
  `spend.cap_usd` (N1) — có tính chi của lần đo. `max_usd` (tuỳ chọn) đặt thêm trần RIÊNG cho lượt này = tổng chi lúc bắt đầu + `max_usd`
  (hiệu lực là min với trần chung).

**Lượt eval trên DB thật.** `llm_calls.span_id → spans.turn_id → turns.ticket_id → tickets` đều NOT NULL FK nên lời gọi ngoài graph cần một
lượt cha. `ensure_eval_turn` ghi (idempotent theo `run_id`): 1 user `svc-eval` (employee), 1 ticket `eval-<run_id>` với `final_state` NULL
(ngoài mẫu số mọi tỉ lệ M9 — "lá đang chạy"), 1 turn ĐÃ KẾT THÚC (`ended_at` có giá trị → worker không "recover" lượt này). Ghi bằng `app_rw`.
**Chỉ chạy factory SAU khi đã sao lưu DB bản đo (H4).**
"""

import importlib
import re
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.clock import Clock, SystemClock
from app.llm.config import ROLES, SpendCfg
from app.llm.ports import LlmPort, TraceParent
from app.llm.store import SqlLlmStore
from app.llm.wiring import LlmSetup, check_llm, open_llm
from app.settings import Settings

RUN_ID = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")
EVAL_USER_ID = "svc-eval"
EVAL_USERNAME = "svc.eval"
EVAL_TICKET_PREFIX = "eval-"


class EvalConfigError(RuntimeError):
    """Cấu hình đo sai — thông điệp chỉ nêu TÊN biến/khoá, không có giá trị (khoá API, DSN)."""


@dataclass(frozen=True)
class EvalTurn:
    ticket_id: str
    turn_id: str


def eval_ids(run_id: str) -> EvalTurn:
    if not RUN_ID.fullmatch(run_id):
        raise EvalConfigError("run_id phải khớp [A-Za-z0-9_.-]{1,48}")
    return EvalTurn(ticket_id=f"{EVAL_TICKET_PREFIX}{run_id}", turn_id=f"{EVAL_TICKET_PREFIX}{run_id}-t1")


async def ensure_eval_turn(engine: AsyncEngine, run_id: str, now: datetime) -> EvalTurn:
    """Ghi (nếu chưa có) user + ticket + turn của lượt eval. Chạy lại cùng `run_id` không ghi thêm dòng nào."""
    ids = eval_ids(run_id)
    async with engine.begin() as conn:
        await conn.execute(
            text("INSERT INTO users (user_id, username, role) VALUES (:u, :n, 'employee') ON CONFLICT DO NOTHING"),
            {"u": EVAL_USER_ID, "n": EVAL_USERNAME},
        )
        await conn.execute(
            text(
                "INSERT INTO tickets (ticket_id, requester_id, requester_role, redacted_request, created_at, is_parent) "
                "VALUES (:t, :u, 'employee', :r, :now, false) ON CONFLICT DO NOTHING"
            ),
            {"t": ids.ticket_id, "u": EVAL_USER_ID, "now": now,
             "r": f"[eval] lượt gắn llm_calls của M8, run {run_id} — không phải yêu cầu của người dùng"},
        )  # fmt: skip
        await conn.execute(
            text(
                "INSERT INTO turns (turn_id, ticket_id, event_type, started_at, ended_at) "
                "VALUES (:u, :t, 'submit', :now, :now) ON CONFLICT DO NOTHING"
            ),
            {"u": ids.turn_id, "t": ids.ticket_id, "now": now},
        )
    return ids


def _require(settings: Settings) -> None:
    if not settings.eval_mode:
        raise EvalConfigError("EVAL_MODE=true bắt buộc (gateway đo lưu prompt_full, cache eval)")
    if settings.llm_backend != "real":
        raise EvalConfigError("LLM_BACKEND=real bắt buộc cho lần đo thật")


def _require_deterministic(setup: LlmSetup) -> None:
    hot = [r for r in ROLES if setup.config.roles[r].temperature != 0]
    if hot:
        raise EvalConfigError(f"llm.yaml: temperature của vai trò {hot} phải bằng 0 khi đo")


async def _with_run_cap(setup: LlmSetup, engine: AsyncEngine, max_usd: float) -> LlmSetup:
    if not max_usd > 0:
        raise EvalConfigError("max_usd phải > 0")
    base = await SqlLlmStore(engine).spend_total()
    spend = setup.runtime.spend
    capped = SpendCfg(cap_usd=min(spend.cap_usd, base + max_usd), warn_ratio=spend.warn_ratio, refresh_s=spend.refresh_s)
    return replace(setup, runtime=replace(setup.runtime, spend=capped))


@asynccontextmanager
async def eval_gateway(
    run_id: str, *, settings: Settings | None = None, clock: Clock | None = None, max_usd: float | None = None
) -> AsyncIterator[LlmPort]:
    settings = settings or Settings(_env_file=None)  # type: ignore[call-arg]  # chỉ biến môi trường, KHÔNG đọc .env
    _require(settings)
    eval_ids(run_id)
    setup = check_llm(settings)
    _require_deterministic(setup)
    clock = clock or SystemClock()
    engine = create_async_engine(settings.database_url, hide_parameters=True)  # F15: lỗi DB không đưa tham số (prompt_full…) vào traceback
    try:
        turn = await ensure_eval_turn(engine, run_id, clock.now())
        if max_usd is not None:
            setup = await _with_run_cap(setup, engine, max_usd)
        parent = TraceParent(turn_id=turn.turn_id, trace_id=uuid4().hex, parent_span_id=None)
        eval_settings = settings.model_copy(update={"llm_cache_mode": "eval"})
        async with open_llm(setup, eval_settings, engine=engine, clock=clock, trace=lambda: parent) as client:
            yield client
    finally:
        await engine.dispose()


async def eval_usage(engine: AsyncEngine, run_id: str) -> dict[str, Any]:
    """Tổng hợp `llm_calls` của lượt eval `run_id` (chỉ SELECT) cho manifest: số lời gọi, trúng cache, token, chi phí, model, prompt."""
    ids = eval_ids(run_id)
    async with engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT count(*), count(*) FILTER (WHERE c.cache_hit), coalesce(sum(c.tokens_in), 0), "
                    "coalesce(sum(c.tokens_out), 0), coalesce(sum(c.cost_usd), 0), "
                    "coalesce(array_agg(DISTINCT c.model), '{}'), coalesce(array_agg(DISTINCT c.prompt_id || '@' || c.prompt_version), '{}'), "
                    "coalesce(array_agg(DISTINCT c.prompt_hash), '{}') "
                    "FROM llm_calls c JOIN spans s ON s.span_id = c.span_id JOIN turns u ON u.turn_id = s.turn_id "
                    "WHERE u.ticket_id = :t"
                ),
                {"t": ids.ticket_id},
            )
        ).one()
    return {
        "n": int(row[0]), "cache_hits": int(row[1]), "tokens_in": int(row[2]), "tokens_out": int(row[3]),
        "cost_usd": float(row[4]), "models": sorted(row[5]), "prompts": sorted(row[6]),
        "prompt_sha256": sorted(h for h in row[7] if h),
    }  # fmt: skip


def resolve_factory(spec: str) -> Any:
    """`pkg.mod:fn` → hàm. Sai dạng/không import được → `ValueError` (CLI trả mã 2)."""
    module, _, name = spec.partition(":")
    if not module or not name:
        raise ValueError("--llm-factory phải có dạng pkg.mod:fn")
    try:
        return getattr(importlib.import_module(module), name)
    except (ImportError, AttributeError):
        raise ValueError(f"--llm-factory: không nạp được {spec}") from None


@asynccontextmanager
async def open_port(spec: str, run_id: str, *, max_usd: float | None = None) -> AsyncIterator[LlmPort]:
    """Gọi `fn(run_id[, max_usd=…])`; kết quả là async context manager (vd `eval_gateway`) thì vào/ra nó, không thì dùng thẳng."""
    fn = resolve_factory(spec)
    made = fn(run_id, max_usd=max_usd) if max_usd is not None else fn(run_id)
    if isinstance(made, AbstractAsyncContextManager):
        async with made as port:
            yield port
    else:
        yield made
