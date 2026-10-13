"""T20b — ScriptedLLM cho ticket con trên stack (phase5 P13; 5.2.8 h1, h2). Viết TỪ ĐẶC TẢ trước code (không đọc thân
`child_preset`). Phần `SqlPresetResolver` trên Postgres thật: `tests/integration/test_t20b_pg.py`.

- h1: `child_preset(thẻ cha, child_id)` = `<thẻ cha>-<i>`; cha không thẻ → None (preset `default`). Preset con thiếu → `ScriptExhausted`
  (E9 thấy được — hành vi `PresetScriptedLLM` đã có, ghim).
- h2: mọi preset `config/scripted/*.yaml` cùng tập khoá với `default.yaml`, `b14_*` không đổi giá trị (P14) — kể cả preset con mới
  (`tcNN-<i>`) khi DỪNG 2 thêm.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from app.llm.errors import ScriptExhausted
from app.llm.ports import TraceParent
from app.llm.providers.base import ProviderRequest
from app.llm.providers.scripted import PresetScriptedLLM, child_preset, load_presets
from tests.fakes.llm import repo_registry

CHO_DUNG2 = frozenset({"test_h1_child_preset_parent_tag_plus_index"})

SCRIPTED = Path(__file__).resolve().parents[3] / "config" / "scripted"


@pytest.fixture(autouse=True)
def _cho_dung2(request: pytest.FixtureRequest) -> None:
    if request.node.originalname in CHO_DUNG2:
        request.applymarker(pytest.mark.xfail(strict=True, raises=(AssertionError, NotImplementedError), reason="T20b DỪNG 2"))


@pytest.mark.parametrize(
    ("tag", "cid", "preset"),
    [
        pytest.param("tc34", "T1-2", "tc34-2", id="tc34-con-2"),
        pytest.param("tc35", "T1-1", "tc35-1", id="tc35-con-1"),
        pytest.param("tc34", "abc-def-3", "tc34-3", id="cha-co-gach"),
        pytest.param(None, "T1-2", None, id="cha-khong-the"),
    ],
)
def test_h1_child_preset_parent_tag_plus_index(tag: str | None, cid: str, preset: str | None) -> None:
    """h1 (P13): `[fake:tc34]` → preset `tc34-1`, `tc34-2` (i = đoạn sau dấu "-" cuối); cha không thẻ → None."""
    assert child_preset(tag, cid) == preset


class _Fixed:
    def __init__(self, tag: str | None) -> None:
        self.tag = tag

    async def tag_for(self, trace: TraceParent | None) -> str | None:
        return self.tag


def _req(prompt_id: str) -> Any:
    """`ProviderRequest` tối thiểu: `PresetScriptedLLM.chat` chỉ đọc `prompt_id` + `trace` trước khi ném (không dựng đủ trường)."""
    req = ProviderRequest.__new__(ProviderRequest)
    object.__setattr__(req, "prompt_id", prompt_id)
    object.__setattr__(req, "trace", None)
    return req


@pytest.mark.asyncio
async def test_h1_missing_child_preset_script_exhausted() -> None:
    """h1 (ghim — hành vi đã có): preset con thiếu (`tc34-9`) → `ScriptExhausted` (E9, thấy được), không rơi về `default`."""
    llm = PresetScriptedLLM(load_presets(SCRIPTED, repo_registry()), _Fixed("tc34-9"))
    with pytest.raises(ScriptExhausted):
        await llm.chat(_req("b10_need_type"))


def test_h2_every_preset_same_keys_and_b14_unchanged() -> None:
    """h2 (P14): mọi preset (13 cũ + 9 T24 + preset mới) cùng tập khoá với `default.yaml`; `b14_risk_estimate`/`b14_risk_vote` bằng
    giá trị an toàn của `default.yaml`; nạp được (schema đúng — bộ nạp thật)."""
    default = yaml.safe_load((SCRIPTED / "default.yaml").read_text(encoding="utf-8"))
    presets = load_presets(SCRIPTED, repo_registry())
    for name, data in presets.items():
        assert set(data) == set(default), (name, set(data) ^ set(default))
        assert data["b14_risk_estimate"] == default["b14_risk_estimate"], name
        assert data["b14_risk_vote"] == default["b14_risk_vote"], name
