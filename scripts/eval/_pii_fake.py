"""Chèn PII giả (tất định) rồi cho qua ĐÚNG L0 + L1 thật (gói 1, D-52; `dac-ta-bat-2-model.md` 4.3, 6.1, 9.3).

Dùng chung cho nghiệm thu thay nhãn che của B2 (`b2_tau_select.py prepare --pii-variants`) và phép đo nhãn che của B3
(`b3_offline.py mask`). Không dùng 22 câu của Dương (chọn và nghiệm thu trên cùng câu là vòng tròn).

- `insert_pii(text, seed=, item_id=)`: chọn 1–3 mục trong {SĐT, email ngoài miền công ty, CCCD, số tài khoản, mật khẩu} theo
  `sha256(seed|item_id)` (cùng đầu vào → cùng kết quả), chèn vào đầu hoặc cuối câu. Giá trị giả, khớp mẫu của
  `config/privacy_patterns.json`.
- `redact(text)`: `RegexPrivacyGuard` thật (L0 bên trong) từ `config/privacy_patterns.json` của repo + miền email công ty mặc định
  của Settings (không đọc file env) — đúng bước API làm trước khi lưu ticket.
- `l0_only(text)`: chỉ L0 (bản "gốc" của nghiệm thu — Q-B2R-7).
Không log văn bản.
"""

import hashlib
import random
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PRIVACY_FILE = REPO / "config" / "privacy_patterns.json"
KINDS = ("phone", "email", "cccd", "bank", "password")


def _digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(n))


def _fake(kind: str, rng: random.Random) -> str:
    if kind == "phone":
        return f"Số liên hệ của mình là 0{rng.choice('35789')}{_digits(rng, 8)}."
    if kind == "email":
        return f"Email cá nhân: user{_digits(rng, 4)}.test@gmail.com."
    if kind == "cccd":
        return f"CCCD 0{_digits(rng, 2)}{rng.choice('0123')}{_digits(rng, 8)}."
    if kind == "bank":
        return f"STK {rng.choice('123456789')}{_digits(rng, 11)}."
    return f"mật khẩu: Gx{_digits(rng, 3)}#{rng.choice('abcdef')}{_digits(rng, 2)}"


def insert_pii(text: str, *, seed: int, item_id: str) -> str:
    rng = random.Random(int.from_bytes(hashlib.sha256(f"{seed}|{item_id}".encode()).digest()[:8], "big"))
    kinds = rng.sample(KINDS, rng.randint(1, 3))
    out = text.strip()
    for kind in kinds:
        piece = _fake(kind, rng)
        out = f"{piece} {out}" if rng.random() < 0.5 else f"{out} {piece}"
    return out


@lru_cache
def _guard() -> Any:
    from app.guard.patterns import load_privacy_patterns
    from app.guard.privacy import RegexPrivacyGuard
    from app.settings import Settings

    domains = Settings.model_fields["company_email_domains"].get_default(call_default_factory=True)
    return RegexPrivacyGuard(load_privacy_patterns(PRIVACY_FILE), domains)


def redact(text: str) -> Any:
    """`RedactionResult` của L0 + L1 thật."""
    return _guard().redact_text(text)


def l0_only(text: str) -> str:
    from app.guard.normalize import l0

    return l0(text)
