"""Q10 (ĐP 09/11, lô vai chat) — hai vai `chat_fast`/`chat_strong` cho các bước HỘI THOẠI; giữ nguyên model của B2 và B14 (test viết trước).

Hợp đồng (ĐP → Q10 · 09/11 18:50):
- `config/llm.yaml` có thêm 2 vai `chat_fast` (tham số kiểu fast) và `chat_strong` (kiểu strong); model đọc từ `Settings.chat_model`
  (CHAT_MODEL). CHAT_MODEL TRỐNG → mỗi vai chat dùng đúng đích chính của vai gốc (fast / strong).
- Bảng `prompt_roles` ghi đè vai theo prompt id: b03_classify, b10_need_type, b11_clarify_question, b11_extract_slots → chat_fast;
  b10_answer → chat_strong. File prompt GIỮ trường `role`. b02_injection_judge, b14_risk_estimate, b14_risk_vote KHÔNG được có trong
  bảng (model đã đo trong báo cáo) — validator từ chối khởi động; prompt id lạ / vai lạ cũng vậy.
- CHAT_MODEL có giá trị mà không có dòng `pricing` → từ chối khởi động.
- Khoá cache gồm model; `llm_calls.model` là model thật đã gọi.
- Trần token (`budget_in`) và cắt `trim_vars` tính theo vai SAU khi áp `prompt_roles`: chat_fast 3000, chat_strong ≥ strong, fast giữ 2000.

ScriptedLLM, không gọi LLM thật, không đọc `.env`.
"""

import copy
import dataclasses
import math
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.core.clock import FakeClock
from app.llm.config import (
    LlmConfig,
    check_timing,
    load_llm_config,
    resolve,
    worst_case_s,
)
from app.llm.context import render
from app.llm.errors import LLMBudgetExceeded, LLMUnavailable
from app.llm.ports import Role
from app.llm.providers.scripted import Http, Reply, Script, ScriptedLLM, Step
from app.llm.registry import load_prompts
from app.llm.schemas import AnswerOut, NeedTypeOut
from app.llm.wiring import check_llm
from app.settings import Settings
from pydantic import SecretStr, ValidationError
from tests.fakes.llm import MemoryLlmStore, make_gateway

REPO = Path(__file__).resolve().parents[3]
LLM_YAML = REPO / "config" / "llm.yaml"
PROMPTS = REPO / "config" / "prompts"
STALE = Settings(_env_file=None).worker_stale_turn_seconds  # type: ignore[call-arg]
PRO = "deepseek-v4-pro"

# Vai file prompt khai ↔ vai thực sự dùng (theo ĐP). Năm prompt hội thoại đi vai chat_*; ba prompt còn lại GIỮ vai gốc.
CHAT_PROMPT_ROLES = {
    "b03_classify": "chat_fast",
    "b10_need_type": "chat_fast",
    "b11_clarify_question": "chat_fast",
    "b11_extract_slots": "chat_fast",
    "b10_answer": "chat_strong",
    "b09_rewrite_query": "chat_fast",  # D-80 (11/11): viết lại câu hỏi để truy hồi — prompt hội thoại, cùng vai B10 need_type
}
PINNED: dict[str, Role] = {"b02_injection_judge": "fast", "b14_risk_estimate": "strong", "b14_risk_vote": "strong"}
DECLARED: dict[str, Role] = {"b03_classify": "fast", "b10_need_type": "fast", "b11_clarify_question": "fast", "b11_extract_slots": "fast",
            "b10_answer": "strong", "b09_rewrite_query": "fast", **PINNED}  # fmt: skip
BASE_MODEL = {"fast": "m-fast", "strong": "m-strong"}

REAL = {"fast_model": "m-fast", "strong_model": "m-strong", "llm_base_url": "http://llm.test/v1",
        "llm_api_key": SecretStr("k-khong-that")}  # fmt: skip


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


