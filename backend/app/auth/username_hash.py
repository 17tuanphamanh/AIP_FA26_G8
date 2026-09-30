"""Username đăng nhập KHÔNG có dòng `users` → lưu băm (Phase 4 P2–P3; chốt Q-3e-14 + Q-4-S).

Vì sao: mật khẩu chỉ gồm chữ thường + số gõ nhầm vào ô username vẫn khớp `USERNAME_PATTERN` (3e) và từng được lưu nguyên văn ở
`security_events.username_attempted` (+ `alerts` khi khoá). Username CÓ dòng `users` giữ nguyên văn (người thật — cần cho điều tra).

- Khoá: `HMAC-SHA256(JWT_SIGNING_KEY, "auth-username-v1")` (Q-4-S) — KHÔNG thêm biến `.env`; tính MỘT lần lúc dựng `AuthService`
  (qua `TokenSigner.username_key`), không log, không nằm trong `Settings`.
- Giá trị lưu: `"h:" + HMAC-SHA256(khoá, username).hexdigest()` — 66 ký tự ≤ `String(128)`, không đổi schema.
- Đếm/khoá (`count_failures` qua view `auth_failures` trên `security_events`) dùng CÙNG giá trị → username ma vẫn bị khoá như cũ.
"""

import hashlib
import hmac

USERNAME_KEY_LABEL = b"auth-username-v1"
HASH_PREFIX = "h:"


def username_key(jwt_signing_key: bytes) -> bytes:
    """Khoá HMAC dẫn xuất từ khoá ký JWT (Q-4-S) — khác `JWT_SIGNING_KEY` → khác khoá → khác giá trị lưu."""
    return hmac.new(jwt_signing_key, USERNAME_KEY_LABEL, hashlib.sha256).digest()


def stored_username(username: str, *, known: bool, key: bytes) -> str:
    """`known` (username có dòng `users`) → nguyên văn; không → `"h:" + 64 hex`. Hàm thuần, tất định theo (username, khoá)."""
    if known:
        return username
    return HASH_PREFIX + hmac.new(key, username.encode("utf-8"), hashlib.sha256).hexdigest()
