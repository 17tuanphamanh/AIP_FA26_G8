"""A2 (bn-a, 08/11) — worker KHÔNG nhận `MFA_ENC_KEY`, `JWT_SIGNING_KEY` (test viết trước, DỪNG 1).

Vì sao: worker chỉ cần khoá HMAC username ma (B15 `ensure` khi phục hồi lượt — `graph/wiring.approver_users`), không cần khoá ký JWT
(ký được token mọi vai trò) hay khoá giải mã secret MFA. Hợp đồng (PLAN bn-a mục A2):
- compose: `x-backend-env` (env chung) KHÔNG còn `JWT_SIGNING_KEY`, `MFA_ENC_KEY`; backend thêm riêng hai biến đó (như
  `SVC_EXECUTOR_TOKEN`); worker thêm `USERNAME_HMAC_KEY: ${USERNAME_HMAC_KEY:-}` (rỗng → worker tự từ chối, thông báo rõ — không chặn
  cả `docker compose` bằng `:?`).
- `.env.example`: dòng `USERNAME_HMAC_KEY=` để trống + chú thích cách dẫn xuất (TA tự thêm giá trị vào `.env`).
- `Settings.username_hmac_key` (SecretStr): 64 ký tự hex (32 byte) — sai dạng → không khởi động, thông báo KHÔNG in giá trị.
- `auth.username_hash.resolve_key(jwt_signing_key, username_hmac_key) -> bytes | None`: có `USERNAME_HMAC_KEY` → dùng nó (nếu CÓ cả
  `JWT_SIGNING_KEY` thì phải bằng khoá dẫn xuất, lệch → RuntimeError — lệch thì backend và worker băm khác nhau, đếm khoá username
  ma sai); chỉ có JWT → dẫn xuất như cũ (Q-4-S); không có gì → None.
- `worker.require_worker_keys(settings) -> bytes`: None → RuntimeError nêu tên `USERNAME_HMAC_KEY` — gọi TRƯỚC khi đụng DB.
- `wiring.approver_users`: lấy khoá qua `resolve_key` → worker chỉ có `USERNAME_HMAC_KEY` vẫn `available=True`.
"""

import hashlib
import hmac
import re
import secrets
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from app.settings import Settings
from pydantic import SecretStr, ValidationError

REPO = Path(__file__).resolve().parents[3]
LABEL = b"auth-username-v1"


def _compose() -> dict[str, Any]:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))


def _derived_hex(jwt: str) -> str:
    """Công thức Q-4-S viết lại độc lập (không gọi code sản phẩm)."""
    return hmac.new(jwt.encode("utf-8"), LABEL, hashlib.sha256).hexdigest()


# ---- compose + .env.example --------------------------------------------------------------------------------------------------


def test_a2_common_env_has_no_jwt_or_mfa_key() -> None:
    common = _compose()["x-backend-env"]
    assert "JWT_SIGNING_KEY" not in common and "MFA_ENC_KEY" not in common
    assert "MIGRATE_DATABASE_URL" not in common  # ĐP 08/11 20:35


def test_migrate_dsn_only_in_backend_where_alembic_runs() -> None:
    """`make up` chạy `compose run --rm --no-deps backend alembic upgrade head` → backend PHẢI còn DSN app_migrate; worker không."""
    backend = _compose()["services"]["backend"]["environment"]
    assert backend["MIGRATE_DATABASE_URL"].startswith("postgresql+psycopg://app_migrate:")
    assert "run --rm --no-deps backend alembic upgrade head" in (REPO / "Makefile").read_text(encoding="utf-8")


def test_a2_worker_env_has_only_username_hmac_key() -> None:
    worker = _compose()["services"]["worker"]["environment"]
    for secret in ("JWT_SIGNING_KEY", "MFA_ENC_KEY", "SVC_EXECUTOR_TOKEN", "MIGRATE_DATABASE_URL"):
        assert secret not in worker, secret
    assert worker["USERNAME_HMAC_KEY"] == "${USERNAME_HMAC_KEY:-}"


def test_a2_backend_gets_jwt_mfa_and_username_hmac_for_cross_check() -> None:
    """Soát A2 (7a): backend nhận CẢ JWT_SIGNING_KEY lẫn USERNAME_HMAC_KEY → `resolve_key` so hai nguồn lúc mở runtime; lệch → không mở.
    (Trước bản soát: backend không nhận USERNAME_HMAC_KEY → trong compose không tiến trình nào giữ cả hai → lệch không bị phát hiện.)"""
    backend = _compose()["services"]["backend"]["environment"]
    assert backend["JWT_SIGNING_KEY"] == "${JWT_SIGNING_KEY:-}"
    assert backend["MFA_ENC_KEY"] == "${MFA_ENC_KEY:-}"
    assert backend["SVC_EXECUTOR_TOKEN"] == "${SVC_EXECUTOR_TOKEN:-}"
    assert backend["USERNAME_HMAC_KEY"] == "${USERNAME_HMAC_KEY:-}"


