"""`config/llm.yaml` (P2 mục 5, sửa theo PLAN-3d): provider, vai trò, fallback, trần chi, giới hạn, cache, giá.

Khác P2 (Q-3d-3): KHÔNG nội suy `${…}`. Model hai vai trò, base_url và khoá API đọc từ env qua TÊN trường `Settings`
(`model_setting`, `base_url_setting`, `api_key_setting`); riêng bảng `pricing` ghi tên model cố định — model nào không
có dòng giá thì không bao giờ được gọi. `resolve()` dựng chuỗi đích theo `LLM_BACKEND`; `check_timing()` ép công
thức Q-3a-16 cho từng vai trò (Q-3d-7). Cả hai ném `RuntimeError` → backend/worker từ chối khởi động (fail-closed).

Q10 (ĐP 09/11): ngoài `fast`/`strong` còn hai vai `chat_fast`/`chat_strong` cho các bước hội thoại. Bảng `prompt_roles` ghi đè vai THỰC SỰ dùng theo
prompt id (file prompt giữ nguyên trường `role` — node truyền đúng vai đó, client đối chiếu như cũ); trần vào (`budget_in`), timeout, đích và
khoá cache đều theo vai thực sự dùng. `CHAT_MODEL` trống → đích chính của vai chat = đích chính của vai gốc (`model_default_role`), hành vi y hệt
trước lô Q10 trừ trần vào của 5 prompt hội thoại. b02_injection_judge và b14_* KHÔNG được có trong `prompt_roles` (model đã đo trong báo cáo).

`providers.<tên>.extra_body` (LLM-G): trường thêm vào thân request cho tính năng riêng của nhà cung cấp (vd. DeepSeek
`thinking: {type: disabled}`). SDK openai gộp nó ĐÈ lên body → khoá trùng tham số gateway đã điều khiển bị từ chối lúc nạp;
giá trị phải chuyển được sang JSON (không date, NaN, inf) ngay lúc nạp, không để nổ ở lời gọi đầu. Mọi model cấu hình đặt
`hide_input_in_errors`: lỗi khởi động chỉ nêu đường dẫn trường + lý do, không in giá trị (extra_body có thể mang khoá riêng).
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)

from app.llm.registry import Prompt, PromptRegistry
from app.settings import Settings

type Role = Literal["fast", "strong"]  # vai node truyền / file prompt khai — hợp đồng node ↔ prompt (client đối chiếu)
type LlmRole = Literal["fast", "strong", "chat_fast", "chat_strong"]  # vai THỰC SỰ dùng, sau khi áp `prompt_roles` (Q10)
type Backend = Literal["scripted", "real"]

BASE_ROLES: tuple[Role, ...] = ("fast", "strong")
# Vai gốc xếp trước: `resolve` cần đích chính của vai gốc để vai chat mượn khi CHAT_MODEL trống.
ROLES: tuple[LlmRole, ...] = ("fast", "strong", "chat_fast", "chat_strong")
CHAT_BASE: Mapping[LlmRole, Role] = {"chat_fast": "fast", "chat_strong": "strong"}  # vai chat → vai gốc (model mặc định, tầng, trần vào tối thiểu)
NO_FALLBACK_ROLES: frozenset[LlmRole] = frozenset({"strong", "chat_strong"})  # P2 mục 5: strong KHÔNG fallback — vai chat_strong cũng vậy
# Chốt cứng (Q10): prompt đã đo trong báo cáo thì model KHÔNG được đổi bằng cấu hình — chặn ngay lúc nạp llm.yaml.
PINNED_PROMPTS: Mapping[str, str] = {
    "b02_injection_judge": "B2 LLM chấm tấn công: τ 0,9999 chọn theo model này, D-52",
    "b14_risk_estimate": "B14 ước lượng rủi ro M5: RQ1 đo theo model này",
    "b14_risk_vote": "B14 ước lượng rủi ro M5 (bỏ phiếu): RQ1 đo theo model này",
}
SCRIPTED_PROVIDER = "scripted"
SCRIPTED_MODEL = "scripted"  # Q-3d-4: mọi vai trò khi LLM_BACKEND=scripted; vẫn phải có dòng pricing (giá 0)

_FROZEN = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

# Khoá `extra_body` bị cấm (so sau strip + lower): gateway tự đặt; làm hỏng cách gateway đọc phản hồi (một lựa chọn, văn
# bản); tham số sinh chữ do gateway quản. extra_body chỉ để bật/tắt tính năng riêng của nhà cung cấp.
EXTRA_BODY_FORBIDDEN = frozenset({
    "model", "messages", "max_tokens", "max_completion_tokens", "temperature", "response_format", "timeout",
    "stream", "stream_options", "n", "tools", "tool_choice", "functions", "function_call", "parallel_tool_calls",
    "logprobs", "top_logprobs", "modalities", "audio", "prediction",
    "stop", "top_p", "seed", "logit_bias", "presence_penalty", "frequency_penalty",
})  # fmt: skip


class Price(BaseModel):
    """USD / 1M token (P2 mục 5)."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True, hide_input_in_errors=True)

    in_: float = Field(alias="in", ge=0)
    out: float = Field(ge=0)

    @property
    def paid(self) -> bool:
        """"Trả phí" = giá > 0 — trần chi tiêu chỉ chặn loại này (Q-3d-4; P2: local và cache vẫn chạy)."""
        return self.in_ > 0 or self.out > 0

    def cost(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.in_ + tokens_out * self.out) / 1_000_000


