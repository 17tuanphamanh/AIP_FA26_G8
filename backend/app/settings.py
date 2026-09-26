"""Cấu hình — docs/spec/build/01-kien-truc-project.md mục 5.

- Env (`Settings`): bí mật, hạ tầng, cờ thực nghiệm, tham số vận hành. Bí mật để SecretStr
  (không in ra log/repr). Biến LLM để trống tới mốc G (decisions.md mục 4).
- `config/policy.json` (`get_policy`): hằng số nghiệp vụ [Chốt 01 mục 5.2]; sai schema → không khởi động.
- `config/slots.yaml` (`get_slots`): `tool_arg_slots` (D-20); `required_slots` thêm ở Phase 3 (B11).
Tên model, giá, prompt KHÔNG nằm ở đây — thuộc config/llm.yaml (P2).

File env: `APP_ENV_FILE` (mặc định `.env`, tính từ thư mục đang chạy); đặt RỖNG để tắt hẳn —
khi đó chỉ đọc biến môi trường. `conftest.py` ở gốc repo đặt rỗng trước khi import app, để test
không bao giờ đọc (hay stat) file `.env` thật.
"""

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
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
    # Token dịch vụ (P6 mục 3, D-03): mock kiểm ở header X-Service-Token.
    svc_agent_token: SecretStr | None = None  # tool đọc (B6, B11), đăng nhập qua AD
    svc_executor_token: SecretStr | None = None  # DUY NHẤT có quyền ghi (B17)
    svc_worker_token: SecretStr | None = None  # worker phát sự kiện timeout (Phase 2)

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
    graph_recursion_limit: int = Field(default=60, ge=10)  # P1 mục 7: lưới cuối sau MAX_LOOPS
    checkpoint_pool_size: int = Field(default=10, ge=1)  # pool psycopg của AsyncPostgresSaver
    # ---- Worker (P1 mục 7) ----
    worker_deadline_scan_seconds: float = Field(default=15.0, gt=0)  # quét hạn chờ
    worker_recover_scan_seconds: float = Field(default=60.0, gt=0)  # quét lượt dở dang
    worker_stale_turn_seconds: float = Field(default=120.0, gt=0)  # lượt mở quá 2 phút → recover
    worker_batch: int = Field(default=200, ge=1)
    # Heartbeat (app/heartbeat.py): worker ghi file định kỳ; healthcheck compose: quá MAX_AGE = unhealthy.
    worker_heartbeat_path: Path = Path("/tmp/servicedesk-worker.heartbeat")
    worker_heartbeat_seconds: float = Field(default=10.0, gt=0)
    worker_heartbeat_max_age: float = Field(default=60.0, gt=0)
    config_dir: Path = Path(__file__).resolve().parents[2] / "config"  # repo: ./config; image: /srv/config

    # ---- Circuit breaker theo hệ thống ngoài [Chốt 17.3, P5 mục 6] ----
    breaker_failure_threshold: int = Field(default=5, ge=1)  # lỗi liên tiếp …
    breaker_window_seconds: float = Field(default=60.0, gt=0)  # … trong cửa sổ này → mở
    breaker_open_seconds: float = Field(default=30.0, gt=0)  # mở bao lâu rồi half-open

    # ---- Xác thực (P6 mục 4; B01 mục 7 [Đề xuất]) ----
    # MAX_AUTH_FAILURES và cửa sổ 10 phút là hằng số nghiệp vụ → ở config/policy.json, không ở đây.
    access_ttl_minutes: int = Field(default=15, ge=1)
    refresh_ttl_hours: int = Field(default=8, ge=1)  # hạn tuyệt đối từ lúc đăng nhập, không trượt
    lockout_minutes: int = Field(default=15, ge=1)
    ip_failure_limit: int = Field(default=20, ge=1)  # lượt thất bại theo dải IP …
    ip_failure_window_minutes: int = Field(default=10, ge=1)  # … trong cửa sổ này → 429
    reauth_minutes: int = Field(default=10, ge=1)  # xác nhận lại: đăng nhập trong N phút gần nhất
    revocation_cache_seconds: float = Field(default=30.0, ge=0)  # thu hồi có hiệu lực ≤ N giây

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

    @model_validator(mode="after")
    def _heartbeat_margin(self) -> "Settings":
        # Ít nhất 3 nhịp trong một MAX_AGE: một nhịp trễ không làm worker bị báo unhealthy oan.
        if self.worker_heartbeat_seconds * 3 > self.worker_heartbeat_max_age:
            raise ValueError("WORKER_HEARTBEAT_SECONDS phải ≤ WORKER_HEARTBEAT_MAX_AGE / 3")
        return self

    @property
    def effective_lock_pool_size(self) -> int:
        assert self.lock_pool_size is not None
        return self.lock_pool_size


@lru_cache
def get_settings() -> Settings:
    return Settings()


# ---- config/policy.json ----------------------------------------------------------------------


class PolicyConstants(BaseModel):
    """Hằng số nghiệp vụ [Chốt 01 mục 5.2]. Thêm `AUTH_FAILURE_WINDOW_MINUTES` = cửa sổ 10 phút
    đi kèm `MAX_AUTH_FAILURES` (5 lần/10 phút — P6 mục 4)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    MAX_LOOPS: int = Field(ge=1)
    MAX_CLARIFICATION_TURNS: int = Field(ge=1)
    TOOL_RETRY: int = Field(ge=0)
    BACKOFF_BASE_SECONDS: float = Field(gt=0)
    MAX_AUTH_FAILURES: int = Field(ge=1)
    AUTH_FAILURE_WINDOW_MINUTES: int = Field(ge=1)
    SLA_MINUTES: int = Field(ge=1)
    THRESHOLD_LOW: float = Field(ge=0, le=1)
    THRESHOLD_HIGH: float = Field(ge=0, le=1)
    RETRIEVAL_THRESHOLD: float = Field(ge=0, le=1)
    CLARIFY_TIMEOUT_HOURS: int = Field(ge=1)
    CONFIRM_TIMEOUT_HOURS: int = Field(ge=1)

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> "PolicyConstants":
        if not self.THRESHOLD_LOW < self.THRESHOLD_HIGH:
            raise ValueError("THRESHOLD_LOW phải nhỏ hơn THRESHOLD_HIGH")
        return self


class PolicyFile(BaseModel):
    """Schema của policy.json. Phase 3 thêm `rules` (20 luật), `thresholds`, `cost_matrix`… (B12–B14
    mục 7) — tới lúc đó khoá lạ bị từ chối để không ai tưởng luật đã có hiệu lực."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    constants: PolicyConstants


def load_policy(path: Path) -> PolicyFile:
    return PolicyFile.model_validate(json.loads(path.read_text(encoding="utf-8")))


@lru_cache
def get_policy() -> PolicyFile:
    return load_policy(get_settings().config_dir / "policy.json")


# ---- config/slots.yaml -----------------------------------------------------------------------


class SlotsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_arg_slots: frozenset[str] = Field(min_length=1)  # TOOL_ARG_SLOTS (D-20)


def load_slots(path: Path) -> SlotsFile:
    return SlotsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_slots() -> SlotsFile:
    return load_slots(get_settings().config_dir / "slots.yaml")
