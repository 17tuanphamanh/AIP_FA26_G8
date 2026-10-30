"""P6 gói tuần 8 (D-67) — chốt preset dữ liệu thử `sim_*` của ScriptedLLM (ĐP soát A + B, điều kiện của `test_gate5.SIM_PRESETS`).

Preset có tên bắt đầu `sim_` (kể cả preset con `sim_…-<i>`) CHỈ dùng được khi APP_ENV ∈ {dev, test} VÀ EVAL_MODE=false — dữ liệu thử
không được lẫn vào lượt đo. Ngoài điều kiện đó → `ScriptExhausted` (lỗi rõ, KHÔNG rơi về preset `default`). Preset gate cũ không đổi.
"""

from typing import Any, ClassVar, cast

import pytest
from app.core.clock import FakeClock
from app.llm import wiring as llm_wiring
from app.llm.errors import ScriptExhausted
from app.llm.ports import TraceParent
from app.llm.providers.scripted import SIM_PREFIX, PresetScriptedLLM, load_presets
from app.llm.schemas import NeedTypeOut
from app.llm.wiring import check_llm, sim_presets_allowed
from app.settings import Settings
from pydantic import SecretStr
from tests.fakes.llm import REPO_CONFIG, make_gateway, repo_registry

TRACE = TraceParent("turn-sim", "s" * 32, None)
NEED = {"text": "đặt lại mật khẩu", "evidence_titles": []}
PRESETS = load_presets(REPO_CONFIG / "scripted", repo_registry())


class _Fixed:
    def __init__(self, tag: str | None) -> None:
        self.tag = tag

    async def tag_for(self, trace: TraceParent | None) -> str | None:
        return self.tag


def _settings(**over: Any) -> Settings:
    values: dict[str, Any] = {"llm_backend": "scripted", "ml_service_token": SecretStr("t" * 32), **over}
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


async def _need(tag: str | None, *, allow_sim: bool) -> str:
    gw = make_gateway(providers={"scripted": PresetScriptedLLM(PRESETS, _Fixed(tag), allow_sim=allow_sim)}, trace=lambda: TRACE)
    out, _ = await gw.client.complete("fast", "b10_need_type", NEED, NeedTypeOut)
    return out.type


def test_sim_preset_exists_with_prefix() -> None:
    assert SIM_PREFIX == "sim_" and "sim_khongluat" in PRESETS


@pytest.mark.parametrize(("app_env", "eval_mode", "allowed"), [
    ("dev", False, True), ("test", False, True),
    ("prod", False, False), ("staging", False, False), (None, False, False),
    ("dev", True, False), ("test", True, False), ("staging", True, False),
])  # fmt: skip
def test_sim_presets_allowed_only_dev_test_without_eval(app_env: str | None, eval_mode: bool, allowed: bool) -> None:
    assert sim_presets_allowed(_settings(app_env=app_env, eval_mode=eval_mode)) is allowed


@pytest.mark.asyncio
@pytest.mark.parametrize("tag", ["sim_khongluat", "sim_khongluat-1", "sim_khong_co"])
async def test_sim_tag_refused_when_not_allowed_not_default(tag: str) -> None:
    """Không được phép → `ScriptExhausted` nêu lý do — không trả phản hồi của `default` (default trả `info`)."""
    with pytest.raises(ScriptExhausted, match=r"dữ liệu thử.*EVAL_MODE=false"):
        await _need(tag, allow_sim=False)


@pytest.mark.asyncio
async def test_sim_tag_used_when_allowed() -> None:
    assert await _need("sim_khongluat", allow_sim=True) == "action"  # đúng preset sim, không phải default (`info`)


@pytest.mark.asyncio
@pytest.mark.parametrize("allow_sim", [False, True])
@pytest.mark.parametrize(("tag", "expected"), [("tc01", "action"), ("tc04", "info"), (None, "info")])
async def test_gate_presets_unaffected(tag: str | None, expected: str, allow_sim: bool) -> None:
    assert await _need(tag, allow_sim=allow_sim) == expected


class _Recorder:
    made: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, presets: Any, resolver: Any, **kwargs: Any) -> None:
        _Recorder.made.append(kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize(("app_env", "eval_mode", "allowed"), [("dev", False, True), ("test", False, True), ("dev", True, False),
                                                              ("test", True, False)])  # fmt: skip
async def test_wiring_passes_allow_sim(monkeypatch: pytest.MonkeyPatch, app_env: str, eval_mode: bool, allowed: bool) -> None:
    """`open_llm` dựng ScriptedLLM với `allow_sim = sim_presets_allowed(settings)` (scripted chỉ khởi động được ở dev/test)."""
    _Recorder.made.clear()
    monkeypatch.setattr(llm_wiring, "PresetScriptedLLM", _Recorder)
    settings = _settings(app_env=app_env, eval_mode=eval_mode)
    async with llm_wiring.open_llm(check_llm(settings), settings, engine=cast(Any, object()), clock=FakeClock(),
                                   trace=lambda: TRACE):  # fmt: skip
        pass
    assert _Recorder.made == [{"allow_sim": allowed}]
