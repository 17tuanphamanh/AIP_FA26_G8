"""Username đăng nhập KHÔNG có dòng `users` → lưu băm (Phase 4 P2–P3; chốt Q-3e-14 + Q-4-S).

Vì sao: mật khẩu chỉ gồm chữ thường + số gõ nhầm vào ô username vẫn khớp `USERNAME_PATTERN` (3e) và từng được lưu nguyên văn ở
`security_events.username_attempted` (+ `alerts` khi khoá). Username CÓ dòng `users` giữ nguyên văn (người thật — cần cho điều tra).

- Khoá: `HMAC-SHA256(JWT_SIGNING_KEY, "auth-username-v1")` (Q-4-S); backend tính MỘT lần lúc dựng `AuthService` (qua
  `TokenSigner.username_key`), không log. A2 (bn-a): worker KHÔNG nhận `JWT_SIGNING_KEY` — nhận đúng khoá dẫn xuất đó qua
  `USERNAME_HMAC_KEY` (tạo bằng `scripts/ops/derive_username_key.py`); `resolve_key` chọn nguồn và từ chối khi hai nguồn lệch — username ma
  của dữ liệu hiện có KHÔNG đổi.
- Giá trị lưu: `"h:" + HMAC-SHA256(khoá, username).hexdigest()` — 66 ký tự ≤ `String(128)`, không đổi schema.
- Đếm/khoá (`count_failures` qua view `auth_failures` trên `security_events`) dùng CÙNG giá trị → username ma vẫn bị khoá như cũ.
"""

import hashlib
import hmac

from pydantic import SecretStr

USERNAME_KEY_LABEL = b"auth-username-v1"
HASH_PREFIX = "h:"


def username_key(jwt_signing_key: bytes) -> bytes:
    """Khoá HMAC dẫn xuất từ khoá ký JWT (Q-4-S) — khác `JWT_SIGNING_KEY` → khác khoá → khác giá trị lưu."""
    return hmac.new(jwt_signing_key, USERNAME_KEY_LABEL, hashlib.sha256).digest()


def resolve_key(jwt_signing_key: SecretStr | None, username_hmac_key: SecretStr | None) -> bytes | None:
    """Khoá HMAC username ma của tiến trình: có `USERNAME_HMAC_KEY` → dùng nó (CÓ cả `JWT_SIGNING_KEY` thì phải bằng khoá dẫn xuất — lệch thì
    backend và worker băm khác nhau, đếm/khoá username ma sai → RuntimeError, không in khoá); chỉ có JWT → dẫn xuất (Q-4-S); không có → None."""
    derived = username_key(jwt_signing_key.get_secret_value().encode("utf-8")) if jwt_signing_key is not None else None
    if username_hmac_key is None:
        return derived
    given = bytes.fromhex(username_hmac_key.get_secret_value())
    if derived is not None and not hmac.compare_digest(given, derived):
        raise RuntimeError(
            "USERNAME_HMAC_KEY không khớp khoá dẫn xuất từ JWT_SIGNING_KEY (username ma sẽ băm khác) — từ chối khởi động; "
            "tạo lại bằng scripts/ops/derive_username_key.py"
        )
    return given


def stored_username(username: str, *, known: bool, key: bytes) -> str:
    """`known` (username có dòng `users`) → nguyên văn; không → `"h:" + 64 hex`. Hàm thuần, tất định theo (username, khoá)."""
    if known:
        return username
    return HASH_PREFIX + hmac.new(key, username.encode("utf-8"), hashlib.sha256).hexdigest()


def failure_keys(username: str, *, known: bool, key: bytes) -> tuple[str, ...]:
    """Giá trị đếm lỗi (view `auth_failures`, MỘT câu `IN`): username ma → (bản băm,); có dòng `users` → (nguyên văn, bản băm) —
    lần sai ghi lúc CHƯA có dòng vẫn được đếm sau khi dòng được tạo (Q-4a-5). Dùng chung cho `AuthService` và `AdUserSync`."""
    hashed = stored_username(username, known=False, key=key)
    return (username, hashed) if known else (hashed,)
