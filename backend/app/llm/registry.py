"""Prompt registry (P2 mục 6; phase3 mục 7.4; PLAN-3d Q-3d-5).

`config/prompts/<id>.yaml` là nguồn DUY NHẤT của `role`, `schema`, `cache` và danh sách biến của một prompt: node
truyền lệch → `PromptContractError` (client). Kiểm lúc nạp (backend/worker từ chối khởi động nếu sai): tên file = `id`,
schema có trong `llm/schemas.SCHEMAS`, biến dùng trong template == `allowed_vars` (không thừa, không thiếu), không còn
`{{`/`}}` lạc. `sha256` của NỘI DUNG FILE đi vào `llm_calls.prompt_hash` (P2 mục 6). Mỗi lần sửa nội dung → tăng
`version` (phase3 mục 7.4).
"""

import hashlib
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.llm.errors import PromptContractError
from app.llm.schemas import SCHEMAS

PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")
BOUNDARY_VAR = "boundary"  # do renderer sinh ngẫu nhiên mỗi lần gọi (`random_boundary`), node không truyền


class PromptSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    version: int = Field(ge=1)
    role: Literal["fast", "strong"]
    schema_name: str = Field(alias="schema")
    allowed_vars: tuple[str, ...]
    # Biến CHUỖI chữ người dùng mà context builder được cắt đuôi khi khung + biến vượt `budget_in` của vai trò (sau khi hết khối bằng
    # chứng / tin nhắn để cắt). Mặc định rỗng: vượt trần → `LLMBudgetExceeded` như cũ. Trần không khai ở đây — chỉ ở `config/llm.yaml`.
    trim_vars: tuple[str, ...] = ()
    cache: Literal["default", "bypass"]
    # Văn bản người dùng đặt giữa hai dấu phân cách sinh ngẫu nhiên mỗi lần gọi (b02_injection_judge, 7.4)
    random_boundary: bool = False
    system: str = Field(min_length=1)
    user: str = Field(min_length=1)

    @model_validator(mode="after")
    def _template_matches_vars(self) -> "PromptSpec":
        if self.schema_name not in SCHEMAS:
            raise ValueError(f"schema {self.schema_name!r} không có trong app/llm/schemas.py")
        if len(set(self.allowed_vars)) != len(self.allowed_vars):
            raise ValueError("allowed_vars có tên trùng")
        if BOUNDARY_VAR in self.allowed_vars:
            raise ValueError(f"{BOUNDARY_VAR!r} do renderer sinh, không được nằm trong allowed_vars")
        if stray_trim := sorted(set(self.trim_vars) - set(self.allowed_vars)):
            raise ValueError(f"trim_vars {stray_trim} không nằm trong allowed_vars")
        text = self.system + "\n" + self.user
        used = set(PLACEHOLDER.findall(text))
        expected = set(self.allowed_vars) | ({BOUNDARY_VAR} if self.random_boundary else set())
        if used != expected:
            raise ValueError(
                f"biến template {sorted(used)} ≠ allowed_vars{' + boundary' if self.random_boundary else ''} "
                f"{sorted(expected)}"
            )
        stray = PLACEHOLDER.sub("", text)
        if "{{" in stray or "}}" in stray:
            raise ValueError("template có '{{' hoặc '}}' không phải biến hợp lệ")
        return self


@dataclass(frozen=True)
class Prompt:
    spec: PromptSpec
    schema: type[BaseModel]
    sha256: str  # sha256 nội dung file → llm_calls.prompt_hash

    @property
    def id(self) -> str:
        return self.spec.id

    @property
    def version(self) -> str:
        return str(self.spec.version)  # llm_calls/lineage.prompt_version VARCHAR(16)


def load_prompt(path: Path) -> Prompt:
    raw = path.read_bytes()
    try:
        spec = PromptSpec.model_validate(yaml.safe_load(raw.decode("utf-8")))
    except ValueError as e:
        raise ValueError(f"{path.name}: {e}") from e
    if spec.id != path.stem:
        raise ValueError(f"{path.name}: id {spec.id!r} phải trùng tên file")
    return Prompt(spec, SCHEMAS[spec.schema_name], hashlib.sha256(raw).hexdigest())


class PromptRegistry:
    def __init__(self, prompts: Mapping[str, Prompt]) -> None:
        self._prompts = dict(prompts)

    def get(self, prompt_id: str) -> Prompt:
        try:
            return self._prompts[prompt_id]
        except KeyError:
            raise PromptContractError(f"prompt {prompt_id!r} không có trong config/prompts") from None

    def __iter__(self) -> Iterator[Prompt]:
        return iter(self._prompts.values())

    def __len__(self) -> int:
        return len(self._prompts)


def load_prompts(directory: Path) -> PromptRegistry:
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise ValueError(f"không có file prompt nào trong {directory}")
    return PromptRegistry({(p := load_prompt(path)).id: p for path in paths})
