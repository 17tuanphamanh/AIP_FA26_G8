"""Cấu hình ml-service — chỉ đọc biến môi trường, không đọc file env (test không chạm `.env`).

`ML_SERVICE_TOKEN` BẮT BUỘC, không mặc định (3-Q21): thiếu hoặc ngắn hơn 32 ký tự → không khởi động.
`ML_MAX_CONCURRENCY` mặc định 1: torch đã tự đa luồng (`ML_THREADS`), chạy song song nhiều lô trên
4 vCPU chỉ làm các lô tranh CPU rồi cùng timeout (quyết định của người, 3a).
`GUARD_MODEL_DIR` (ML-GAN): rỗng = không nạp, `/classify` 503 như Phase 3; có đặt → nạp lúc khởi động (`guard.py`).
`GUARD_MODEL_SHA256`: đặt thì `model.safetensors` lệch → không khởi động; sai dạng (khác 64 hex) cũng không khởi động.
Phase 5 gói 1 (D-52, phase5 §6.5 #3, #5, #9): `ML_CLASSIFY_CONCURRENCY` (mặc định 1) — hàng chờ RIÊNG cho `/classify` và
`/classify_intent`, tách khỏi embed/rerank (lệch quyết định 3a: classify chạy song song rerank, tranh CPU — ghi D-52);
`ML_MODELS_ROOT` (mặc định `/ml_models`) — `GUARD_MODEL_DIR`, `INTENT_MODEL_DIR` và mọi file trong đó phải nằm dưới gốc này
sau `resolve()`; `GUARD_MANIFEST_SHA256` — SHA-256 của `MANIFEST.sha256`. Đặt `GUARD_MODEL_DIR` thì `GUARD_MODEL_SHA256` VÀ
`GUARD_MANIFEST_SHA256` bắt buộc (kiểm ở `guard.check_guard`). Hai biến số không truyền qua compose (như `ML_MAX_CONCURRENCY`).
Phase 5 gói 2 (D-53): `INTENT_MODEL_DIR` rỗng = không nạp, `/classify_intent` 503; có đặt → nạp `intent-clf` (`intent.py`) và
`INTENT_MODEL_SHA256` (SHA-256 của `model.safetensors`) VÀ `INTENT_MANIFEST_SHA256` bắt buộc (kiểm ở `intent.check_intent`).
D-101: `ML_EMBED_CONCURRENCY` (mặc định 1) — hàng chờ riêng cho `/embed` + `/count_tokens`, tách khỏi `/rerank`.
"""

import os
import re
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_TOKEN_LEN = 32  # P6 mục 3: ≥ 32 byte ngẫu nhiên (token_urlsafe(32) dài 43 ký tự)
SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
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
    # Phase 5 (T23a, D-44; gói 2, D-53) — model phân loại của nhóm (P11): guard (injection-clf), intent (intent-clf) nạp nếu đặt.
    guard_model_dir: Path | None = None
    guard_model_sha256: str | None = None
    intent_model_dir: Path | None = None
    intent_model_sha256: str | None = None
    intent_manifest_sha256: str | None = None
    # Phase 5 (gói 1, D-52)
    ml_classify_concurrency: int = Field(default=1, ge=1)
    # D-101 (máy demo 17/11): hàng chờ RIÊNG cho /embed + /count_tokens — câu ngắn (vài trăm ms) không xếp sau rerank 10–15 s rồi hết
    # hạn 5 s của backend (cùng lý do D-52 tách /classify). Không truyền qua compose (như ML_MAX_CONCURRENCY).
    ml_embed_concurrency: int = Field(default=1, ge=1)
    ml_models_root: Path = Path("/ml_models")
    guard_manifest_sha256: str | None = None

    @field_validator("ml_service_token")
    @classmethod
    def _long_enough(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < MIN_TOKEN_LEN:
            raise ValueError(f"ML_SERVICE_TOKEN phải dài ≥ {MIN_TOKEN_LEN} ký tự")
        return value

    @field_validator("guard_model_sha256", "guard_manifest_sha256", "intent_model_sha256", "intent_manifest_sha256")
    @classmethod
    def _sha256_hex(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not SHA256_HEX.match(value.lower()):
            raise ValueError("GUARD_/INTENT_MODEL_SHA256, GUARD_/INTENT_MANIFEST_SHA256 phải là 64 ký tự hex (SHA-256)")
        return value.lower()
