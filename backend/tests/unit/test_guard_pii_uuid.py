"""be-pii-uuid (ĐP duyệt 02/11 22:25): luật PII không che bên trong UUID 8-4-4-4-12 (`pii_exclude` trong `config/privacy_patterns.json`).

Lỗi gốc: link email `/chat/23d1ce34-f9e3-43b0-8471-62786daeeefe` — mẫu phone cho phép một dấu gạch giữa các chữ số nên "0-8471-62786" bị
che thành `<SĐT_1>` (test_email_outbox_pg đỏ ngẫu nhiên vì ticket_id là uuid4). Chỉ miễn đúng dạng UUID, KHÔNG miễn URL; 10 luật, mẫu phone,
luật bí mật/entropy không đổi. Guard thật trên file mẫu của repo.
"""

import random
import uuid
from pathlib import Path
from typing import Any

import pytest
from app.guard.patterns import PRIVACY_FILE, PatternFileError, load_privacy_patterns
from app.guard.privacy import RegexPrivacyGuard
from tests.unit.test_guard_privacy import _broken, _set

CONFIG = Path(__file__).resolve().parents[3] / "config"
BUG_UUID = "23d1ce34-f9e3-43b0-8471-62786daeeefe"


@pytest.fixture(scope="module")
def guard() -> RegexPrivacyGuard:
    return RegexPrivacyGuard(load_privacy_patterns(CONFIG / PRIVACY_FILE), ["company.vn"])


def _unchanged(guard: RegexPrivacyGuard, text: str) -> None:
    r = guard.redact_text(text)
    assert (r.text, r.pii_found, r.secrets_found, r.notices) == (text, {}, 0, []), r


# ---- UUID không bị che ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        BUG_UUID,
        f"Xem chi tiết: https://demo.local/chat/{BUG_UUID}",
        f"/chat/{BUG_UUID}",
        f"Mã ticket {BUG_UUID.upper()} đang chờ duyệt.",
        "aaaaaaaa-bbbb-cccc-dddd-012345678901",  # nhóm cuối 12 chữ số liền bắt đầu 0 — không thành CCCD
        "Ticket 00000000-0000-0000-0000-090123456789 xong",  # nhóm cuối giống SĐT/CCCD
        "stk ở ticket 0a1b2c3d-0901-2345-6789-012345678901",  # có từ khoá STK trước — vẫn là UUID
    ],
)
def test_uuid_is_never_masked(guard: RegexPrivacyGuard, text: str) -> None:
    _unchanged(guard, text)


def test_seeded_random_uuid4_never_masked_as_pii(guard: RegexPrivacyGuard) -> None:
    rng = random.Random(20261102)
    hits = 0
    for _ in range(5000):
        u = str(uuid.UUID(int=rng.getrandbits(128), version=4))
        r = guard.redact_text(f"Xem chi tiết: https://demo.local/chat/{u}")
        hits += bool(r.pii_found)
    assert hits == 0


# ---- SĐT thật vẫn bị che --------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phone",
    ["0901234567", "090-123-4567", "090 123 4567", "0901.234.567", "+84 90 123 4567", "+84901234567"],
)
def test_real_phone_still_masked(guard: RegexPrivacyGuard, phone: str) -> None:
    r = guard.redact_text(f"Liên hệ mình qua {phone} nhé")
    assert r.text == "Liên hệ mình qua <SĐT_1> nhé" and r.pii_found == {"SĐT": 1}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("https://zalo.me/0901234567", "https://zalo.me/<SĐT_1>"),  # KHÔNG miễn URL
        ("https://demo.local/lien-he?phone=0901234567", "https://demo.local/lien-he?phone=<SĐT_1>"),
        (f"ticket {BUG_UUID} sđt 0901234567", f"ticket {BUG_UUID} sđt <SĐT_1>"),  # cạnh UUID, cách dấu cách
        (f"{BUG_UUID}-0901234567", f"{BUG_UUID}-<SĐT_1>"),  # dính UUID bằng dấu gạch — vẫn che đúng 1 lần
        (f"https://demo.local/chat/{BUG_UUID}?phone=0901234567", f"https://demo.local/chat/{BUG_UUID}?phone=<SĐT_1>"),
    ],
)
def test_phone_next_to_uuid_or_in_url_still_masked(guard: RegexPrivacyGuard, text: str, expected: str) -> None:
    r = guard.redact_text(text)
    assert r.text == expected and r.pii_found == {"SĐT": 1}


@pytest.mark.parametrize(
    ("text", "label"),
    [
        ("23d1ce34-f9e3-43b0-8471-62786daeeef", "SĐT"),  # nhóm cuối 11 ký tự: không phải UUID → luật cũ
        ("23d1ce34-f9e3-43b0-8471-62786daeeefe0", "SĐT"),  # nhóm cuối 13 ký tự
        ("23d1ce3-f9e3-43b0-8471-62786daeeefe", "SĐT"),  # nhóm đầu 7 ký tự
        ("aaaaaaaa-bbbb-cccc-ddd-012345678901", "CCCD"),  # nhóm 4 chỉ 3 ký tự → CCCD như cũ
    ],
)
def test_uuid_lookalike_with_wrong_group_lengths_keeps_old_rules(guard: RegexPrivacyGuard, text: str, label: str) -> None:
    assert guard.redact_text(text).pii_found == {label: 1}


def test_other_pii_unchanged(guard: RegexPrivacyGuard) -> None:
    r = guard.redact_text("CCCD 012345678901, email a.b@gmail.com, stk 1234 5678 9012")
    assert r.pii_found == {"CCCD": 1, "EMAIL": 1, "STK": 1}
    assert guard.redact_text("email sếp a.b@company.vn").pii_found == {}


# ---- file mẫu --------------------------------------------------------------------------------------------------------------------


def test_repo_file_declares_uuid_exclusion_only() -> None:
    patterns = load_privacy_patterns(CONFIG / PRIVACY_FILE)
    assert [e for e, _ in patterns.pii_exclude] == ["uuid"]
    assert [r.id for r in patterns.rules if r.kind == "pii"] == ["email", "phone", "cccd", "bank_account"]


BROKEN: dict[str, Any] = {
    "thiếu pii_exclude": lambda d: d.pop("pii_exclude"),
    "pii_exclude rỗng": _set(("pii_exclude",), []),
    "regex pii_exclude sai": _set(("pii_exclude", 0, "regex"), "[0-9a-f{8}"),
    "trường lạ": _set(("pii_exclude", 0, "flags"), "i"),
}


@pytest.mark.parametrize("name", BROKEN)
def test_broken_pii_exclude_refuses_to_load(tmp_path: Path, name: str) -> None:
    folder = _broken(tmp_path, BROKEN[name])
    with pytest.raises(PatternFileError):
        load_privacy_patterns(folder / PRIVACY_FILE)