def test_a2_env_example_declares_blank_username_hmac_key_with_derivation_hint() -> None:
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    lines = text.splitlines()
    assert "USERNAME_HMAC_KEY=" in lines
    assert not [line for line in lines if re.match(r"^\s*USERNAME_HMAC_KEY=\S", line)]
    assert "auth-username-v1" in text  # chú thích chỉ cách dẫn xuất từ JWT_SIGNING_KEY


# ---- Settings + resolve_key -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["abc", "z" * 64, "a" * 63, "a" * 65])
def test_a2_username_hmac_key_must_be_64_hex_and_error_hides_value(bad: str) -> None:
    with pytest.raises(ValidationError) as e:
        Settings(_env_file=None, username_hmac_key=bad)  # type: ignore[call-arg,arg-type]
    assert "USERNAME_HMAC_KEY" in str(e.value)
    assert bad not in str(e.value)


def test_a2_resolve_key_prefers_given_and_checks_against_jwt() -> None:
    from app.auth.username_hash import resolve_key, username_key

    jwt = secrets.token_urlsafe(32)
    derived = _derived_hex(jwt)
    assert resolve_key(SecretStr(jwt), None) == username_key(jwt.encode("utf-8")) == bytes.fromhex(derived)
    assert resolve_key(None, SecretStr(derived)) == bytes.fromhex(derived)  # worker: chỉ khoá dẫn xuất
    assert resolve_key(SecretStr(jwt), SecretStr(derived)) == bytes.fromhex(derived)
    assert resolve_key(None, None) is None
    other = "0" * 64
    with pytest.raises(RuntimeError) as e:
        resolve_key(SecretStr(jwt), SecretStr(other))
    assert "USERNAME_HMAC_KEY" in str(e.value) and other not in str(e.value) and jwt not in str(e.value)


# ---- worker ------------------------------------------------------------------------------------------------------------------


def test_a2_worker_refuses_without_username_hmac_key() -> None:
    from app.worker import require_worker_keys

    with pytest.raises(RuntimeError, match="USERNAME_HMAC_KEY"):
        require_worker_keys(Settings(_env_file=None))  # type: ignore[call-arg]
    key = "ab" * 32
    assert require_worker_keys(Settings(_env_file=None, username_hmac_key=key)) == bytes.fromhex(key)  # type: ignore[call-arg,arg-type]


@pytest.mark.asyncio
async def test_a2_worker_run_refuses_before_touching_db(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import worker

    def boom(*_: Any, **__: Any) -> Any:
        raise AssertionError("create_engines bị gọi trước khi kiểm khoá")

    monkeypatch.setattr(worker, "get_settings", lambda: Settings(_env_file=None))  # type: ignore[call-arg]
    monkeypatch.setattr(worker, "create_engines", boom)
    with pytest.raises(RuntimeError, match="USERNAME_HMAC_KEY"):
        await worker.run()


def test_a2_wiring_approver_users_available_with_only_derived_key() -> None:
    from app.graph.wiring import approver_users

    jwt = secrets.token_urlsafe(32)
    worker_settings = Settings(_env_file=None, username_hmac_key=_derived_hex(jwt))  # type: ignore[call-arg,arg-type]
    assert worker_settings.jwt_signing_key is None
    users = approver_users(worker_settings, SimpleNamespace(main=None), sink=None)  # type: ignore[arg-type]
    assert users.available is True
    assert approver_users(Settings(_env_file=None), SimpleNamespace(main=None), sink=None).available is False  # type: ignore[arg-type,call-arg]


# ---- Q7 (ĐP 08/11): worker thấy khoá thừa → từ chối khởi động -----------------------------------------------------------------


@pytest.mark.parametrize("var", ["jwt_signing_key", "mfa_enc_key", "svc_executor_token", "migrate_database_url"])
def test_a2_worker_refuses_when_it_receives_jwt_or_mfa_key(var: str) -> None:
    from app.worker import require_worker_keys

    value = "x" * 44
    kw: dict[str, Any] = {"username_hmac_key": "ab" * 32, var: value}
    s = Settings(_env_file=None, **kw)  # type: ignore[call-arg]
    with pytest.raises(RuntimeError) as e:
        require_worker_keys(s)
    assert var.upper() in str(e.value) and value not in str(e.value)


# ---- Q9 (ĐP 08/11): script dẫn xuất ghi thẳng vào file; username ma KHÔNG đổi -------------------------------------------------

SCRIPT = REPO / "scripts" / "ops" / "derive_username_key.py"


def _run_script(tmp_path: Path, *args: str, env_jwt: str | None = None) -> Any:
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k not in ("JWT_SIGNING_KEY", "USERNAME_HMAC_KEY", "MFA_ENC_KEY")}
    env |= {"PYTHONPATH": str(REPO / "backend"), "APP_ENV_FILE": ""}
    if env_jwt is not None:
        env["JWT_SIGNING_KEY"] = env_jwt
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, env=env, cwd=tmp_path,
                          check=False, timeout=60)  # fmt: skip