def _raw() -> dict[str, Any]:
    data = yaml.safe_load(LLM_YAML.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _cfg(mutate: Callable[[dict[str, Any]], None] | None = None) -> LlmConfig:
    data = copy.deepcopy(_raw())
    if mutate is not None:
        mutate(data)
    return LlmConfig.model_validate(data)


def _priced(data: dict[str, Any], *models: str) -> None:
    for m in models:
        data["pricing"][m] = {"in": 0.25, "out": 1.0}


# ---- A. config/llm.yaml của repo -------------------------------------------------------------------------


def test_repo_defines_chat_roles_with_fast_and_strong_style_parameters() -> None:
    cfg = load_llm_config(LLM_YAML)
    assert set(cfg.roles) == {"fast", "strong", "chat_fast", "chat_strong"}
    fast, strong, chat_fast, chat_strong = (cfg.roles[r] for r in ("fast", "strong", "chat_fast", "chat_strong"))
    assert chat_fast.model_setting == chat_strong.model_setting == "chat_model"
    assert (chat_fast.provider, chat_fast.max_tokens, chat_fast.temperature) == (fast.provider, fast.max_tokens, fast.temperature)
    assert (chat_strong.provider, chat_strong.max_tokens, chat_strong.temperature) == (strong.provider, strong.max_tokens,
                                                                                       strong.temperature)  # fmt: skip
    assert chat_fast.budget_in == 3000
    assert chat_strong.budget_in >= strong.budget_in
    assert cfg.fallback["chat_fast"] == () and cfg.fallback["chat_strong"] == ()


def test_repo_fast_and_strong_roles_unchanged() -> None:
    """B2 (fast) và B14 (strong) dùng hai vai này: tham số đã đo không được đổi (D-52, RQ1)."""
    cfg = load_llm_config(LLM_YAML)
    f, s = cfg.roles["fast"], cfg.roles["strong"]
    assert (f.model_setting, f.timeout_s, f.max_retries, f.deadline_s, f.max_tokens, f.temperature, f.budget_in) == (
        "fast_model", 8, 3, 45, 400, 0, 2000)  # fmt: skip
    assert (s.model_setting, s.timeout_s, s.max_retries, s.deadline_s, s.max_tokens, s.temperature, s.budget_in) == (
        "strong_model", 20, 1, 50, 900, 0, 6000)  # fmt: skip


def test_repo_prompt_roles_are_exactly_the_five_conversation_prompts() -> None:
    cfg = load_llm_config(LLM_YAML)
    assert dict(cfg.prompt_roles) == CHAT_PROMPT_ROLES
    assert not set(cfg.prompt_roles) & set(PINNED)


def test_prompt_files_keep_their_declared_role() -> None:
    """Không đụng file prompt: trường `role` vẫn là fast/strong như cũ — node truyền đúng vai đó (hợp đồng client)."""
    registry = load_prompts(PROMPTS)
    assert {p.id: p.spec.role for p in registry} == DECLARED


@pytest.mark.parametrize("role", ["chat_fast", "chat_strong"])
def test_repo_timing_of_chat_roles_obeys_the_startup_rule(role: str) -> None:
    cfg = load_llm_config(LLM_YAML)
    r = cfg.roles[role]  # type: ignore[index]
    worst = worst_case_s(r, cfg.limits)
    by_hand = (r.max_retries + 1) * r.timeout_s + sum(cfg.limits.backoff_base_s * 2**k for k in range(r.max_retries)) \
        + r.max_retries * cfg.limits.jitter_max_s  # fmt: skip
    assert worst == pytest.approx(by_hand)
    assert worst < STALE / 2 and worst <= r.deadline_s < STALE / 2
    check_timing(cfg, STALE)  # không ném: cả 4 vai


def test_repo_timing_values_of_chat_roles_match_the_comment_in_llm_yaml() -> None:
    cfg = load_llm_config(LLM_YAML)
    assert worst_case_s(cfg.roles["chat_fast"], cfg.limits) == pytest.approx(39.5)  # 3 × 12 + (1+2) + 2 × 0.25
    assert worst_case_s(cfg.roles["chat_strong"], cfg.limits) == pytest.approx(51.25)  # 2 × 25 + 1 + 0.25


def test_chat_roles_trade_retries_for_longer_timeouts() -> None:
    """Pro có thể chậm hơn flash → timeout dài hơn, không nhiều lần thử lại hơn (ĐP)."""
    cfg = load_llm_config(LLM_YAML)
    f, s, cf, cs = (cfg.roles[r] for r in ("fast", "strong", "chat_fast", "chat_strong"))
    assert cf.timeout_s > f.timeout_s and cf.max_retries < f.max_retries
    assert cs.timeout_s > s.timeout_s and cs.max_retries <= s.max_retries


@pytest.mark.parametrize(("role", "field", "value", "pattern"), [
    ("chat_fast", "timeout_s", 20, r"roles\.chat_fast: \(max_retries\+1\)"),
    ("chat_strong", "max_retries", 3, r"roles\.chat_strong: \(max_retries\+1\)"),
    ("chat_strong", "deadline_s", 60, r"roles\.chat_strong: deadline_s = 60s ≥ WORKER_STALE_TURN_SECONDS/2"),
    ("chat_strong", "deadline_s", 30, r"roles\.chat_strong: deadline_s = 30s < thời gian retry tối đa 51\.25s"),
    ("chat_fast", "deadline_s", 30, r"roles\.chat_fast: deadline_s = 30s < thời gian retry tối đa 39\.50s"),
])  # fmt: skip
def test_timing_violations_of_chat_roles_refuse_start(role: str, field: str, value: float, pattern: str) -> None:
    cfg = _cfg(lambda d: d["roles"][role].update({field: value}))
    with pytest.raises(RuntimeError, match=pattern):
        check_timing(cfg, STALE)


def test_worst_case_spend_reservation_numbers_in_the_comment() -> None:
    """Giữ chỗ xấu nhất của MỘT request = giá(budget_in token vào) + giá(max_tokens ra) (`LLMClient._reserve`) — số trong chú thích."""
    cfg = load_llm_config(LLM_YAML)

    def reserve(role: str, model: str) -> float:
        r = cfg.roles[role]  # type: ignore[index]
        return cfg.pricing[model].cost(r.budget_in, r.max_tokens)

    assert reserve("fast", "deepseek-flash") == pytest.approx(0.00108)
    assert reserve("chat_fast", "deepseek-flash") == pytest.approx(0.00138)
    assert reserve("chat_fast", PRO) == pytest.approx(0.005544)
    assert reserve("strong", "deepseek-flash") == pytest.approx(0.00288)
    assert reserve("chat_strong", PRO) == pytest.approx(0.011484)
    # tối đa max_concurrency request bay cùng lúc, mỗi cái giữ chỗ xấu nhất: còn xa dưới phần trần chưa chạm ngưỡng cảnh báo
    assert reserve("chat_strong", PRO) * cfg.limits.max_concurrency < cfg.spend.cap_usd * (1 - cfg.spend.warn_ratio)


# ---- B. validator lúc khởi động --------------------------------------------------------------------------


@pytest.mark.parametrize("role", ["chat_fast", "chat_strong", "fast"])
@pytest.mark.parametrize("pid", sorted(PINNED))
def test_pinned_prompt_in_prompt_roles_refuses_start_and_says_why(pid: str, role: str) -> None:
    with pytest.raises(ValidationError, match=rf"prompt_roles.*{pid}.*đã đo trong báo cáo"):
        _cfg(lambda d: d["prompt_roles"].update({pid: role}))


def test_unknown_role_in_prompt_roles_refuses_start() -> None:
    with pytest.raises(ValidationError, match="prompt_roles"):
        _cfg(lambda d: d["prompt_roles"].update({"b03_classify": "chat_ultra"}))


def test_missing_chat_role_refuses_start() -> None:
    def drop(d: dict[str, Any]) -> None:
        del d["roles"]["chat_fast"]

    with pytest.raises(ValidationError, match=r"thiếu vai trò.*chat_fast"):
        _cfg(drop)


def test_chat_strong_fallback_rejected_like_strong() -> None:
    with pytest.raises(ValidationError, match=r"fallback\.chat_strong phải rỗng"):
        _cfg(lambda d: d["fallback"].update({"chat_strong": [{"provider": "cloud_a", "model": "x"}]}))


@pytest.mark.parametrize(("role", "field", "value"), [
    ("chat_fast", "model_default_role", None),  # thiếu → CHAT_MODEL trống sẽ không có model để dùng
    ("chat_fast", "model_default_role", "strong"),  # sai tầng
    ("chat_strong", "model_default_role", "fast"),
    ("fast", "model_default_role", "strong"),  # vai gốc không có vai mặc định
])  # fmt: skip
def test_model_default_role_wiring_is_validated(role: str, field: str, value: str | None) -> None:
    def mutate(d: dict[str, Any]) -> None:
        if value is None:
            d["roles"][role].pop(field, None)
        else:
            d["roles"][role][field] = value

    with pytest.raises(ValidationError, match="model_default_role"):
        _cfg(mutate)


@pytest.mark.parametrize(("role", "budget"), [("chat_fast", 1999), ("chat_strong", 5999)])
def test_chat_budget_below_base_role_refuses_start(role: str, budget: int) -> None:
    """CHAT_MODEL trống thì chỉ model giữ như cũ — trần vào của vai chat không được thấp hơn vai gốc (không cắt nhiều hơn)."""
    with pytest.raises(ValidationError, match=rf"{role}.*budget_in"):
        _cfg(lambda d: d["roles"][role].update({"budget_in": budget}))


def _config_dir(tmp_path: Path, mutate: Callable[[dict[str, Any]], None] | None = None) -> Path:
    data = copy.deepcopy(_raw())
    if mutate is not None:
        mutate(data)
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "llm.yaml").write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    shutil.copytree(PROMPTS, cfg_dir / "prompts")
    return cfg_dir