class ProviderCfg(BaseModel):
    model_config = _FROZEN

    kind: Literal["openai_compat"]
    base_url_setting: str  # tên trường Settings (env), vd. llm_base_url → LLM_BASE_URL
    api_key_setting: str  # tên trường SecretStr của Settings, vd. llm_api_key → LLM_API_KEY
    # non-strict mặc định: schema có dict tự do (slots) không hợp strict mode; chốt lại ở mốc G bằng probe
    json_mode: Literal["json_schema", "json_object"] = "json_schema"
    extra_body: dict[str, Any] | None = None  # None = không gửi trường thêm nào (body y như trước LLM-G)

    @field_validator("extra_body", mode="before")
    @classmethod
    def _no_gateway_keys(cls, v: Any) -> Any:
        if isinstance(v, dict):
            not_str = [repr(k) for k in v if not isinstance(k, str)]
            if not_str:
                raise ValueError(f"extra_body: khoá phải là chuỗi: {not_str}")
            clash = sorted(k for k in v if k.strip().lower() in EXTRA_BODY_FORBIDDEN)
            if clash:
                raise ValueError(f"extra_body: khoá trùng tham số gateway đã điều khiển: {clash}")
            try:
                json.dumps(v, allow_nan=False)
            except (TypeError, ValueError):
                raise ValueError("extra_body: giá trị không chuyển được sang JSON (date, NaN, inf…)") from None
        return v


class RoleCfg(BaseModel):
    model_config = _FROZEN

    provider: str
    model_setting: str  # tên trường Settings chứa tên model (FAST_MODEL / STRONG_MODEL / CHAT_MODEL) — chỉ dùng khi `real`
    # Chỉ vai chat (Q10): `model_setting` TRỐNG → dùng đúng đích chính của vai này (chat_fast → fast, chat_strong → strong)
    model_default_role: Role | None = None
    model_version: str | None = None  # ghim phiên bản (vào khoá cache, Q-3d-9); None = không ghim
    timeout_s: float = Field(gt=0)  # mỗi request
    max_retries: int = Field(ge=0)  # số lần THỬ LẠI (429/5xx/timeout/mất kết nối) trên một đích
    deadline_s: float = Field(gt=0)  # bọc TOÀN BỘ complete(): retry + fallback + sửa schema (Q-3d-7)
    max_tokens: int = Field(ge=1)
    temperature: float = Field(ge=0, le=2)
    budget_in: int = Field(ge=1)  # trần token đầu vào [Chốt 17.2]