def test_q9_script_writes_derived_key_to_file_never_to_screen(tmp_path: Path) -> None:
    jwt = secrets.token_urlsafe(32)
    out = tmp_path / "username_key.env"
    r = _run_script(tmp_path, "--out", str(out), env_jwt=jwt)
    assert r.returncode == 0, r.stderr
    derived = _derived_hex(jwt)
    assert out.read_text(encoding="utf-8") == f"USERNAME_HMAC_KEY={derived}\n"
    assert derived not in r.stdout + r.stderr and jwt not in r.stdout + r.stderr
    assert (out.stat().st_mode & 0o777) == 0o600


def test_q9_script_reads_jwt_from_env_file_like_settings(tmp_path: Path) -> None:
    jwt = secrets.token_urlsafe(32)
    env_file = tmp_path / "may.env"
    env_file.write_text(f'APP_ENV=dev\nJWT_SIGNING_KEY="{jwt}"\nMFA_ENC_KEY=khac\n', encoding="utf-8")  # dạng có ngoặc như .env
    out = tmp_path / "k.env"
    r = _run_script(tmp_path, "--env-file", str(env_file), "--out", str(out))
    assert r.returncode == 0, r.stderr
    assert out.read_text(encoding="utf-8") == f"USERNAME_HMAC_KEY={_derived_hex(jwt)}\n"
    assert jwt not in r.stdout + r.stderr


def test_q9_script_refuses_existing_file_and_missing_jwt(tmp_path: Path) -> None:
    existing = tmp_path / "da-co.env"  # đứng thay `.env` thật (sandbox cấm tạo file tên `.env`; O_EXCL không xét tên)
    existing.write_text("GIU_NGUYEN=1\n", encoding="utf-8")
    r = _run_script(tmp_path, "--out", str(existing), env_jwt=secrets.token_urlsafe(32))
    assert r.returncode != 0 and existing.read_text(encoding="utf-8") == "GIU_NGUYEN=1\n"  # không ghi đè (kể cả .env)
    missing = tmp_path / "k.env"
    r = _run_script(tmp_path, "--out", str(missing))
    assert r.returncode != 0 and "JWT_SIGNING_KEY" in r.stderr and not missing.exists()


def test_q9_ghost_username_identical_before_and_after_split(tmp_path: Path) -> None:
    """Dữ liệu hiện có: backend (khoá dẫn xuất từ JWT qua `TokenSigner`, như trước A2) và worker (khoá đọc từ file script ghi) phải ra
    CÙNG giá trị `username_attempted` cho username ma — và trùng công thức Q-4-S viết độc lập."""
    from datetime import timedelta

    from app.auth.tokens import TokenSigner
    from app.auth.username_hash import failure_keys, resolve_key, stored_username
    from app.core.clock import FakeClock

    jwt = secrets.token_urlsafe(32)
    out = tmp_path / "k.env"
    assert _run_script(tmp_path, "--out", str(out), env_jwt=jwt).returncode == 0
    worker_key_hex = out.read_text(encoding="utf-8").strip().split("=", 1)[1]
    worker_settings = Settings(_env_file=None, username_hmac_key=worker_key_hex)  # type: ignore[call-arg,arg-type]
    worker_key = resolve_key(worker_settings.jwt_signing_key, worker_settings.username_hmac_key)
    before = TokenSigner(SecretStr(jwt), timedelta(minutes=15), FakeClock()).username_key()  # đường backend trước A2
    assert worker_key == before
    for ghost in ("matkhau123", "khong.co.ai", "nv999"):
        expected = "h:" + hmac.new(bytes.fromhex(_derived_hex(jwt)), ghost.encode("utf-8"), hashlib.sha256).hexdigest()
        assert stored_username(ghost, known=False, key=before) == expected
        assert stored_username(ghost, known=False, key=worker_key) == expected
        assert failure_keys(ghost, known=False, key=worker_key) == (expected,)


def test_a2_backend_runtime_refuses_when_derived_and_given_keys_differ() -> None:
    """Backend có JWT_SIGNING_KEY + USERNAME_HMAC_KEY lệch (xoay JWT, quên tạo lại khoá) → `approver_users` (gọi trong `open_runtime`)
    ném RuntimeError → runtime không mở (route 503), thông báo không có khoá."""
    from app.graph.wiring import approver_users

    jwt = secrets.token_urlsafe(32)
    stale = _derived_hex(secrets.token_urlsafe(32))  # khoá dẫn xuất từ JWT CŨ
    backend = Settings(_env_file=None, jwt_signing_key=jwt, username_hmac_key=stale)  # type: ignore[call-arg,arg-type]
    with pytest.raises(RuntimeError, match="USERNAME_HMAC_KEY") as e:
        approver_users(backend, SimpleNamespace(main=None), sink=None)  # type: ignore[arg-type]
    assert stale not in str(e.value) and jwt not in str(e.value)
    same = Settings(_env_file=None, jwt_signing_key=jwt, username_hmac_key=_derived_hex(jwt))  # type: ignore[call-arg,arg-type]
    assert approver_users(same, SimpleNamespace(main=None), sink=None).available is True  # type: ignore[arg-type]