def _scripted_settings(cfg_dir: Path, **over: Any) -> Settings:
    return _settings(app_env="dev", llm_backend="scripted", config_dir=cfg_dir,
                     llm_script_preset_dir=REPO / "config" / "scripted", **over)  # fmt: skip


def test_check_llm_on_a_copy_of_the_repo_config_passes_and_carries_prompt_roles(tmp_path: Path) -> None:
    """Đối chứng cho các ca dưới: thư mục cấu hình tạm dựng đúng thì `check_llm` qua."""
    setup = check_llm(_scripted_settings(_config_dir(tmp_path)))
    assert dict(setup.runtime.prompt_roles) == CHAT_PROMPT_ROLES


def test_unknown_prompt_id_in_prompt_roles_refuses_start(tmp_path: Path) -> None:
    cfg_dir = _config_dir(tmp_path, lambda d: d["prompt_roles"].update({"b99_khong_co": "chat_fast"}))
    with pytest.raises(RuntimeError, match=r"prompt_roles.*b99_khong_co"):
        check_llm(_scripted_settings(cfg_dir))


@pytest.mark.parametrize(("pid", "role"), [("b10_answer", "chat_fast"), ("b03_classify", "chat_strong")])
def test_prompt_role_of_the_wrong_tier_refuses_start(tmp_path: Path, pid: str, role: str) -> None:
    """Prompt `strong` mà gán `chat_fast` (hoặc ngược lại) thì CHAT_MODEL trống cũng đổi model — không còn 'y hệt hiện nay'."""
    cfg_dir = _config_dir(tmp_path, lambda d: d["prompt_roles"].update({pid: role}))
    with pytest.raises(RuntimeError, match=rf"prompt_roles.*{pid}"):
        check_llm(_scripted_settings(cfg_dir))