class FallbackCfg(BaseModel):
    model_config = _FROZEN

    provider: str
    model: str = Field(min_length=1)  # tên cố định — phải có dòng pricing


class SpendCfg(BaseModel):
    model_config = _FROZEN

    cap_usd: float = Field(gt=0)  # N1: ≤ 1.000.000 đ cho cả đồ án
    warn_ratio: float = Field(gt=0, le=1)  # ≥ ngưỡng → log cảnh báo (cảnh báo M9 luật 14: P9)
    refresh_s: float = Field(default=60, gt=0)  # làm mới SUM(llm_calls.cost_usd)


class LimitsCfg(BaseModel):
    model_config = _FROZEN

    max_concurrency: int = Field(ge=1)  # semaphore mỗi process [Chốt 14.3]
    retry_on: frozenset[int] = Field(min_length=1)
    backoff_base_s: float = Field(gt=0)  # base · 2^(k-1)
    jitter_max_s: float = Field(ge=0)  # + ngẫu nhiên [0, jitter_max_s]


class CacheCfg(BaseModel):
    model_config = _FROZEN

    ttl_hours_runtime: float = Field(gt=0)


class LlmConfig(BaseModel):
    model_config = _FROZEN

    providers: dict[str, ProviderCfg]
    roles: dict[LlmRole, RoleCfg]
    fallback: dict[LlmRole, tuple[FallbackCfg, ...]]
    spend: SpendCfg
    limits: LimitsCfg
    cache: CacheCfg
    pricing: dict[str, Price]
    # Q10: prompt id → vai thực sự dùng (ghi đè trường `role` của file prompt khi chọn model/trần/timeout). Rỗng = như trước lô Q10.
    prompt_roles: dict[str, LlmRole] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _consistent(self) -> "LlmConfig":
        missing = [r for r in ROLES if r not in self.roles or r not in self.fallback]
        if missing:
            raise ValueError(f"llm.yaml thiếu vai trò trong roles/fallback: {missing}")
        for r in ROLES:
            if r in NO_FALLBACK_ROLES and self.fallback[r]:
                # P2 mục 5: strong KHÔNG fallback — kể cả sang provider khác (giữ số liệu thực nghiệm nhất quán); chat_strong cũng vậy
                raise ValueError(f"llm.yaml: fallback.{r} phải rỗng (P2 mục 5)")
            want = CHAT_BASE.get(r)
            if self.roles[r].model_default_role != want:
                raise ValueError(
                    f"llm.yaml roles.{r}: model_default_role = {self.roles[r].model_default_role!r}, phải là {want!r} "
                    "(chỉ vai chat có, và trỏ về vai gốc cùng tầng — CHAT_MODEL trống thì vai chat dùng model của vai gốc)"
                )
        for chat, base in CHAT_BASE.items():
            if self.roles[chat].budget_in < self.roles[base].budget_in:
                raise ValueError(
                    f"llm.yaml roles.{chat}: budget_in {self.roles[chat].budget_in} < roles.{base}.budget_in "
                    f"{self.roles[base].budget_in} — CHAT_MODEL trống thì vai chat không được cắt nhiều hơn vai gốc"
                )
        for pid in self.prompt_roles:
            if pid in PINNED_PROMPTS:
                raise ValueError(
                    f"llm.yaml prompt_roles: {pid} không được đổi vai — model của prompt này đã đo trong báo cáo "
                    f"({PINNED_PROMPTS[pid]})"
                )
        used = [self.roles[r].provider for r in ROLES] + [f.provider for r in ROLES for f in self.fallback[r]]  # gồm cả vai chat
        unknown = sorted(set(used) - set(self.providers))
        if unknown:
            raise ValueError(f"llm.yaml: provider chưa khai báo: {unknown}")
        bad = sorted(k for k in self.pricing if not k.strip() or "${" in k)
        if bad:
            raise ValueError(f"llm.yaml: khoá pricing phải là tên model cố định (Q-3d-3): {bad}")
        return self


