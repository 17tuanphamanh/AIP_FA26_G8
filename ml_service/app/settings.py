"""Cấu hình ml-service — chỉ đọc biến môi trường, không đọc file env (test không chạm `.env`).

`ML_SERVICE_TOKEN` BẮT BUỘC, không mặc định (3-Q21): thiếu hoặc ngắn hơn 32 ký tự → không khởi động.
`ML_MAX_CONCURRENCY` mặc định 1: torch đã tự đa luồng (`ML_THREADS`), chạy song song nhiều lô trên
4 vCPU chỉ làm các lô tranh CPU rồi cùng timeout (quyết định của người, 3a).
"""

import os
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_TOKEN_LEN = 32  # P6 mục 3: ≥ 32 byte ngẫu nhiên (token_urlsafe(32) dài 43 ký tự)
DEFAULT_LOCK = Path(__file__).resolve().parents[1] / "models.lock.json"


def default_threads() -> int:
    return max(1, (os.cpu_count() or 2) - 1)  # P4 mục 6: số vCPU − 1


class MlSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", env_ignore_empty=True)

    ml_service_token: SecretStr
    models_dir: Path = Path("/models")
    models_lock: Path = DEFAULT_LOCK
    ml_threads: int = Field(default_factory=default_threads, ge=1)
    ml_max_concurrency: int = Field(default=1, ge=1)
    # Model phân loại của nhóm (P11) — Phase 3 chưa nạp; /classify, /classify_intent trả 503.
    guard_model_dir: Path | None = None
    intent_model_dir: Path | None = None

    @field_validator("ml_service_token")
    @classmethod
    def _long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_TOKEN_LEN:
            raise ValueError(f"ML_SERVICE_TOKEN phải dài ≥ {MIN_TOKEN_LEN} ký tự")
        return value