def test_evidence_budget_check_uses_the_effective_role(tmp_path: Path) -> None:
    """f1: b10_answer đi vai chat_strong → khung + RAG_EVIDENCE_MAX_TOKENS so với `budget_in` của chat_strong, không của `strong`."""
    cfg_dir = _config_dir(tmp_path, lambda d: d["roles"]["strong"].update({"budget_in": 4300}))  # < khung ~408 + 4000; chat_strong vẫn 6000
    assert check_llm(_scripted_settings(cfg_dir)).runtime.roles["strong"].budget_in == 4300

    def lower_chat_strong_via_both(d: dict[str, Any]) -> None:
        d["roles"]["strong"].update({"budget_in": 4300})
        d["roles"]["chat_strong"].update({"budget_in": 4300})

    with pytest.raises(ValueError, match="RAG_EVIDENCE_MAX_TOKENS"):
        check_llm(_scripted_settings(_config_dir(tmp_path / "x", lower_chat_strong_via_both)))


# ---- C. resolve: CHAT_MODEL trống / có / thiếu giá ----------------------------------------------------------


def _real_cfg() -> LlmConfig:
    return _cfg(lambda d: _priced(d, "m-fast", "m-strong"))


@pytest.mark.parametrize("chat_model", [None, ""])
def test_blank_chat_model_chat_roles_use_exactly_the_base_targets(chat_model: str | None) -> None:
    over = {} if chat_model is None else {"chat_model": chat_model}
    runtime = resolve(_real_cfg(), _settings(**REAL, **over), "real")
    assert runtime.chains["chat_fast"] == runtime.chains["fast"]
    assert runtime.chains["chat_strong"] == runtime.chains["strong"]
    assert runtime.chains["chat_fast"][0].model == "m-fast" and runtime.chains["chat_strong"][0].model == "m-strong"


def test_chat_model_set_only_chat_roles_change() -> None:
    runtime = resolve(_real_cfg(), _settings(**REAL, chat_model=PRO), "real")
    for role in ("chat_fast", "chat_strong"):
        (only,) = runtime.chains[role]
        assert (only.provider, only.model) == ("cloud_a", PRO)
        assert only.price is not None and only.price.paid and (only.price.in_, only.price.out) == (1.32, 3.96)
    assert [t.model for t in runtime.chains["fast"]] == ["m-fast"]
    assert [t.model for t in runtime.chains["strong"]] == ["m-strong"]