def load_llm_config(path: Path) -> LlmConfig:
    return LlmConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


# ---- Dựng chuỗi đích theo LLM_BACKEND --------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    provider: str
    model: str
    model_version: str | None
    price: Price | None  # None = model không có dòng pricing → gateway từ chối, 0 request (3-Q26)


@dataclass(frozen=True)
class RuntimeLlm:
    """Cấu hình đã giải theo backend — thứ `LLMClient` dùng. `chains[role][0]` là đích chính."""

    backend: Backend
    roles: Mapping[LlmRole, RoleCfg]
    chains: Mapping[LlmRole, tuple[Target, ...]]
    limits: LimitsCfg
    spend: SpendCfg
    cache: CacheCfg
    # Q10: rỗng (mặc định) = mọi prompt đi vai file khai — cách harness eval và test dựng tay vẫn chạy như cũ
    prompt_roles: Mapping[str, LlmRole] = field(default_factory=dict)

    def role_of(self, prompt: Prompt) -> LlmRole:
        """Vai THỰC SỰ dùng của prompt (model, `budget_in`, timeout, đích): `prompt_roles` nếu có, không thì `role` file khai."""
        return self.prompt_roles.get(prompt.id, prompt.spec.role)


def _env(setting: str) -> str:
    return setting.upper()


def _check_setting_names(cfg: LlmConfig) -> None:
    fields = Settings.model_fields
    names = [cfg.roles[r].model_setting for r in ROLES]
    names += [n for p in cfg.providers.values() for n in (p.base_url_setting, p.api_key_setting)]
    unknown = sorted({n for n in names if n not in fields})
    if unknown:
        raise RuntimeError(f"llm.yaml trỏ tới trường Settings không tồn tại: {unknown} — từ chối khởi động")
    not_secret = sorted(
        p.api_key_setting for p in cfg.providers.values()
        if "SecretStr" not in str(fields[p.api_key_setting].annotation)
    )  # fmt: skip
    if not_secret:
        raise RuntimeError(f"llm.yaml: api_key_setting phải là trường SecretStr: {not_secret} — từ chối khởi động")


def resolve(cfg: LlmConfig, settings: Settings, backend: Backend) -> RuntimeLlm:
    """Chuỗi đích mỗi vai trò. Từ chối khởi động (RuntimeError) khi model thiếu giá — nêu tên model (Q-3d-3) —,
    hoặc khi `real` thiếu model/base_url/khoá."""
    _check_setting_names(cfg)
    chains: dict[LlmRole, tuple[Target, ...]] = {}
    labels: dict[str, str] = {}
    if backend == "scripted":
        for r in ROLES:
            chains[r] = (Target(SCRIPTED_PROVIDER, SCRIPTED_MODEL, None, cfg.pricing.get(SCRIPTED_MODEL)),)
        labels[SCRIPTED_MODEL] = "LLM_BACKEND=scripted"
    else:
        for r in ROLES:
            role = cfg.roles[r]
            model = getattr(settings, role.model_setting)
            if not model and role.model_default_role is None:
                raise RuntimeError(
                    f"{_env(role.model_setting)} chưa cấu hình (bắt buộc khi LLM_BACKEND=real) — từ chối khởi động"
                )
            fallback = [Target(f.provider, f.model, None, cfg.pricing.get(f.model)) for f in cfg.fallback[r]]
            for f in cfg.fallback[r]:
                labels.setdefault(f.model, f"fallback.{r}={f.model!r}")
            if model:
                labels.setdefault(model, f"{_env(role.model_setting)}={model!r}")
                primary = Target(role.provider, model, role.model_version, cfg.pricing.get(model))
            else:  # vai chat, CHAT_MODEL trống → CHÍNH đích chính của vai gốc (cùng provider, model, phiên bản ghim → cùng khoá cache)
                assert role.model_default_role is not None
                primary = chains[role.model_default_role][0]
            chains[r] = (primary, *fallback)
        for name in sorted({t.provider for c in chains.values() for t in c}):
            p = cfg.providers[name]
            if not getattr(settings, p.base_url_setting):
                raise RuntimeError(f"{_env(p.base_url_setting)} chưa cấu hình (provider {name}) — từ chối khởi động")
            key = getattr(settings, p.api_key_setting)
            if not isinstance(key, SecretStr) or not key.get_secret_value():
                raise RuntimeError(f"{_env(p.api_key_setting)} chưa cấu hình (provider {name}) — từ chối khởi động")
    missing = sorted({t.model for c in chains.values() for t in c if t.price is None})
    if missing:
        raise RuntimeError(
            "model không có dòng trong pricing của config/llm.yaml: "
            + ", ".join(labels[m] for m in missing)
            + " — thêm dòng giá (USD/1M token) rồi khởi động lại"
        )
    return RuntimeLlm(backend, dict(cfg.roles), chains, cfg.limits, cfg.spend, cfg.cache, dict(cfg.prompt_roles))


