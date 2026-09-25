"""Cấu hình từ env — docs/spec/build/01-kien-truc-project.md mục 5.1.

Bí mật để SecretStr (không in ra log/repr). Biến LLM để trống tới mốc G (decisions.md mục 4).
Tên model, giá, prompt KHÔNG nằm ở đây — thuộc config/llm.yaml (P2).

File env: `APP_ENV_FILE` (mặc định `.env`, tính từ thư mục đang chạy); đặt RỖNG để tắt hẳn —
khi đó chỉ đọc biến môi trường. `conftest.py` ở gốc repo đặt rỗng trước khi import app, để test
không bao giờ đọc (hay stat) file `.env` thật.
"""

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def env_file_from_env() -> str | None:
    """Đường dẫn file env theo `APP_ENV_FILE`; rỗng → None (tắt đọc file)."""
    return os.environ.get("APP_ENV_FILE", ".env") or None


class Settings(BaseSettings):
    # env_file đọc lúc import module: đổi APP_ENV_FILE sau khi đã import app.settings thì không ăn.
    # env_ignore_empty: `LLM_API_KEY=` (để trống tới mốc G) được hiểu là chưa đặt → None.
    model_config = SettingsConfigDict(
        env_file=env_file_from_env(), env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True
    )

    # ---- Bí mật ----
    llm_api_key: SecretStr | None = None
    jwt_signing_key: SecretStr | None = None
    mfa_enc_key: SecretStr | None = None
    svc_executor_token: SecretStr | None = None

    # ---- Hạ tầng ----
    database_url: str = "postgresql+psycopg://app_rw@localhost:5432/servicedesk"  # role app_rw
    migrate_database_url: str | None = None  # role app_migrate — chỉ Alembic dùng
    qdrant_url: str = "http://localhost:6333"
    ml_service_url: str = "http://localhost:8200"
    mock_url: str = "http://localhost:8100"
    db_pool_size: int = Field(default=10, ge=1)
    graph_concurrency: int = Field(default=8, ge=1)  # P1 mục 7
    lock_pool_size: int | None = Field(default=None, ge=1)  # mặc định GRAPH_CONCURRENCY + 2 (D-19)
    ticket_lock_timeout: float = Field(default=5.0, gt=0)  # giây; SET lock_timeout trên lock pool
    health_timeout: float = Field(default=2.0, gt=0)  # giây mỗi phụ thuộc ở /api/health

    # ---- Cờ thực nghiệm ----
    eval_mode: bool = False
    enable_proactive_diagnosis: bool = True  # B06 mục 7: mặc định true
    strategy: Literal["manual", "full_auto", "rule_only", "llm_only", "hybrid", "hybrid_guarded"] = (
        "hybrid"
    )
    llm_cache_mode: Literal["default", "eval", "bypass"] = "default"  # P2 mục 8
    rediagnose_on_new_slot: bool = False  # D-20: tắt mặc định

    @model_validator(mode="after")
    def _default_lock_pool(self) -> "Settings":
        if self.lock_pool_size is None:
            self.lock_pool_size = self.graph_concurrency + 2
        return self

    @property
    def effective_lock_pool_size(self) -> int:
        assert self.lock_pool_size is not None
        return self.lock_pool_size


@lru_cache
def get_settings() -> Settings:
    return Settings()
