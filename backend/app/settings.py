"""Cấu hình — docs/spec/build/01-kien-truc-project.md mục 5.

- Env (`Settings`): bí mật, hạ tầng, cờ thực nghiệm, tham số vận hành. Bí mật để SecretStr
  (không in ra log/repr). Biến LLM để trống tới mốc G (decisions.md mục 4).
- `config/policy.json` (`get_policy`): hằng số nghiệp vụ [Chốt 01 mục 5.2]; sai schema → không khởi động.
- `config/slots.yaml` (`get_slots`): `tool_arg_slots` (D-20); `required_slots` thêm ở Phase 3 (B11).
- `config/escalation_templates.yaml` (`get_escalation_templates`): mẫu thông báo + `next_for_l2` theo mã E
  của B20 (B20 mục 4.2, 7.1) — đủ E0–E9, không chuỗi rỗng.
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

from app.domain.exit_codes import ExitCode


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
    # Header X-Service-Token khi gọi ml-service (3-Q21): BẮT BUỘC ở mọi môi trường — backend và worker
    # từ chối khởi động khi thiếu (`require_ml_token`). None ở đây chỉ để test dựng Settings tự do.
    ml_service_token: SecretStr | None = None

    # ---- Môi trường (2b-Q2, 2b-Q3) ----
    # KHÔNG mặc định: thiếu = coi như môi trường thật → mọi thành phần giả (`NotRedactingGuard`,
    # `FAKE_APPROVER_ID`) bị từ chối lúc khởi động (`require_dev_fakes`). Compose bắt khai báo.
    app_env: Literal["dev", "test", "staging", "prod"] | None = None
    # Người duyệt cố định của node B15 GIẢ (tới Phase 4). Phải có dòng `users` (FK approvals).
    fake_approver_id: str | None = None
    # Stack compose (2b-4): preset node giả mặc định; ĐẶT biến = bật thẻ `[fake:<preset>]` theo ticket
    # (`graph/fakes.StackScenario`). Không đặt → kịch bản mặc định, thẻ bị bỏ qua. Chỉ dev/test.
    fake_scenario: str | None = None
    # Giây dừng ở điểm do preset quyết (kill_b06, kill_b15) — để SIGKILL giữa lượt. Chỉ dev/test.
    fake_node_delay: float | None = Field(default=None, ge=0)

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
    # Worker chạy lại một lượt dở dang tối đa bấy nhiêu lần (turns.recover_attempts, 2b-Q6).
    max_recover_attempts: int = Field(default=3, ge=1)
    # Heartbeat (app/heartbeat.py): worker ghi file định kỳ; healthcheck compose: quá MAX_AGE = unhealthy.
    worker_heartbeat_path: Path = Path("/tmp/servicedesk-worker.heartbeat")
    worker_heartbeat_seconds: float = Field(default=10.0, gt=0)
    worker_heartbeat_max_age: float = Field(default=60.0, gt=0)
    config_dir: Path = Path(__file__).resolve().parents[2] / "config"  # repo: ./config; image: /srv/config
    # RAG ingest (3-Q16): ngoài bản đích alias, giữ N collection `kb_*` mới nhất để quay lui; còn lại bị xoá.
    # Mặc định ở đây, không truyền qua compose.
    rag_keep_old_collections: int = Field(default=2, ge=0)
    # ---- RAG query (3c, mục 3.5) — một nguồn, không lặp hằng ở chỗ khác ----
    rag_prefetch_k: int = Field(default=20, ge=1)  # P3 [Chốt]
    # Q-3a-16 (S9, PLAN-3c mục 6.2): tier ② (threads=4, K=10, fp32) trên CPU dev — trung vị p95 đo được
    # (10,4 s) vẫn > 9 s/9,5 s "đạt", nhưng người quyết định NỚI tiêu chí thực tế là trần 3·T+3<60
    # (T ≤ 18, xem TIMEOUT_S["rerank"]) chứ không phải "≤ 9 s" — xem PROGRESS. Nợ kỹ thuật: đo lại trên
    # máy gaming/staging GPU (N2), đặt lại theo số đo đó.
    rag_rerank_k: int = Field(default=10, ge=1)
    rag_top_n: int = Field(default=5, ge=1)  # [Chốt]
    rag_intent_fallback: bool = True  # D-23
    rag_neighbor_window: int = Field(default=1, ge=0)  # D-24
    rag_evidence_max_tokens: int = Field(default=4000, ge=1)  # B10
    rag_qdrant_timeout_s: float = Field(default=5.0, gt=0)  # timeout mỗi lời gọi AsyncQdrantClient
    rag_deadline_s: float = Field(default=50.0, gt=0)  # Q-3c-4: bọc toàn bộ retrieve/expand_for_answer
    # ---- API ----
    max_request_body_bytes: int = Field(default=64 * 1024, ge=1)  # đếm byte ĐỌC THẬT (2b-3 Q5)
    background_shutdown_seconds: float = Field(default=10.0, ge=0)  # tắt app: chờ lượt nền rồi huỷ

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

    @model_validator(mode="after")
    def _fake_delay_below_stale(self) -> "Settings":
        # Lượt đang ngủ ≥ nửa ngưỡng "lượt dở dang" thì worker dễ coi lượt còn sống là lượt chết.
        if self.fake_node_delay is not None and self.fake_node_delay * 2 >= self.worker_stale_turn_seconds:
            raise ValueError("FAKE_NODE_DELAY phải < WORKER_STALE_TURN_SECONDS / 2")
        return self

    @model_validator(mode="after")
    def _rag_rerank_bounds(self) -> "Settings":
        # 32 = một lô rerank của ml-service (`ml.client.RERANK_MAX_PASSAGES`) — không import `app.ml`
        # ở đây (vòng: ml.client -> tools.retry -> settings); `test_rag_timeouts.py` (c32) đối chiếu.
        rerank_max_passages = 32
        if not 1 <= self.rag_rerank_k <= min(self.rag_prefetch_k, rerank_max_passages):
            raise ValueError(
                "RAG_RERANK_K phải trong [1, min(RAG_PREFETCH_K, 32)]"
            )
        if self.rag_top_n > self.rag_rerank_k:
            raise ValueError("RAG_TOP_N phải <= RAG_RERANK_K")
        return self

    @model_validator(mode="after")
    def _rag_deadline_below_stale(self) -> "Settings":
        # Q-3c-4: lượt truy hồi treo hết deadline vẫn phải xong trước khi worker coi lượt là "dở dang".
        if self.rag_deadline_s >= self.worker_stale_turn_seconds / 2:
            raise ValueError("RAG_DEADLINE_S phải < WORKER_STALE_TURN_SECONDS / 2")
        return self

    @property
    def effective_lock_pool_size(self) -> int:
        assert self.lock_pool_size is not None
        return self.lock_pool_size

    def require_ml_token(self) -> SecretStr:
        """`ML_SERVICE_TOKEN` bắt buộc mọi env (3-Q21, Q-3a-5) — thiếu → từ chối khởi động."""
        if self.ml_service_token is None:
            raise RuntimeError("ML_SERVICE_TOKEN chưa cấu hình (bắt buộc mọi môi trường) — từ chối khởi động")
        return self.ml_service_token

    def require_dev_fakes(self, what: str) -> None:
        """Thành phần giả chỉ được nạp khi `APP_ENV` ∈ {dev, test} — fail-closed (2b-Q2, 2b-Q3)."""
        if self.app_env not in DEV_FAKE_ENVS:
            raise RuntimeError(
                f"{what} chỉ dùng được khi APP_ENV ∈ {sorted(DEV_FAKE_ENVS)} "
                f"(đang là {self.app_env!r}) — từ chối khởi động"
            )


DEV_FAKE_ENVS = frozenset({"dev", "test"})


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
    # 3-Q13: slot nối thêm vào câu truy hồi (build_query). Mặc định rỗng — fixture test cũ (vd.
    # test_tool_registry.py) dựng slots.yaml tối giản không khai báo mục này vẫn nạp được.
    query_slots: tuple[str, ...] = ()


def load_slots(path: Path) -> SlotsFile:
    return SlotsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_slots() -> SlotsFile:
    return load_slots(get_settings().config_dir / "slots.yaml")


# ---- config/escalation_templates.yaml ---------------------------------------------------------


class CodeTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    user_message: str = Field(min_length=1)  # tin gửi người dùng [Chốt B20 7.1]
    next_for_l2: str = Field(min_length=1)  # phần (4) của ghi chú bàn giao (B20 4.2)


class EscalationTemplates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deny_warning: str = Field(min_length=1)  # nối vào next_for_l2 với MỌI E5 (2b-Q4)
    codes: dict[ExitCode, CodeTemplate]

    @model_validator(mode="after")
    def _all_codes(self) -> "EscalationTemplates":
        missing = sorted(c.value for c in ExitCode if c not in self.codes)
        if missing:
            raise ValueError(f"escalation_templates thiếu mã: {missing}")
        return self

    def of(self, code: str) -> CodeTemplate:
        return self.codes[ExitCode(code)]


def load_escalation_templates(path: Path) -> EscalationTemplates:
    return EscalationTemplates.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_escalation_templates() -> EscalationTemplates:
    return load_escalation_templates(get_settings().config_dir / "escalation_templates.yaml")