def test_chat_model_without_pricing_refuses_start_and_names_it() -> None:
    with pytest.raises(RuntimeError) as e:
        resolve(_real_cfg(), _settings(**REAL, chat_model="m-chua-co-gia"), "real")
    assert "CHAT_MODEL='m-chua-co-gia'" in str(e.value) and "pricing" in str(e.value)


def test_chat_model_without_pricing_refuses_check_llm() -> None:
    settings = _settings(app_env="prod", llm_backend="real", chat_model="m-chua-co-gia",
                         **{**REAL, "fast_model": "deepseek-flash", "strong_model": "deepseek-flash"})  # fmt: skip
    with pytest.raises(RuntimeError, match=r"CHAT_MODEL='m-chua-co-gia'"):
        check_llm(settings)


def test_chat_model_with_priced_model_passes_check_llm() -> None:
    settings = _settings(app_env="prod", llm_backend="real", chat_model=PRO,
                         **{**REAL, "fast_model": "deepseek-flash", "strong_model": "deepseek-flash"})  # fmt: skip
    setup = check_llm(settings)
    assert setup.runtime.chains["chat_fast"][0].model == PRO and setup.runtime.chains["fast"][0].model == "deepseek-flash"


def test_chat_model_does_not_replace_fast_model_requirement() -> None:
    """B2 vẫn cần FAST_MODEL: đặt CHAT_MODEL không làm FAST_MODEL thành tuỳ chọn."""
    over = {k: v for k, v in REAL.items() if k != "fast_model"}
    with pytest.raises(RuntimeError, match=r"FAST_MODEL chưa cấu hình"):
        resolve(_real_cfg(), _settings(**over, chat_model=PRO), "real")


def test_scripted_backend_gives_chat_roles_the_scripted_target() -> None:
    runtime = resolve(_real_cfg(), _settings(), "scripted")
    for role in ("chat_fast", "chat_strong"):
        (only,) = runtime.chains[role]
        assert (only.provider, only.model) == ("scripted", "scripted")


def test_settings_reads_chat_model_from_env_and_ignores_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _settings().chat_model is None
    monkeypatch.setenv("CHAT_MODEL", PRO)
    assert _settings().chat_model == PRO
    monkeypatch.setenv("CHAT_MODEL", "")  # compose `${CHAT_MODEL:-}` truyền chuỗi rỗng khi không đặt
    assert not _settings().chat_model


# ---- D. client: model theo từng prompt id, llm_calls, cache -------------------------------------------------

# Một phản hồi hợp lệ cho mỗi prompt (đúng schema) — chỉ để lời gọi đi hết đường, thứ cần soi là TÊN MODEL.
OK_REPLY: dict[str, dict[str, Any]] = {
    "b02_injection_judge": {"is_attack": False, "category": "none", "reason": "bình thường"},
    "b03_classify": {"intents": [], "is_multi": False},
    "b10_need_type": {"type": "info", "confidence": 0.9},
    "b09_rewrite_query": {"query": "Cách kết nối Wi-Fi công ty?"},
    "b10_answer": {"answer_markdown": "Không đủ căn cứ.", "citations": [], "cannot_answer": True},
    "b11_clarify_question": {"text": "Bạn dùng máy nào?"},
    "b11_extract_slots": {"slots": {}, "off_topic": False},
    "b14_risk_estimate": {"prob_needs_human": 0.1, "factors": [], "rationale": "ít rủi ro"},
    "b14_risk_vote": {"needs_human": False, "factors": []},
}


def _vars(pid: str, **over: Any) -> dict[str, Any]:
    spec = load_prompts(PROMPTS).get(pid).spec
    base: dict[str, Any] = {n: ([] if n == "evidence" else "x") for n in spec.allowed_vars}
    return {**base, **over}


def _script(reply: dict[str, Any]) -> Script:
    def step(_variables: Mapping[str, Any]) -> Step:
        return Reply(reply)

    return step


def _gateway(chat_model: str | None, *, store: MemoryLlmStore | None = None, prompt_roles: bool = True) -> Any:
    over = {"chat_model": chat_model} if chat_model else {}
    runtime = resolve(_real_cfg(), _settings(**REAL, **over), "real")
    if not prompt_roles:
        runtime = dataclasses.replace(runtime, prompt_roles={})  # hành vi TRƯỚC lô này: mọi prompt đi vai file khai
    clock = FakeClock()
    llm = ScriptedLLM({pid: _script(reply) for pid, reply in OK_REPLY.items()}, clock=clock)
    gw = make_gateway(runtime=runtime, providers={"cloud_a": llm}, store=store, clock=clock)
    gw.llm = llm  # `make_gateway` tự dựng một ScriptedLLM riêng; provider nhận request ở đây mới là cái cần đếm
    return gw


