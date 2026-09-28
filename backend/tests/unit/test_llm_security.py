"""Soát bảo mật LLM gateway (PLAN-3d S9 / DỪNG 3) — mỗi test một mục của bảng soát trong PROGRESS.

1. Prompt đầy đủ chỉ vào `prompt_full` khi EVAL_MODE=true; EVAL_MODE bị từ chối ngoài dev/test/staging.
2. Khoá API và base_url không lọt vào repr/str của Settings, provider, client, hay log của SDK (`httpx2` in cả URL).
3. `LLM_BACKEND=real`: không nạp preset, thẻ `[fake:…]` không có tác dụng — request đi thẳng tới provider thật.
4. Trần chi: gọi song song gần trần không vượt trần (giữ chỗ trước mỗi request trả phí); lần sửa schema sau khi chạm
   trần bị chặn.
5. Đích fallback thiếu pricing: 0 request.
6. Dấu phân cách của b02 lấy từ `secrets`, không từ `random`.
8. SDK `openai`/`httpx2` chỉ được import trong `app/llm/providers/openai_compat.py` (import-linter hợp đồng 9 lo phần
   node không import provider/client/wiring/store của llm).
"""

import ast
import asyncio
import json
import logging
import random
import re
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from app.core.clock import FakeClock
from app.llm import context
from app.llm.context import new_boundary
from app.llm.errors import LLMBudgetExceeded, LLMUnavailable
from app.llm.ports import TraceParent
from app.llm.providers.base import ProviderRequest, ProviderResponse
from app.llm.schemas import AnswerOut, InjectionJudgeOut, NeedTypeOut
from app.llm.wiring import check_llm, open_llm
from app.settings import Settings
from pydantic import SecretStr, ValidationError
from tests.fakes.llm import REPO_CONFIG, MemoryLlmStore, make_gateway
from tests.fakes.scripted_llm import Http
from tests.unit.test_llm_client import (
    ANSWER_OK,
    ANSWER_VARS,
    NEED,
    NEED_OK,
    Server,
    ok,
    openai_provider,
    runtime,
    scripted,
    target,
)

APP = Path(__file__).resolve().parents[2] / "app"
CAP = 38.0  # spend.cap_usd của config/llm.yaml
URL_SECRETS = ("PW-URL-bi-mat", "QKEY-bi-mat")
LEAKY_URL = f"http://nguoi:{URL_SECRETS[0]}@llm.test/v1?api-key={URL_SECRETS[1]}"


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg]


# ---- 1. EVAL_MODE chỉ ở môi trường thử nghiệm -----------------------------------------------------------


@pytest.mark.parametrize("env", ["prod", None])
def test_s9_eval_mode_refused_in_prod_or_unset_env(env: str | None) -> None:
    with pytest.raises(ValidationError, match=r"EVAL_MODE=true chỉ dùng được khi APP_ENV"):
        _settings(app_env=env, eval_mode=True)


@pytest.mark.parametrize("env", ["dev", "test", "staging"])
def test_s9_eval_mode_allowed_in_experiment_envs(env: str) -> None:
    assert _settings(app_env=env, eval_mode=True).eval_mode is True
    assert _settings(app_env="prod").eval_mode is False  # mặc định tắt: prod khởi động bình thường