def check_prompt_roles(cfg: LlmConfig, registry: PromptRegistry) -> None:
    """`prompt_roles` đối chiếu với `config/prompts/` (cần registry nên không làm được trong validator của `LlmConfig`): prompt id phải có
    thật, và vai gán phải CÙNG TẦNG với `role` file khai (chat_fast ↔ fast, chat_strong ↔ strong) — không thì CHAT_MODEL trống cũng đổi model."""
    declared = {p.id: p.spec.role for p in registry}
    unknown = sorted(set(cfg.prompt_roles) - set(declared))
    if unknown:
        raise RuntimeError(f"llm.yaml prompt_roles: prompt id không có trong config/prompts: {unknown} — từ chối khởi động")
    for pid, role in sorted(cfg.prompt_roles.items()):
        tier = cfg.roles[role].model_default_role or role
        if tier != declared[pid]:
            raise RuntimeError(
                f"llm.yaml prompt_roles: {pid} khai role {declared[pid]!r} nhưng được gán {role!r} (tầng {tier!r}) — "
                "CHAT_MODEL trống cũng sẽ đổi model của prompt này — từ chối khởi động"
            )


# ---- Thời gian (Q-3d-7, cùng công thức Q-3a-16 của RAG) ---------------------------------------------------


def worst_case_s(role: RoleCfg, limits: LimitsCfg) -> float:
    """Thời gian tệ nhất của MỘT đích: (max_retries+1) lần thử × timeout + Σ backoff + jitter tối đa."""
    backoff = sum(limits.backoff_base_s * 2**k for k in range(role.max_retries))
    return (role.max_retries + 1) * role.timeout_s + backoff + role.max_retries * limits.jitter_max_s


def check_timing(cfg: LlmConfig, stale_turn_seconds: float) -> None:
    """Lời gọi LLM tệ nhất vẫn xong trước khi worker coi lượt là dở dang (như `rag_deadline_s`, Q-3c-4)."""
    half = stale_turn_seconds / 2
    for r in ROLES:
        role, worst = cfg.roles[r], worst_case_s(cfg.roles[r], cfg.limits)
        if not worst < half:
            raise RuntimeError(
                f"llm.yaml roles.{r}: (max_retries+1)·timeout_s + backoff = {worst:.2f}s "
                f"≥ WORKER_STALE_TURN_SECONDS/2 = {half:g}s — từ chối khởi động"
            )
        if not role.deadline_s < half:
            raise RuntimeError(
                f"llm.yaml roles.{r}: deadline_s = {role.deadline_s:g}s ≥ WORKER_STALE_TURN_SECONDS/2 = {half:g}s"
                " — từ chối khởi động"
            )
        if worst > role.deadline_s:
            raise RuntimeError(
                f"llm.yaml roles.{r}: deadline_s = {role.deadline_s:g}s < thời gian retry tối đa {worst:.2f}s "
                "(lần thử cuối không bao giờ tới) — từ chối khởi động"
            )