def _expected_model(pid: str, chat_model: str | None) -> str:
    return chat_model if chat_model and pid in CHAT_PROMPT_ROLES else BASE_MODEL[DECLARED[pid]]


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_model", [None, "", PRO], ids=["chat-model-none", "chat-model-trong", "chat-model-v4-pro"])
@pytest.mark.parametrize("pid", sorted(DECLARED))
async def test_each_prompt_calls_the_expected_model(pid: str, chat_model: str | None) -> None:
    gw = _gateway(chat_model)
    registry_prompt = load_prompts(PROMPTS).get(pid)
    _, meta = await gw.client.complete(DECLARED[pid], pid, _vars(pid), registry_prompt.schema)
    want = _expected_model(pid, chat_model)
    assert [c.model for c in gw.llm.calls_for(pid)] == [want]  # model thật gửi tới provider
    assert meta.model == want
    assert [(r.prompt_id, r.model) for r in gw.store.rows] == [(pid, want)]  # llm_calls ghi đúng tên model thật
    assert gw.store.spans[0].attributes["role"] == DECLARED[pid]  # thuộc tính cũ giữ nghĩa cũ: vai file khai
    assert gw.store.spans[0].attributes["llm_role"] == CHAT_PROMPT_ROLES.get(pid, DECLARED[pid])


@pytest.mark.asyncio
async def test_chat_model_blank_equals_behaviour_before_prompt_roles_for_every_prompt() -> None:
    """CHAT_MODEL trống: mỗi prompt gọi đúng model của fast/strong — so từng prompt id với bản KHÔNG có prompt_roles."""
    new, old = _gateway(None), _gateway(None, prompt_roles=False)
    for pid in sorted(DECLARED):
        schema = load_prompts(PROMPTS).get(pid).schema
        _, a = await new.client.complete(DECLARED[pid], pid, _vars(pid), schema)
        _, b = await old.client.complete(DECLARED[pid], pid, _vars(pid), schema)
        assert (a.provider, a.model, a.model_version) == (b.provider, b.model, b.model_version), pid
        assert [c.model for c in new.llm.calls_for(pid)] == [c.model for c in old.llm.calls_for(pid)] == [BASE_MODEL[DECLARED[pid]]]


@pytest.mark.asyncio
async def test_cache_key_distinguishes_the_chat_model() -> None:
    store = MemoryLlmStore()
    flash, pro = _gateway(None, store=store), _gateway(PRO, store=store)
    args = ("fast", "b10_need_type", _vars("b10_need_type"), NeedTypeOut)
    _, m1 = await flash.client.complete(*args)
    _, m2 = await pro.client.complete(*args)  # cùng prompt, cùng biến, khác model → KHÔNG trúng cache của flash
    assert (m1.cache_hit, m1.model) == (False, "m-fast")
    assert (m2.cache_hit, m2.model) == (False, PRO) and len(pro.llm.calls_for("b10_need_type")) == 1
    _, m3 = await pro.client.complete(*args)
    _, m4 = await flash.client.complete(*args)
    assert (m3.cache_hit, m3.model) == (True, PRO) and (m4.cache_hit, m4.model) == (True, "m-fast")
    assert [(r.model, r.cache_hit) for r in store.rows] == [("m-fast", False), (PRO, False), (PRO, True), ("m-fast", True)]


@pytest.mark.asyncio
async def test_blank_chat_model_keeps_the_pre_change_cache_entries() -> None:
    """Deploy mà không đặt CHAT_MODEL không làm mất cache đã có: khoá cache của prompt hội thoại y hệt bản trước lô này."""
    store = MemoryLlmStore()
    before, after = _gateway(None, store=store, prompt_roles=False), _gateway(None, store=store)
    args = ("fast", "b10_need_type", _vars("b10_need_type"), NeedTypeOut)
    _, first = await before.client.complete(*args)
    _, second = await after.client.complete(*args)
    assert (first.cache_hit, second.cache_hit) == (False, True) and len(after.llm.calls_for("b10_need_type")) == 0