@pytest.mark.asyncio
@pytest.mark.parametrize("eval_mode", [True, False])
async def test_s9_eval_mode_logs_one_warning_at_startup(eval_mode: bool, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    settings = _settings(app_env="test", llm_backend="scripted", eval_mode=eval_mode)
    setup = check_llm(settings)  # backend gọi check_llm 2 lần (create_app + open_runtime) — log nằm ở open_llm
    async with open_llm(setup, settings, engine=cast(Any, object()), clock=FakeClock(), trace=lambda: None):
        pass
    hits = [r for r in caplog.records if "EVAL_MODE=true" in r.getMessage()]
    assert [(r.levelno, r.name) for r in hits] == ([(logging.WARNING, "app.llm.wiring")] if eval_mode else [])


# ---- 2. khoá + base_url không lọt ra repr/str/log ----------------------------------------------------------


def test_s9_settings_repr_and_str_hide_key_and_base_url() -> None:
    s = _settings(llm_api_key=SecretStr("sk-khoa-bi-mat"), llm_base_url=LEAKY_URL)
    for text in (repr(s), str(s)):
        for secret in ("sk-khoa-bi-mat", *URL_SECRETS, "llm.test"):
            assert secret not in text
    assert s.llm_base_url == LEAKY_URL and s.llm_api_key is not None  # vẫn đọc được giá trị khi cần


@pytest.mark.asyncio
async def test_s9_provider_client_repr_and_sdk_logs_hide_key_and_base_url(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    server = Server(ok(NEED_OK))
    provider = openai_provider(server, base_url=LEAKY_URL)  # khoá "k-test"
    gw = make_gateway(runtime=runtime((target("cloud_a"),)), providers={"cloud_a": provider})
    canary = "CANARY-s9-cau-nguoi-dung"
    await gw.client.complete("fast", "b10_need_type", {**NEED, "text": canary}, NeedTypeOut)
    assert len(server.requests) == 1 and URL_SECRETS[1] in str(server.requests[0].url)  # URL thật vẫn dùng đủ
    blob = caplog.text + repr(provider) + str(provider) + repr(gw.client) + repr(gw.store.rows) + repr(gw.store.spans)
    for secret in (*URL_SECRETS, "k-test", canary):
        assert secret not in blob


# ---- 3. LLM_BACKEND=real: thẻ [fake:…] không có tác dụng ------------------------------------------------------


def _real_config_dir(tmp_path: Path) -> Path:
    data = yaml.safe_load((REPO_CONFIG / "llm.yaml").read_text(encoding="utf-8"))
    data["pricing"].update({"m-fast": {"in": 0, "out": 0}, "m-strong": {"in": 0, "out": 0}})  # giá 0: không đọc tổng chi
    (tmp_path / "llm.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    shutil.copytree(REPO_CONFIG / "prompts", tmp_path / "prompts")
    shutil.copytree(REPO_CONFIG / "scripted", tmp_path / "scripted")  # preset có trên đĩa — real vẫn không nạp
    return tmp_path


@pytest.mark.asyncio
async def test_s9_real_backend_ignores_fake_tag_and_goes_to_real_provider(tmp_path: Path) -> None:
    settings = _settings(app_env="prod", llm_backend="real", fast_model="m-fast", strong_model="m-strong",
                         llm_base_url="http://llm.test/v1", llm_api_key=SecretStr("k"),
                         config_dir=_real_config_dir(tmp_path))  # fmt: skip
    setup = check_llm(settings)
    assert setup.presets is None and setup.runtime.backend == "real"
    no_db = cast(Any, object())  # engine giả: mọi truy cập DB đều lỗi (ghi trace lỗi chỉ log, không làm hỏng lời gọi)
    async with open_llm(setup, settings, engine=no_db, clock=FakeClock(),
                        trace=lambda: TraceParent("turn-s9", "a" * 32, None)) as client:  # fmt: skip
        with pytest.raises(RuntimeError, match="test không được ra mạng: POST tới llm.test"):
            await client.complete("fast", "b02_injection_judge", {"text": "[fake:vpn_demo] quên mật khẩu"},
                                  InjectionJudgeOut)  # fmt: skip


# ---- 4. trần chi: song song gần trần, sửa schema sau khi chạm trần ---------------------------------------------


class GateProvider:
    """Provider trả phí giữ mọi request ở cửa cho tới khi `gate` mở — mọi lời gọi được cho qua đều đang bay cùng lúc."""

    def __init__(self, content: dict[str, Any]) -> None:
        self.content = content
        self.entered = 0
        self.gate = asyncio.Event()

    async def chat(self, req: ProviderRequest) -> ProviderResponse:
        self.entered += 1
        await self.gate.wait()
        return ProviderResponse(content=json.dumps(self.content), tokens_in=None, tokens_out=None, model_version=None)


@pytest.mark.asyncio
async def test_s9_parallel_calls_near_cap_never_exceed_cap() -> None:
    n = 6
    base = CAP - 0.0025  # đủ cho 1–2 request strong (≤ 900 token ra + ước tính token vào), không đủ cho 6
    store = MemoryLlmStore(base_spend=base)
    provider = GateProvider(ANSWER_OK)
    gw = make_gateway(runtime=runtime((target("cloud_a"),)), providers={"cloud_a": provider}, store=store)  # type: ignore[dict-item]
    tasks = [asyncio.create_task(gw.client.complete("strong", "b10_answer", {**ANSWER_VARS, "question": f"câu {i}"},
                                                    AnswerOut)) for i in range(n)]  # fmt: skip
    for _ in range(50):
        await asyncio.sleep(0)
    admitted = provider.entered
    provider.gate.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert 1 <= admitted < n
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(refused) == n - admitted and all(isinstance(r, LLMBudgetExceeded) for r in refused)
    assert base + sum(r.cost_usd for r in store.rows) <= CAP


@pytest.mark.asyncio
async def test_s9_schema_repair_after_cap_reached_is_blocked() -> None:
    server = Server(ok("không phải JSON", tokens=(1000, 1000)), ok(NEED_OK))  # lần 1 tốn 0,00125 USD → vượt trần
    store = MemoryLlmStore(base_spend=CAP - 0.001)
    gw = make_gateway(runtime=runtime((target("cloud_a"),)), providers={"cloud_a": openai_provider(server)},
                      store=store)  # fmt: skip
    with pytest.raises(LLMBudgetExceeded):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert len(server.requests) == 1  # không có request sửa schema
    (row,) = store.rows
    assert row.cost_usd == pytest.approx(0.00125) and row.json_valid_first_try is False


@pytest.mark.asyncio
async def test_s9_failed_attempts_release_reservation() -> None:
    store = MemoryLlmStore(base_spend=CAP - 0.001)  # đủ giữ chỗ 1–2 request fast: lần thử lỗi không nhả chỗ → lần 3 bị chặn
    flaky = scripted("cloud_a", Http(503))
    gw = make_gateway(runtime=runtime((target("cloud_a"),)), providers={"cloud_a": flaky}, store=store)
    with pytest.raises(LLMUnavailable):  # 4 lần thử đều được giữ chỗ rồi nhả — không lần nào bị chặn vì "đầy chỗ"
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert len(flaky.calls) == 4 and "spend_over" not in " ".join(gw.store.spans[0].attributes["failures"])


# ---- 5. fallback thiếu pricing: 0 request -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_s9_unpriced_fallback_gets_zero_requests() -> None:
    a = scripted("cloud_a", Http(503))
    server = Server(ok(NEED_OK))
    rt = runtime((target("cloud_a"), target("cloud_b", None)))
    gw = make_gateway(runtime=rt, providers={"cloud_a": a, "cloud_b": openai_provider(server, name="cloud_b")})
    with pytest.raises(LLMUnavailable):
        await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    assert len(a.calls) == 4 and server.requests == []


# ---- 6. dấu phân cách: secrets, không random ---------------------------------------------------------------


def _imports(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_s9_boundary_from_secrets_not_random() -> None:
    random.seed(0)
    first = new_boundary()
    random.seed(0)
    assert new_boundary() != first  # gieo lại random không lặp lại được dấu
    assert re.fullmatch(r"[0-9a-f]{16}", first)  # 64 bit
    imported = _imports(Path(context.__file__))
    assert "secrets" in imported and "random" not in imported


# ---- 8. SDK chỉ ở provider ----------------------------------------------------------------------------------


def test_s9_only_openai_compat_imports_llm_sdk() -> None:
    allowed = {APP / "llm" / "providers" / "openai_compat.py"}
    offenders = sorted(str(p.relative_to(APP)) for p in APP.rglob("*.py")
                       if p not in allowed and _imports(p) & {"openai", "httpx2"})  # fmt: skip
    assert offenders == []
