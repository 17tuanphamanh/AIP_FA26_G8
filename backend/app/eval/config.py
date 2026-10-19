"""Cấu hình một lượt chạy trên stack + `run_id` (P8 §5.1) cho harness G2.

`run_id = sha256(config_json | dataset_sha256 | git_commit)[:12]`; `config_json` là JSON sắp khoá (thứ tự khoá dict không đổi
`run_id`). TODO(G2-Q4): `--run-id` của CLI chỉ để đối chiếu — khác giá trị tính ra → `RunIdMismatch`.
"""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.eval.predictions import Split

StackStrategy = Literal["hybrid", "llm_only"]  # P8 §5.4 S1/S2. TODO(G2-Q15): S3 = hybrid tắt chẩn đoán (enable_proactive_diagnosis)
ProbMethod = Literal["self_report", "sampling_k5"]  # = P_METHODS (app/db/models.py)
DEFAULT_SEED = 20260925  # P8 §8


class RunConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy: StackStrategy
    split: Split  # TODO(G2-Q3): CV 5 phần gán phần offline — lượt stack đề xuất ghi "test"
    timeout_s: int = Field(gt=0)  # giới hạn mỗi kịch bản (số Tuấn Anh gửi 19/10)
    prob_method: ProbMethod
    llm_roles: dict[str, str]
    enable_proactive_diagnosis: bool = True
    seed: int = DEFAULT_SEED


class RunIdMismatch(ValueError):
    """`--run-id` khác `run_id` tính từ cấu hình + dữ liệu + commit."""


def make_run_id(config: RunConfig, dataset_sha256: str, git_commit: str) -> str:
    config_json = json.dumps(config.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"{config_json}|{dataset_sha256}|{git_commit}".encode()).hexdigest()[:12]


def check_run_id(given: str | None, computed: str) -> None:
    if given is not None and given != computed:
        raise RunIdMismatch("run_id truyền vào khác run_id tính từ cấu hình + dữ liệu + commit")
