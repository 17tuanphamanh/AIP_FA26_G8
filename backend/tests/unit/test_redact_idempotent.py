"""Q-3g-4 (chốt 3g): `clarify_wait` che lại câu trả lời bằng `redact_text` THUẦN dù API đã che — phải idempotent:
che(che(x)) == che(x) với MỌI mẫu của e-test 3e (không idempotent → nhãn/mặt nạ bị che chồng, câu lưu khác câu gửi LLM).

Mẫu = mọi chuỗi hằng trong test guard của 3e (`test_guard_privacy.py`, `test_guard_api.py`) + ca dựng lúc chạy (PEM, JWT,
bí mật của desk). Guard thật trên `config/privacy_patterns.json` của repo.
"""

import ast
from pathlib import Path

import pytest
from app.guard.patterns import PRIVACY_FILE, load_privacy_patterns
from app.guard.privacy import NotRedactingGuard, RegexPrivacyGuard
from tests.fakes.desk import SECRET
from tests.unit import test_guard_privacy as e_tests

CONFIG = Path(__file__).resolve().parents[3] / "config"
SOURCES = ("test_guard_privacy.py", "test_guard_api.py")


def _samples() -> list[str]:
    out: set[str] = {SECRET, e_tests._pem(), e_tests._jwt(), *(c[0] for c in e_tests.E2_CASES)}
    for name in SOURCES:
        tree = ast.parse((Path(__file__).parent / name).read_text(encoding="utf-8"))
        out |= {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and len(n.value) >= 3}  # fmt: skip
    return sorted(out)


SAMPLES = _samples()


@pytest.fixture(scope="module")
def guard() -> RegexPrivacyGuard:
    return RegexPrivacyGuard(load_privacy_patterns(CONFIG / PRIVACY_FILE), ["congty-abc.vn"])


def test_sample_list_is_large() -> None:
    assert len(SAMPLES) >= 150  # 3.9: danh sách quét không rỗng
    assert any("[BÍ_MẬT" in s or "mật khẩu" in s for s in SAMPLES)


def test_q3g4_redact_is_idempotent_on_every_3e_sample(guard: RegexPrivacyGuard) -> None:
    bad = []
    for s in SAMPLES:
        once = guard.redact_text(s)
        twice = guard.redact_text(once.text)
        if twice.text != once.text:
            bad.append(s[:60])
    assert bad == []


def test_q3g4_redacted_secret_does_not_leak_on_second_pass(guard: RegexPrivacyGuard) -> None:
    once = guard.redact_text(f"máy LAP-0342, mật khẩu là {SECRET}")
    assert SECRET not in once.text and "LAP-0342" in once.text
    assert guard.redact_text(once.text).text == once.text


def test_not_redacting_guard_has_pure_redact_text() -> None:
    assert NotRedactingGuard().redact_text("x").text == "x"  # PRIVACY_GUARD=none (dev/test) vẫn đủ giao diện node