@pytest.mark.asyncio
async def test_timeout_and_retries_follow_the_effective_role() -> None:
    """Lời gọi hỏng (503) — số lần thử và timeout mỗi lần theo vai THỰC SỰ dùng: b03 → chat_fast (3 lần × 12 s), b10_answer → chat_strong
    (2 lần × 25 s), còn b02 giữ fast (4 lần × 8 s)."""
    runtime = resolve(_real_cfg(), _settings(**REAL), "real")
    clock = FakeClock()
    llm = ScriptedLLM({"b03_classify": [Http(503)] * 3, "b10_answer": [Http(503)] * 2, "b02_injection_judge": [Http(503)] * 4},
                      clock=clock)  # fmt: skip
    gw = make_gateway(runtime=runtime, providers={"cloud_a": llm}, clock=clock)
    registry = load_prompts(PROMPTS)
    for pid in ("b03_classify", "b10_answer", "b02_injection_judge"):
        with pytest.raises(LLMUnavailable):
            await gw.client.complete(DECLARED[pid], pid, _vars(pid), registry.get(pid).schema)
    assert [(c.attempt, c.timeout_s) for c in llm.calls_for("b03_classify")] == [(0, 12), (1, 12), (2, 12)]
    assert [(c.attempt, c.timeout_s) for c in llm.calls_for("b10_answer")] == [(0, 25), (1, 25)]
    assert [(c.attempt, c.timeout_s) for c in llm.calls_for("b02_injection_judge")] == [(0, 8), (1, 8), (2, 8), (3, 8)]


@pytest.mark.asyncio
async def test_chat_strong_never_falls_back_even_if_a_chain_is_built_by_hand() -> None:
    """P2 mục 5: strong KHÔNG fallback. Vai chat_strong (b10_answer) cũng vậy — kể cả khi chuỗi đích dựng tay có đích thứ hai."""
    runtime = resolve(_real_cfg(), _settings(**REAL), "real")
    first = runtime.chains["chat_strong"][0]
    second = dataclasses.replace(first, provider="cloud_b", model="m-b")
    runtime = dataclasses.replace(runtime, chains={**runtime.chains, "chat_strong": (first, second)})
    clock = FakeClock()
    a = ScriptedLLM({"b10_answer": [Http(503)] * 2}, clock=clock)
    b = ScriptedLLM({"b10_answer": [Reply(OK_REPLY["b10_answer"])]}, clock=clock)
    gw = make_gateway(runtime=runtime, providers={"cloud_a": a, "cloud_b": b}, clock=clock)
    with pytest.raises(LLMUnavailable):
        await gw.client.complete("strong", "b10_answer", _vars("b10_answer"), AnswerOut)
    assert len(a.calls) == 2 and b.calls == []
    assert gw.store.rows[0].used_fallback is False


# ---- E. trần token và cắt trim_vars theo vai SAU prompt_roles --------------------------------------------------

LONG = (("VPN báo lỗi 809 trên máy LAP-0342 ở nhà " * 120)[:4000]).rstrip()  # 4000 ký tự = TEXT_MAX
TEXT_VAR = {"b03_classify": "redacted_request", "b10_need_type": "text", "b11_clarify_question": "user_request",
            "b11_extract_slots": "text", "b10_answer": "question", "b09_rewrite_query": "question"}  # fmt: skip
OLD_BUDGET = {"fast": 2000, "strong": 6000}  # trần TRƯỚC lô này của vai file khai


