"""`GET /api/admin/llm-status` — trạng thái LLM CHỈ ĐỌC cho Trưởng BP IT (I1).

Quyền `llm_status:read` (chỉ manager). Thứ tự lỗi: 401 → 403 → 503 `monitor_unavailable` (thiếu `MONITOR_DATABASE_URL`;
KHÔNG rơi về `engines.main`). Chỉ GET: các method khác → 405. Không gọi LLM, không ghi DB/file/audit.

Nguồn:
- `backend`, tên model hai vai trò, khoá: `Settings` + `config/llm.yaml` (đọc mỗi lần gọi, như probe của /api/health).
  `scripted` → mọi vai trò là `"scripted"`. `real` → `FAST_MODEL`/`STRONG_MODEL` (chưa đặt → null).
- `api_key_configured`: MỘT boolean — mọi provider đang dùng có khoá không rỗng. Tuyệt đối không trả khoá, độ dài, tiền tố,
  mã băm; thân response là model `extra="forbid"` đủ trường, không có chỗ nào nhận giá trị khoá.
- `spend`: `SUM(llm_calls.cost_usd)` (cùng nguồn trần chi) so với `spend.cap_usd`. `percent = total / cap × 100` (số thô, không
  làm tròn). `status`: `over` khi `total >= cap` (như `llm/spend.py`), `warn` khi `total >= cap × warn_ratio`, còn lại `ok`;
  `warn_percent = warn_ratio × 100` lấy từ cấu hình. Chi phí tính theo bảng giá `pricing` trong cấu hình (giá giờ cao điểm) —
  là cận trên, có thể cao hơn hoá đơn nhà cung cấp.
- `usage`: `calls_total`; `calls_24h` = lời gọi có `created_at >= as_of − 24 giờ`; `tickets_with_calls` = số ticket có ≥ 1 lời
  gọi; `avg_cost_per_ticket_usd` = `SUM(cost_usd) ÷ tickets_with_calls` trên TOÀN BỘ lịch sử (cache hit tính là lời gọi chi
  phí 0; chưa có ticket nào → null).
- `kb`: kết quả `_kb_status` của /api/health (alias `kb_current`, cache 10 giây; chỉ báo — lỗi → `status="unknown"`).
- `as_of`: `app.state.m9_clock.now()` (UTC); số trong `spend`/`usage` đọc cùng một snapshot READ ONLY.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, SecretStr

from app.api.alerts import ErrorDetail
from app.api.health import _kb_status
from app.auth.deps import require
from app.auth.models import Principal
from app.llm.config import BASE_ROLES, ROLES, SCRIPTED_MODEL, LlmConfig, load_llm_config
from app.monitor.db import read_snapshot
from app.monitor.queries.llm_usage import LlmUsage, llm_usage
from app.settings import Settings

router = APIRouter()

USAGE_WINDOW = timedelta(hours=24)

type SpendState = Literal["ok", "warn", "over"]
type KbState = Literal["ready", "missing", "unknown"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Models(_Strict):
    fast: str | None
    strong: str | None


class Spend(_Strict):
    total_usd: float
    cap_usd: float
    percent: float
    warn_percent: float
    status: SpendState


class Usage(_Strict):
    calls_total: int
    calls_24h: int
    tickets_with_calls: int
    avg_cost_per_ticket_usd: float | None


class Kb(_Strict):
    alias: str
    collection: str | None
    status: KbState


class LlmStatus(_Strict):
    as_of: datetime
    backend: Literal["scripted", "real"] | None
    models: Models
    api_key_configured: bool
    spend: Spend
    usage: Usage
    kb: Kb


READ_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}, 503: {"model": ErrorDetail},
}  # fmt: skip


def _models(cfg: LlmConfig, settings: Settings) -> Models:
    if settings.llm_backend == "scripted":
        return Models(fast=SCRIPTED_MODEL, strong=SCRIPTED_MODEL)
    got = {r: getattr(settings, cfg.roles[r].model_setting) or None for r in BASE_ROLES}  # Q10: trạng thái chỉ báo fast/strong, không đổi hợp đồng API
    return Models(fast=got["fast"], strong=got["strong"])


def _key_configured(cfg: LlmConfig, settings: Settings) -> bool:
    """Chỉ boolean. `real`: mọi provider mà hai vai trò (và dự phòng) dùng; `scripted`: mọi provider khai báo."""
    if settings.llm_backend == "real":
        names = {cfg.roles[r].provider for r in ROLES} | {f.provider for r in ROLES for f in cfg.fallback[r]}
    else:
        names = set(cfg.providers)
    if not names:
        return False
    for name in names:
        key = getattr(settings, cfg.providers[name].api_key_setting)
        if not isinstance(key, SecretStr) or not key.get_secret_value():
            return False
    return True


def _spend(total: float, cap: float, warn_ratio: float) -> Spend:
    """`over`/`warn` so `>=` như `llm/spend.py` (ngưỡng cảnh báo = `cap × warn_ratio`)."""
    status: SpendState = "over" if total >= cap else "warn" if total >= cap * warn_ratio else "ok"
    return Spend(total_usd=total, cap_usd=cap, percent=total / cap * 100, warn_percent=warn_ratio * 100, status=status)


def _usage(u: LlmUsage) -> Usage:
    avg = None if u.tickets == 0 else u.spent_usd / u.tickets
    return Usage(calls_total=u.calls_total, calls_24h=u.calls_since, tickets_with_calls=u.tickets, avg_cost_per_ticket_usd=avg)


def build_status(settings: Settings, cfg: LlmConfig, usage: LlmUsage, kb: dict[str, str | None], now: datetime) -> LlmStatus:
    return LlmStatus(
        as_of=now.astimezone(UTC), backend=settings.llm_backend, models=_models(cfg, settings),
        api_key_configured=_key_configured(cfg, settings),
        spend=_spend(usage.spent_usd, cfg.spend.cap_usd, cfg.spend.warn_ratio), usage=_usage(usage),
        kb=Kb.model_validate(kb),
    )  # fmt: skip


@router.get("/api/admin/llm-status", response_model=LlmStatus, responses=READ_ERRORS)
async def llm_status(
    request: Request, _: Annotated[Principal, Depends(require("llm_status:read"))]
) -> LlmStatus:
    settings: Settings = request.app.state.settings
    now: datetime = request.app.state.m9_clock.now()
    cfg = load_llm_config(settings.config_dir / "llm.yaml")
    async with read_snapshot(request.app.state.engines) as conn:
        usage = await llm_usage(conn, now - USAGE_WINDOW)
    return build_status(settings, cfg, usage, await _kb_status(request), now)
