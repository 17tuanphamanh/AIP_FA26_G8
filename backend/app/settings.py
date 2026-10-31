"""Cấu hình — docs/spec/build/01-kien-truc-project.md mục 5.

- Env (`Settings`): bí mật, hạ tầng, cờ thực nghiệm, tham số vận hành. Bí mật để SecretStr
  (không in ra log/repr). Biến LLM để trống tới mốc G (decisions.md mục 4).
- `config/policy.json` (`get_policy`): hằng số nghiệp vụ [Chốt 01 mục 5.2]; sai schema → không khởi động. 3h (phase3 11.2):
  `business_hours` + `rules` (R16–R20, schema/DSL `domain.policy`); `policy_sha256` vào audit điểm 4 (3-Q29);
  `check_policy_config` (Q-3h-1, gọi ở `open_runtime` trước DB): mỗi `action_type` thuộc đúng một intent, mọi `action` của
  luật ∈ `action_types` của intent luật đó — lệch → không khởi động.
- `config/slots.yaml` (`get_slots`): `tool_arg_slots` (D-20), `query_slots` (3-Q13), `intents` (3f, phase3 3.2 — schema
  `domain.slots.IntentSlots`).
- `config/action_metadata.yaml` (`get_action_metadata`, 3f, phase3 9.2): thuộc tính rủi ro từng `action_type`.
  `check_intent_config` (gọi ở `graph/wiring.open_runtime` trước DB): `ENABLED_INTENTS` ⊆ `slots.intents`, mọi
  `action_type` có metadata — thiếu → không khởi động (không mặc định "reversible").
- `config/approvers.yaml` (`open_approvers`, Phase 4 4b P1): người duyệt chính/dự phòng/Trưởng BP theo intent — gọi ở
  `open_runtime` trước DB; thiếu intent đang bật, khoá lạ, id sai mẫu, trùng người → không khởi động. `approval_sla_minutes`
  (P12): `APPROVAL_SLA_MINUTES_DEV` chỉ dev/test.
- `config/escalation_templates.yaml` (`get_escalation_templates`): mẫu thông báo + `next_for_l2` theo mã E
  của B20 (B20 mục 4.2, 7.1) — đủ E0–E9, không chuỗi rỗng.
Giá, timeout, prompt KHÔNG nằm ở đây — thuộc config/llm.yaml, config/prompts/ (P2). Riêng tên model hai vai
trò (`FAST_MODEL`, `STRONG_MODEL`), `LLM_BASE_URL`, `LLM_API_KEY` đọc từ env (PLAN-3d Q-3d-3).

File env: `APP_ENV_FILE` (mặc định `.env`, tính từ thư mục đang chạy); đặt RỖNG để tắt hẳn —
khi đó chỉ đọc biến môi trường. `conftest.py` ở gốc repo đặt rỗng trước khi import app, để test
không bao giờ đọc (hay stat) file `.env` thật.
"""

import hashlib
import json
import logging
import os
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    SecretStr,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.domain.action import ActionMeta
from app.domain.approval import Roster
from app.domain.exit_codes import ExitCode
from app.domain.policy import BusinessHours, Rule, check_rules
from app.domain.slots import IntentSlots

log = logging.getLogger(__name__)

GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")  # Phase 4 P4: `APP_GIT_SHA` chỉ nhận SHA-1 đầy đủ, chữ thường
# Dạng địa chỉ email chấp nhận (SMTP_FROM, `users.email` đồng bộ từ AD): một `@`, không khoảng trắng/ký tự điều khiển, tên miền có dấu
# chấm; tổng ≤ 254 (RFC 5321) kiểm riêng ở nơi dùng.
_DOMAIN_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
EMAIL_ADDRESS_RE = re.compile(rf"[A-Za-z0-9.!#$%&'*+/=?^_`{{|}}~-]{{1,64}}@{_DOMAIN_LABEL}(?:\.{_DOMAIN_LABEL})+")


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

    # ---- LLM gateway (P2; phase3 mục 7.3, PLAN-3d Q-3d-3, Q-3d-13) ----
    # BẮT BUỘC, không mặc định (3-Q26): thiếu → backend/worker từ chối khởi động (`require_llm_backend`).
    # `scripted` (ScriptedLLM) chỉ khi APP_ENV ∈ {dev, test}. None ở đây chỉ để test dựng Settings tự do.
    llm_backend: Literal["scripted", "real"] | None = None
    # Chỉ dùng khi `real`: model của hai vai trò (phải có dòng trong `pricing` của config/llm.yaml) và
    # base_url của provider — config/llm.yaml trỏ tới TÊN các trường này (`model_setting`, `base_url_setting`).
    fast_model: str | None = None
    strong_model: str | None = None
    # repr=False: URL có thể mang khoá (`user:pass@`, `?api-key=`) — không lộ qua repr/str của Settings (S9).
    llm_base_url: str | None = Field(default=None, repr=False)
    # Preset ScriptedLLM trên stack dev (`[fake:<preset>]`, Q-3d-12). None → `<config_dir>/scripted`.
    llm_script_preset_dir: Path | None = None

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
    # ---- SSE tiến trình ticket (GET /api/tickets/{id}/events) ----
    enable_sse: bool = False  # tắt → route trả 404, màn chat dùng polling như cũ
    sse_poll_ms: int = Field(default=300, ge=50)  # nhịp đọc DB tìm dòng audit mới
    sse_heartbeat_s: float = Field(default=15.0, gt=0)  # comment giữ kết nối khi không có sự kiện
    graph_recursion_limit: int = Field(default=60, ge=10)  # P1 mục 7: lưới cuối sau MAX_LOOPS
    checkpoint_pool_size: int = Field(default=10, ge=1)  # pool psycopg của AsyncPostgresSaver
    # ---- Worker (P1 mục 7) ----
    worker_deadline_scan_seconds: float = Field(default=15.0, gt=0)  # quét hạn chờ
    worker_recover_scan_seconds: float = Field(default=60.0, gt=0)  # quét lượt dở dang
    worker_stale_turn_seconds: float = Field(default=120.0, gt=0)  # lượt mở quá 2 phút → recover
    # Hạn cho cả lượt (phase3 9.0, P4 PLAN-3f): mọi lời gọi ra ngoài cắt timeout theo phần còn lại − biên an toàn
    # (`core/turn_budget.py`); hết → E2 turn_budget_exceeded. Phải < WORKER_STALE_TURN_SECONDS (`_turn_budget_below_stale`).
    turn_budget_s: float = Field(default=100.0, gt=0)
    safety_margin_s: float = Field(default=2.0, gt=0)
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
    # `off` → không mở /docs, /redoc, /openapi.json (máy demo). Không phụ thuộc APP_ENV: demo chạy APP_ENV=dev.
    api_docs: Literal["on", "off"] = "on"
    # ---- Privacy guard (B02 L1, phase3 mục 8.3, 3-Q25) ----
    # Mặc định MỌI env là guard regex thật. `none` (NotRedactingGuard) chỉ khi đặt tường minh VÀ APP_ENV ∈ {dev, test}
    # (`main._default_guard` → `require_dev_fakes`) — không có đường nào lưu dữ liệu thô ở môi trường thật.
    privacy_guard: Literal["regex", "none"] = "regex"
    # Email thuộc các tên miền này (và tên miền con) KHÔNG bị che — cần cho slot (mục 3.5, 8.3).
    company_email_domains: list[str] = Field(default_factory=lambda: ["congty-abc.vn"])
    # Output guard (phase3 10.3 (b), `guard/output.py`): chuỗi canary cài trong KB/prompt — xuất hiện trong chữ LLM sắp
    # lưu/gửi → chặn. Mặc định rỗng; test/probe đặt. Mỗi chuỗi ≥ 8 ký tự (ngắn hơn dễ chặn nhầm câu thường).
    output_canaries: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=8)]] = Field(
        default_factory=list
    )

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

    # ---- Phạm vi intent (3-Q27, phase3 3.5) — Phase 5 T24 P1 (Q-5-7): bật đủ 4 loại ----
    enabled_intents: list[str] = Field(default_factory=lambda: ["vpn", "account", "software", "access"], min_length=1)

    # ---- Cờ thực nghiệm ----
    eval_mode: bool = False
    enable_proactive_diagnosis: bool = True  # B06 mục 7: mặc định true
    strategy: Literal["manual", "full_auto", "rule_only", "llm_only", "hybrid", "hybrid_guarded"] = (
        "hybrid"
    )
    llm_cache_mode: Literal["default", "eval", "bypass"] = "default"  # P2 mục 8
    rediagnose_on_new_slot: bool = False  # D-20: tắt mặc định; bật → không khởi động (3g, Q-3g-7)
    # Phase 5 (T23a, ML-GAN — D-44): quyền quyết định của model chặn tấn công ở B2 L3. `shadow` (mặc định): vẫn gọi
    # /classify, ghi `p_mal` vào `screening`, nhưng không chặn/cho qua theo điểm — mọi câu không khớp mẫu xuống L4.
    # `active`: ≥ TAU_BLOCK chặn, ≤ TAU_PASS qua. Giá trị khác → không khởi động. Node B2 đọc MỘT lần lúc dựng graph (backend VÀ worker).
    # Phase 5 (gói 1, D-52): thêm `review` — model nghi (p ≥ τ) mà LLM chấm nói không → E1 `injection_suspected`; model không
    # bao giờ cho câu đi thẳng. `review` BẮT BUỘC `B2_TAU_REVIEW` ([0,50; 0,9999], không mặc định); `active` chỉ ở dev/test
    # (D-44: 31/900 câu tấn công đi thẳng). Sai → backend VÀ worker từ chối khởi động (`_b2_mode_guard`).
    b2_classifier_mode: Literal["shadow", "active", "review"] = "shadow"
    b2_tau_review: float | None = Field(default=None, ge=0.5, le=0.9999, allow_inf_nan=False)

    # ---- Phase 4 ----
    # S0-P11 (Q-4-U A+, D-34): `true` → yêu cầu HÀNH ĐỘNG cũng phải qua cổng độ liên quan B9 như Phase 3 (ablation Phase 10,
    # đối chiếu hành vi 3h). Mặc định `false`: B9 chỉ cho câu trả lời; căn cứ hành động = `procedure_doc` kiểm ở B11.
    grounding_gate_actions: bool = False
    # P4 (Việc treo 13): commit của image — `make up` build với `--build-arg GIT_SHA` CHỈ khi cây sạch (file tracked không đổi);
    # `backend/Dockerfile` đặt `ENV APP_GIT_SHA`. Chỉ nhận 40 hex; khác → None + 1 dòng WARNING (không từ chối khởi động);
    # rỗng (cây bẩn) → None. `lineage.commit_sha` lấy từ đây (qua `NodeDeps.commit_sha`).
    app_git_sha: str | None = None
    # 4b P12: hạn duyệt (phút) đè `SLA_MINUTES` của policy.json để thử hết hạn/nhắc trên stack dev — CHỈ khi APP_ENV ∈ {dev, test}
    # (`require_dev_fakes` ở `open_runtime`, trước DB); môi trường khác đặt biến này → từ chối khởi động.
    approval_sla_minutes_dev: int | None = Field(default=None, ge=1, le=30)

    @field_validator("app_git_sha", mode="before")
    @classmethod
    def _git_sha_40_hex(cls, v: object) -> object:
        # P4: sai dạng → None + WARNING (không in giá trị); không từ chối khởi động — lineage chỉ mất commit_sha.
        if v is None or v == "":
            return None
        if isinstance(v, str) and GIT_SHA_RE.fullmatch(v):
            return v
        log.warning("APP_GIT_SHA không phải 40 ký tự hex — bỏ qua, lineage.commit_sha = NULL")
        return None

    # ---- Phase 5 (gói 2b) — chống spam D-54 (a), đặc tả `claude/dac-ta-bat-2-model.md` 4.8 ----
    # 429 theo tài khoản (sau xác thực, đếm theo `user_id`): ticket mới (`POST /api/tickets`, không tính ticket con) ≤ N trong 10 phút và
    # ≤ M mỗi giờ; `/messages`, `/reply`, `/confirm` chung một bộ ≤ K trong 10 phút (bảng `rate_hits`). KHÔNG có giá trị "tắt": cổng, đo,
    # demo nới bằng số lớn (`make up RATE=loose`, `make verify` tự nới) và ghi vào biên bản.
    ticket_rate_10min: int = Field(default=10, ge=1)
    ticket_rate_hour: int = Field(default=30, ge=1)
    message_rate_10min: int = Field(default=30, ge=1)

    # ---- M9 (P9; kế hoạch M9 mục 4.1) ----
    # DSN role app_monitor (chỉ SELECT). KHÔNG mặc định: thiếu/rỗng → route M9 trả 503 `monitor_unavailable`, job M9
    # không chạy — không bao giờ rơi về app_rw (`monitor/db.py`). repr=False: DSN mang mật khẩu.
    monitor_database_url: str | None = Field(default=None, repr=False)

    # ---- Notify-email (hàng đợi `email_outbox` + worker `send_emails`) ----
    # Mặc định TẮT. Bật mà thiếu biến bắt buộc → MỌI tiến trình (backend, worker) từ chối khởi động, thông báo nêu tên biến
    # (`_email_config`). EVAL_MODE=true → luôn tắt (`email_active`): không ghi outbox, không gửi. SMTP_PASSWORD là SecretStr;
    # SMTP_USERNAME/SMTP_PASSWORD đi cặp; có tài khoản thì bắt buộc STARTTLS (không gửi mật khẩu qua kênh rõ).
    email_enabled: bool = False
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_starttls: bool = True
    smtp_username: str | None = Field(default=None, repr=False)
    smtp_password: SecretStr | None = None
    smtp_from: str | None = None
    email_link_base_url: str | None = None  # gốc URL frontend cho dòng "Xem chi tiết: …" (không có "/" cuối)
    email_send_interval_seconds: float = Field(default=15.0, gt=0)  # chu kỳ job `send_emails` của worker

    @field_validator("email_link_base_url", mode="after")
    @classmethod
    def _link_base(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip().rstrip("/")
        if not re.fullmatch(r"https?://[^\s/?#]+(/[^\s?#]*)?", v):
            raise ValueError("EMAIL_LINK_BASE_URL phải là URL http(s)://… không có query/fragment")
        return v

    @model_validator(mode="after")
    def _email_config(self) -> "Settings":
        if not self.email_enabled:
            return self
        if self.eval_mode:  # EVAL_MODE luôn tắt email — không đòi biến SMTP
            log.warning("EMAIL_ENABLED=true bị bỏ qua vì EVAL_MODE=true — không ghi email_outbox, không gửi")
            return self
        required = {
            "SMTP_HOST": self.smtp_host, "SMTP_FROM": self.smtp_from, "EMAIL_LINK_BASE_URL": self.email_link_base_url,
        }  # fmt: skip
        missing = [name for name, value in required.items() if not value]
        if (self.smtp_username is None) != (self.smtp_password is None):
            missing.append("SMTP_PASSWORD" if self.smtp_password is None else "SMTP_USERNAME")
        if missing:
            raise ValueError(f"EMAIL_ENABLED=true nhưng thiếu biến: {', '.join(missing)} — từ chối khởi động")
        if self.smtp_username is not None and not self.smtp_starttls:
            raise ValueError("SMTP_USERNAME đặt mà SMTP_STARTTLS=false — không gửi mật khẩu SMTP qua kênh rõ, từ chối khởi động")
        if self.smtp_from is not None and not EMAIL_ADDRESS_RE.fullmatch(self.smtp_from):
            raise ValueError("SMTP_FROM không phải địa chỉ email hợp lệ — từ chối khởi động")
        return self

    @property
    def email_active(self) -> bool:
        """Email thật sự chạy: EMAIL_ENABLED=true VÀ không EVAL_MODE. Mọi nơi dựng notifier/job email chỉ hỏi thuộc tính này."""
        return self.email_enabled and not self.eval_mode

    @field_validator("llm_backend", mode="before")
    @classmethod
    def _llm_backend_value(cls, v: object) -> object:
        # Q-3d-13: thông báo nêu tên biến + giá trị hợp lệ (lỗi Literal mặc định chỉ ghi tên trường thường).
        if v is not None and v not in LLM_BACKENDS:
            raise ValueError(f"LLM_BACKEND={v!r} không hợp lệ — giá trị hợp lệ: {' | '.join(LLM_BACKENDS)}")
        return v

    @field_validator("api_docs", mode="before")
    @classmethod
    def _api_docs_value(cls, v: object) -> object:
        if v not in API_DOCS_VALUES:
            raise ValueError(f"API_DOCS={v!r} không hợp lệ — giá trị hợp lệ: {' | '.join(API_DOCS_VALUES)}")
        return v

    @model_validator(mode="after")
    def _eval_mode_not_in_prod(self) -> "Settings":
        # P2 mục 11: EVAL_MODE ghi prompt đầy đủ vào `llm_calls.prompt_full` — chỉ môi trường thử nghiệm. Thiếu
        # APP_ENV = coi như môi trường thật (2b-Q2). Kiểm ở Settings nên MỌI tiến trình (backend, worker, CLI) từ chối.
        if self.eval_mode and self.app_env not in EVAL_MODE_ENVS:
            raise ValueError(
                f"EVAL_MODE=true chỉ dùng được khi APP_ENV ∈ {sorted(EVAL_MODE_ENVS)} "
                f"(đang là {self.app_env!r}) — từ chối khởi động"
            )
        return self

    @model_validator(mode="after")
    def _b2_mode_guard(self) -> "Settings":
        # Phase 5 (gói 1, D-52): kiểm ở Settings → MỌI tiến trình dựng Settings (backend, worker) cùng từ chối.
        if self.b2_classifier_mode == "review" and self.b2_tau_review is None:
            raise ValueError("B2_CLASSIFIER_MODE=review cần b2_tau_review (B2_TAU_REVIEW, khoảng [0,50; 0,9999]) — từ chối khởi động")
        if self.b2_classifier_mode == "active" and self.app_env not in B2_ACTIVE_ENVS:
            raise ValueError(
                f"B2_CLASSIFIER_MODE=active chỉ dùng được khi APP_ENV ∈ {sorted(B2_ACTIVE_ENVS)} "
                f"(đang là {self.app_env!r}) — từ chối khởi động"
            )
        return self

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
    def _turn_budget_below_stale(self) -> "Settings":
        # 9.0: lượt dùng hết hạn vẫn phải xong (kể cả E2 → B20) trước khi worker coi là "dở dang" và chạy lại.
        if not self.safety_margin_s < self.turn_budget_s < self.worker_stale_turn_seconds:
            raise ValueError(
                "cần SAFETY_MARGIN_S < TURN_BUDGET_S < WORKER_STALE_TURN_SECONDS "
                f"(đang {self.safety_margin_s:g} / {self.turn_budget_s:g} / {self.worker_stale_turn_seconds:g}) "
                "— từ chối khởi động"
            )
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

    def require_llm_backend(self) -> Literal["scripted", "real"]:
        """`LLM_BACKEND` bắt buộc mọi env (3-Q26, Q-3d-13); `scripted` chỉ dev/test — fail-closed."""
        if self.llm_backend is None:
            raise RuntimeError(
                f"LLM_BACKEND chưa cấu hình — giá trị hợp lệ: {' | '.join(LLM_BACKENDS)} "
                "(scripted chỉ khi APP_ENV là dev hoặc test) — từ chối khởi động"
            )
        if self.llm_backend == "scripted":
            self.require_dev_fakes("LLM_BACKEND=scripted (ScriptedLLM; môi trường thật dùng LLM_BACKEND=real)")
        return self.llm_backend

    def require_dev_fakes(self, what: str) -> None:
        """Thành phần giả chỉ được nạp khi `APP_ENV` ∈ {dev, test} — fail-closed (2b-Q2, 2b-Q3)."""
        if self.app_env not in DEV_FAKE_ENVS:
            raise RuntimeError(
                f"{what} chỉ dùng được khi APP_ENV ∈ {sorted(DEV_FAKE_ENVS)} "
                f"(đang là {self.app_env!r}) — từ chối khởi động"
            )


DEV_FAKE_ENVS = frozenset({"dev", "test"})
B2_ACTIVE_ENVS = DEV_FAKE_ENVS  # Phase 5 (gói 1, D-52): `active` 0,90/0,10 giữ trong code, chỉ thử ở dev/test
EVAL_MODE_ENVS = frozenset({"dev", "test", "staging"})  # S9 PLAN-3d: prod và APP_ENV thiếu → từ chối
LLM_BACKENDS = ("scripted", "real")
API_DOCS_VALUES = ("on", "off")


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
    TAU_INTENT: float = Field(ge=0, le=1)  # B3 đường LLM: confidence < ngưỡng → E1 intent_low_confidence (D-27, 3-Q29)
    CLARIFY_TIMEOUT_HOURS: int = Field(ge=1)
    CONFIRM_TIMEOUT_HOURS: int = Field(ge=1)

    @model_validator(mode="after")
    def _thresholds_ordered(self) -> "PolicyConstants":
        if not self.THRESHOLD_LOW < self.THRESHOLD_HIGH:
            raise ValueError("THRESHOLD_LOW phải nhỏ hơn THRESHOLD_HIGH")
        return self


class M5Config(BaseModel):
    """Khối `m5` của policy.json (phase6 6.1 P2): cách lấy p của B14 + phiên bản calibrator. `calibrator_version` null = chưa
    hiệu chỉnh → không bao giờ AUTO (D-38). Mẫu `VERSION_PATTERN` (6A) KHÔNG kiểm ở đây: `settings` không được import `app.risk`
    (`llm`, `rag`, `monitor` import settings — hợp đồng import-linter); `graph/wiring.open_runtime` nạp bằng `load_calibrator`
    (kiểm mẫu TRƯỚC khi ghép đường dẫn) trước DB → sai mẫu vẫn là không khởi động. `p_method` chép tập của `risk.estimator.PMethod`
    (cùng lý do) — test so khớp."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    p_method: Literal["self_report", "sampling_k5"]
    calibrator_version: str | None = Field(min_length=1, max_length=64)  # độ dài cột lineage.calibrator_version


class PolicyFile(BaseModel):
    """Schema của policy.json. 3h: `business_hours` + `rules` (Phase 3 chỉ R16–R20 — phase3 11.2; 15 luật còn lại ở
    Phase 5). Phase 6 6C: khối `m5` (P2) BẮT BUỘC. `thresholds`, `cost_matrix`… (B12–B14 mục 7) chưa có — khoá lạ bị từ chối
    để không ai tưởng đã có hiệu lực."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    constants: PolicyConstants
    business_hours: BusinessHours
    m5: M5Config
    rules: tuple[Rule, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> "PolicyFile":
        check_rules(self.rules)
        return self


def _no_nan(name: str) -> float:
    raise ValueError(f"policy.json: {name} không hợp lệ (NaN/Infinity làm điều kiện luật luôn đúng/sai)")


def parse_policy(raw: bytes) -> PolicyFile:
    return PolicyFile.model_validate(json.loads(raw.decode("utf-8"), parse_constant=_no_nan))


def load_policy(path: Path) -> PolicyFile:
    return parse_policy(path.read_bytes())


@lru_cache
def _policy_bytes() -> bytes:
    """Đọc `config/policy.json` MỘT lần mỗi process — luật đang chạy và sha ghi audit luôn cùng một bản (soát S7 NGHI 2)."""
    return (get_settings().config_dir / "policy.json").read_bytes()


@lru_cache
def get_policy() -> PolicyFile:
    return parse_policy(_policy_bytes())


def policy_sha256() -> str:
    """sha256 của đúng các byte đã nạp thành `get_policy()` — audit điểm 4 (3-Q29, `policy_version_id` NULL ở Phase 3)."""
    return hashlib.sha256(_policy_bytes()).hexdigest()


# ---- config/slots.yaml -----------------------------------------------------------------------


class SlotsFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_arg_slots: frozenset[str] = Field(min_length=1)  # TOOL_ARG_SLOTS (D-20)
    # 3-Q13: slot nối thêm vào câu truy hồi (build_query). Mặc định rỗng — fixture test cũ (vd.
    # test_tool_registry.py) dựng slots.yaml tối giản không khai báo mục này vẫn nạp được.
    query_slots: tuple[str, ...] = ()
    # 3f (phase3 3.2): slot theo intent — Phase 3 chỉ `vpn`. Mặc định rỗng (fixture test tối giản vẫn nạp được);
    # intent bật mà không có mục ở đây → `check_intent_config` từ chối khởi động.
    intents: dict[str, IntentSlots] = Field(default_factory=dict)

    @property
    def declared_names(self) -> frozenset[str]:
        """Mọi tên slot khai báo trong file (định danh cố định — ghi vào audit được, khác key tự do của LLM)."""
        names = set(self.tool_arg_slots) | set(self.query_slots)
        for spec in self.intents.values():
            names |= spec.keys
        return frozenset(names)


def load_slots(path: Path) -> SlotsFile:
    return SlotsFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_slots() -> SlotsFile:
    return load_slots(get_settings().config_dir / "slots.yaml")


# ---- config/action_metadata.yaml (3f, phase3 9.2) -------------------------------------------------


class ActionMetadataFile(RootModel[dict[str, dict[str, ActionMeta]]]):
    """intent → action_type → `ActionMeta`."""

    def of(self, intent: str) -> dict[str, ActionMeta]:
        return self.root.get(intent, {})


def load_action_metadata(path: Path) -> ActionMetadataFile:
    return ActionMetadataFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@lru_cache
def get_action_metadata() -> ActionMetadataFile:
    return load_action_metadata(get_settings().config_dir / "action_metadata.yaml")


def intents_of_actions(metadata: ActionMetadataFile) -> dict[str, str]:
    """`action_type` → intent (Q-3h-1: `Action` không mang intent). Một `action_type` ở ≥ 2 intent → `ValueError`."""
    owner: dict[str, str] = {}
    for intent, actions in sorted(metadata.root.items()):
        for action_type in actions:
            if action_type in owner:
                raise ValueError(f"action_type {action_type!r} thuộc cả {owner[action_type]!r} lẫn {intent!r}")
            owner[action_type] = intent
    return owner


@lru_cache
def action_intents() -> Mapping[str, str]:
    return intents_of_actions(get_action_metadata())


def check_policy_config(policy: PolicyFile, slots: SlotsFile, metadata: ActionMetadataFile) -> None:
    """Fail-closed lúc khởi động (Q-3h-1): mỗi `action_type` thuộc đúng một intent; mọi `action` của luật thuộc
    `action_types` (slots.yaml) của đúng intent luật đó — luật nhắm hành động không tồn tại sẽ im lặng không bao giờ khớp."""
    try:
        owner = intents_of_actions(metadata)
    except ValueError as e:
        raise RuntimeError(f"action_metadata.yaml: {e} — từ chối khởi động") from e
    for rule in policy.rules:
        declared = set(slots.intents[rule.intent].action_types) if rule.intent in slots.intents else set()
        bad = sorted(a for a in rule.actions if a not in declared or owner.get(a) != rule.intent)
        if bad:
            raise RuntimeError(
                f"policy.json {rule.id}: action {bad} không thuộc action_types của intent {rule.intent!r} — từ chối khởi động"
            )


def check_intent_config(settings: Settings, slots: SlotsFile, metadata: ActionMetadataFile) -> None:
    """Fail-closed lúc khởi động (phase3 9.2, 3-Q27): intent bật phải có slot; mọi `action_type` phải có metadata.
    3g (chốt Q-3g-7): cờ D-20 `REDIAGNOSE_ON_NEW_SLOT` bật → từ chối — chẩn đoán lại chưa hiện thực ("Việc treo" 11)."""
    if settings.rediagnose_on_new_slot:
        raise RuntimeError(
            "REDIAGNOSE_ON_NEW_SLOT=true: chẩn đoán lại (D-20) chưa hiện thực ở Phase 3 — từ chối khởi động"
        )
    if missing := sorted(set(settings.enabled_intents) - set(slots.intents)):
        raise RuntimeError(f"ENABLED_INTENTS có intent không khai báo trong slots.yaml: {missing} — từ chối khởi động")
    for intent, spec in sorted(slots.intents.items()):
        if missing := sorted(set(spec.action_types) - set(metadata.of(intent))):
            raise RuntimeError(
                f"action_metadata.yaml thiếu metadata cho {intent}: {missing} — từ chối khởi động "
                "(không mặc định reversible)"
            )


# ---- config/approvers.yaml (Phase 4 chặng 4b P1) ------------------------------------------------

APPROVERS_FILE = "approvers.yaml"


class ApproversFile(RootModel[dict[str, Roster]]):
    """intent → người duyệt chính / dự phòng / Trưởng BP (Q-4-H: lịch trực tĩnh). Nhóm AD và trạng thái KHÔNG kiểm lúc khởi động
    (mock AD có thể chưa lên) — B15 kiểm lúc chạy."""

    def of(self, intent: str) -> Roster | None:
        return self.root.get(intent)


def load_approvers(path: Path) -> ApproversFile:
    return ApproversFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def check_approvers_config(settings: Settings, approvers: ApproversFile) -> None:
    """Fail-closed lúc khởi động (P1): mọi intent trong `ENABLED_INTENTS` phải có roster."""
    if missing := sorted(i for i in settings.enabled_intents if approvers.of(i) is None):
        raise RuntimeError(f"{APPROVERS_FILE} thiếu người duyệt cho intent đang bật {missing} — từ chối khởi động")


def open_approvers(settings: Settings) -> ApproversFile:
    """Nạp `<config_dir>/approvers.yaml` + kiểm (P1). File thiếu, YAML hỏng, schema sai (khoá lạ, id sai mẫu, trùng người),
    intent đang bật không có roster → `RuntimeError` (backend/worker từ chối khởi động, gọi TRƯỚC khi đụng DB)."""
    path = settings.config_dir / APPROVERS_FILE
    try:
        approvers = load_approvers(path)
    except (OSError, yaml.YAMLError, ValueError) as e:  # ValidationError là ValueError
        raise RuntimeError(f"{APPROVERS_FILE} không nạp được ({type(e).__name__}) — từ chối khởi động") from e
    check_approvers_config(settings, approvers)
    return approvers


def approval_sla_minutes(settings: Settings) -> int:
    """Hạn duyệt HIỆU LỰC (P12): `APPROVAL_SLA_MINUTES_DEV` — chỉ APP_ENV ∈ {dev, test}, khác → từ chối khởi động — hoặc
    `SLA_MINUTES` của policy.json."""
    if settings.approval_sla_minutes_dev is None:
        return get_policy().constants.SLA_MINUTES
    settings.require_dev_fakes("APPROVAL_SLA_MINUTES_DEV (hạn duyệt rút ngắn cho dev)")
    return settings.approval_sla_minutes_dev


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
