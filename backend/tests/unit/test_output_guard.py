"""Output guard (phase3 mục 10.3; PLAN-3g S1): g4 + phần unit của g20 (câu hỏi B11 chứa canary).

Guard thật trên `config/privacy_patterns.json` + `config/prompts/*.yaml` của repo. g26 (không chặn nhầm KB fixture) ở
`test_b10_answer.py` — cần `render_answer`.
"""

from pathlib import Path

import pytest
from app.guard.output import SYSTEM_SHINGLE, OutputGuard
from app.llm.registry import load_prompts
from app.settings import Settings
from pydantic import ValidationError

CONFIG = Path(__file__).resolve().parents[3] / "config"
CANARY = "CANARY-ZX81-OUT"


@pytest.fixture(scope="module")
def guard() -> OutputGuard:
    return OutputGuard.from_config(CONFIG, [CANARY])


def _pem() -> str:
    kind = "RSA " + "PRIVATE KEY"  # ghép lúc chạy (gitleaks)
    return f"-----BEGIN {kind}-----\nMIIEowIBAAKCAQEA7x\n-----END {kind}-----"


def _jwt() -> str:
    return ".".join(("eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiJudjAwMSJ9", "c2lnbmF0dXJlLXRlc3Q"))  # noqa: FLY002


def _system_line() -> str:
    """Một dòng `system` thật ≥ 40 ký tự (b10_answer)."""
    prompts = {p.id: p for p in load_prompts(CONFIG / "prompts")}
    line = next(ln for ln in prompts["b10_answer"].spec.system.splitlines() if len(ln.strip()) >= 60)
    return line.strip()


# ---- g4: mật khẩu, canary, dòng system prompt → chặn; câu thường → qua ------------------------------------


def test_g4_four_cases(guard: OutputGuard) -> None:
    assert guard.violation("Mật khẩu VPN của bạn là Abc@12345, hãy đăng nhập lại.") == "secret"
    assert guard.violation(f"Bạn làm theo hướng dẫn. Mã tham chiếu {CANARY}.") == "canary"
    assert guard.violation(f"Theo quy định: {_system_line()}") == "system_prompt"
    assert guard.violation("VPN công ty dùng cổng 443 (SSL). Bạn mở ứng dụng ABC Connect rồi chọn Kết nối.") is None
    assert guard.violates("pwd=Q!w2e3r4") and not guard.violates("Bạn khởi động lại máy nhé.")


@pytest.mark.parametrize("text", [
    _pem(), f"token {_jwt()}", "key sk-" + "a1B2c3D4e5F6g7H8i9J0", "mk: Xy9!abc", "OTP là 482913",
    "chuỗi a8F3kL9qZ2xW7vB4nM6tR1yU lạ",
])  # fmt: skip
def test_g4_each_secret_rule_blocks(guard: OutputGuard, text: str) -> None:
    """Luật bí mật 1–6 (PEM, JWT, API key, cụm mật khẩu, OTP, entropy) — mỗi luật một ca."""
    assert guard.violation(text) == "secret"


def test_g4_pii_is_not_an_output_violation(guard: OutputGuard) -> None:
    """Output guard chỉ xét BÍ MẬT (luật 1–6), không xét PII: câu trả lời KB có email/hotline công ty vẫn gửi được."""
    assert guard.violation("Liên hệ helpdesk@congty-abc.vn hoặc gọi 0912345678.") is None


def test_g4_canary_case_and_l0_insensitive(guard: OutputGuard) -> None:
    assert guard.violation(f"xem {CANARY.lower()} nhé") == "canary"
    assert guard.violation("xem ＣＡＮＡＲＹ-ＺＸ81-ＯＵＴ nhé") == "canary"  # full-width → L0 (NFKC)


def test_g4_system_line_after_case_and_whitespace_changes(guard: OutputGuard) -> None:
    line = _system_line()
    assert guard.violation("  ".join(line.upper().split())) == "system_prompt"
    assert guard.violation(line[: SYSTEM_SHINGLE - 1]) is None  # < 40 ký tự trùng → không phải lộ prompt


def test_g4_every_loaded_prompt_is_covered(guard: OutputGuard) -> None:
    for p in load_prompts(CONFIG / "prompts"):
        long_lines = [ln.strip() for ln in p.spec.system.splitlines() if len(" ".join(ln.split())) >= SYSTEM_SHINGLE]
        assert long_lines, p.id
        for ln in long_lines:
            assert guard.violation(f"… {ln} …") == "system_prompt", (p.id, ln)


def test_q3g8_password_policy_sentence_is_blocked(guard: OutputGuard) -> None:
    """Q-3g-8 (chốt giữ chặn): câu KB kiểu chính sách mật khẩu cũng bị luật 4 chặn — probe mốc G."""
    assert guard.violation("Mật khẩu: tối thiểu 12 ký tự") == "secret"


def test_output_guard_needs_system_lines() -> None:
    from app.guard.patterns import privacy_patterns

    with pytest.raises(ValueError, match="dòng system"):
        OutputGuard(privacy_patterns(CONFIG), [], ["ngắn"])


# ---- g20 (phần unit): câu hỏi B11 do LLM viết chứa canary → chặn ------------------------------------------


def test_g20_unit_question_with_canary_blocked(guard: OutputGuard) -> None:
    q = f"Bạn cho mình xin mã thiết bị (ví dụ LAP-0342) nhé. {CANARY}"
    assert guard.violation(q) == "canary"
    assert guard.violation("Bạn cho mình xin mã thiết bị (ví dụ LAP-0342) để kiểm tra chứng chỉ VPN nhé.") is None


# ---- cấu hình ---------------------------------------------------------------------------------------------


def test_output_canaries_setting() -> None:
    assert Settings(_env_file=None).output_canaries == []  # type: ignore[call-arg]
    s = Settings(_env_file=None, output_canaries=["  Canary#7781xyz  "])  # type: ignore[call-arg]
    assert s.output_canaries == ["Canary#7781xyz"]
    with pytest.raises(ValidationError):
        Settings(_env_file=None, output_canaries=["abc"])  # type: ignore[call-arg]  # < 8 ký tự