def _cost(trimmed_or_error: Callable[[], int]) -> float:
    """Số ký tự bị cắt; không cắt được mà vượt trần (LLMBudgetExceeded) = vô cùng."""
    try:
        return trimmed_or_error()
    except LLMBudgetExceeded:
        return math.inf


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_model", [None, PRO], ids=["chat-model-trong", "chat-model-v4-pro"])
@pytest.mark.parametrize("pid", sorted(CHAT_PROMPT_ROLES))
async def test_conversation_prompts_do_not_cut_more_than_before(pid: str, chat_model: str | None) -> None:
    prompt = load_prompts(PROMPTS).get(pid)
    variables = _vars(pid, **{TEXT_VAR[pid]: LONG})
    old = _cost(lambda: render(prompt, variables, budget_in=OLD_BUDGET[prompt.spec.role]).trimmed_chars)
    gw = _gateway(chat_model)

    async def via_client() -> int:
        _, meta = await gw.client.complete(DECLARED[pid], pid, variables, prompt.schema)
        return meta.trimmed_chars

    try:
        new = float(await via_client())
    except LLMBudgetExceeded:
        new = math.inf
    assert new <= old, (pid, new, old)
    chat_budget = load_llm_config(LLM_YAML).roles[CHAT_PROMPT_ROLES[pid]].budget_in  # type: ignore[index]
    assert new == _cost(lambda: render(prompt, variables, budget_in=chat_budget).trimmed_chars)  # cắt theo trần của vai CHAT


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_model", [None, PRO], ids=["chat-model-trong", "chat-model-v4-pro"])
async def test_b03_request_of_4000_chars_is_cut_less_under_chat_fast(chat_model: str | None) -> None:
    """Trần tính theo vai chat_fast (3000), không theo `role: fast` trong file prompt (2000): câu 4000 ký tự bị cắt ÍT hơn trước."""
    prompt = load_prompts(PROMPTS).get("b03_classify")
    variables = _vars("b03_classify", redacted_request=LONG)
    at_2000 = render(prompt, variables, budget_in=2000).trimmed_chars
    gw = _gateway(chat_model)
    _, meta = await gw.client.complete("fast", "b03_classify", variables, prompt.schema)
    assert at_2000 > 1000 and meta.trimmed_chars < at_2000
    assert meta.trimmed_chars == render(prompt, variables, budget_in=3000).trimmed_chars


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_model", [None, PRO], ids=["chat-model-trong", "chat-model-v4-pro"])
async def test_b02_judge_keeps_fast_budget_and_behaviour(chat_model: str | None) -> None:
    prompt = load_prompts(PROMPTS).get("b02_injection_judge")

    def over_2000(n: int) -> bool:
        return _cost(lambda: render(prompt, {"text": "a" * n}, budget_in=2000).est_tokens) == math.inf

    lo, hi = 1, 20_000  # độ dài nhỏ nhất làm b02 vượt trần 2000 (b02 không có trim_vars → vượt là ném)
    while lo < hi:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if over_2000(mid) else (mid + 1, hi)
    first_over = lo
    assert not over_2000(first_over - 1) and render(prompt, {"text": "a" * first_over}, budget_in=3000).est_tokens <= 3000
    gw = _gateway(chat_model)
    _, meta = await gw.client.complete("fast", "b02_injection_judge", {"text": "a" * (first_over - 1)}, prompt.schema,
                                       cache_policy="bypass")  # fmt: skip
    assert meta.model == "m-fast"
    with pytest.raises(LLMBudgetExceeded):  # vẫn trần 2000 của fast: KHÔNG được nới theo chat_fast
        await gw.client.complete("fast", "b02_injection_judge", {"text": "a" * first_over}, prompt.schema, cache_policy="bypass")
    assert len(gw.llm.calls_for("b02_injection_judge")) == 1  # lời gọi vượt trần không gửi request nào


# ---- E2. health / llm-status: CHAT_MODEL vào kiểm giá, không đổi hợp đồng API ----------------------------------------------


def test_health_llm_targets_include_chat_model_only_when_set() -> None:
    from app.main import llm_targets

    cfg = load_llm_config(LLM_YAML)
    assert llm_targets(cfg, _settings(fast_model="a", strong_model="b")) == ("a", "b")  # trống: vai chat mượn đích của vai gốc
    assert llm_targets(cfg, _settings(fast_model="a", strong_model="b", chat_model="c")) == ("a", "b", "c", "c")


def test_llm_status_models_still_reports_fast_and_strong_only() -> None:
    from app.api.llm_status import Models, _models

    cfg = load_llm_config(LLM_YAML)
    settings = _settings(llm_backend="real", fast_model="a", strong_model="b", chat_model="c")
    assert _models(cfg, settings) == Models(fast="a", strong="b")


# ---- F. compose, .env.example -------------------------------------------------------------------------------


def test_compose_passes_chat_model_to_backend_and_worker() -> None:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["x-backend-env"]["CHAT_MODEL"] == "${CHAT_MODEL:-}"
    for name in ("backend", "worker"):
        assert compose["services"][name]["environment"]["CHAT_MODEL"] == "${CHAT_MODEL:-}", name
    assert "CHAT_MODEL" not in compose["services"]["mock"]["environment"]


def test_env_example_has_blank_chat_model_with_a_comment() -> None:
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    assert lines.count("CHAT_MODEL=") == 1  # để trống = tắt (hành vi như trước lô này)
    at = lines.index("CHAT_MODEL=")
    assert at > 0 and lines[at - 1].startswith("#") and "CHAT_MODEL" in lines[at - 1]  # chú thích đứng ngay trên
    assert not any(line.startswith("CHAT_MODEL=") and line != "CHAT_MODEL=" for line in lines)
