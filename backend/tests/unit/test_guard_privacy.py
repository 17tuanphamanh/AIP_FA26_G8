"""L0 + L1 privacy guard (phase3 mục 8.3, 8.7 e1–e4; PLAN-3e Q-3e-3, Q-3e-4, Q-3e-5, B3).

Guard thật trên `config/privacy_patterns.json` của repo. Mỗi ca "không che" có đối chứng: chuỗi đủ dài/đủ entropy để
luật 6 che nếu không có loại trừ — test đỏ khi bỏ loại trừ (M-3e-5, M-3e-13), không xanh oan vì chuỗi quá ngắn.
Test API (notices, 503, 422, security_events): `test_guard_api.py`.
"""

import json
import shutil
import time
from pathlib import Path
from typing import Any, Literal

import pytest
from app.guard.normalize import l0
from app.guard.patterns import (
    PRIVACY_FILE,
    PRIVACY_RULE_ORDER,
    PatternFileError,
    load_privacy_patterns,
)
from app.guard.privacy import NOTICE_PII, NOTICE_SECRET, RegexPrivacyGuard, shannon_bits
from app.main import create_app
from app.settings import Settings
from tests.fakes.runtime import no_runtime

CONFIG = Path(__file__).resolve().parents[3] / "config"
MASK = "[BÍ_MẬT_ĐÃ_ẨN]"


@pytest.fixture(scope="module")
def guard() -> RegexPrivacyGuard:
    return RegexPrivacyGuard(load_privacy_patterns(CONFIG / PRIVACY_FILE), ["congty-abc.vn"])


def _pem() -> str:
    # Ghép lúc chạy: viết liền thì gitleaks coi là khoá thật (như tests/fakes/desk.SECRET).
    kind = "RSA " + "PRIVATE KEY"
    return f"-----BEGIN {kind}-----\nMIIEowIBAAKCAQEA7x\nq9Zk2pL\n-----END {kind}-----"


def _jwt() -> str:
    return ".".join(("eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiJudjAwMSJ9", "c2lnbmF0dXJlLXRlc3Q"))  # noqa: FLY002 — gitleaks


# (câu, giá trị gốc phải biến mất, nhãn phải có, secrets_found, pii_found)
E2_CASES: list[tuple[str, str, str, int, dict[str, int]]] = [
    ("gọi em số 0912345678 nhé", "0912345678", "<SĐT_1>", 0, {"SĐT": 1}),
    ("sđt +84 912 345 678", "912 345 678", "<SĐT_1>", 0, {"SĐT": 1}),
    ("liên hệ 0387.654.321 giờ hành chính", "0387.654.321", "<SĐT_1>", 0, {"SĐT": 1}),
    ("CCCD của tôi 079099012345", "079099012345", "<CCCD_1>", 0, {"CCCD": 1}),
    ("số căn cước 001204012345 cần cập nhật", "001204012345", "<CCCD_1>", 0, {"CCCD": 1}),
    ("gửi về nguyen.van.a1990@gmail.com giúp", "nguyen.van.a1990@gmail.com", "<EMAIL_1>", 0, {"EMAIL": 1}),
    ("mail riêng: tranthib@yahoo.com.vn", "tranthib@yahoo.com.vn", "<EMAIL_1>", 0, {"EMAIL": 1}),
    ("hộp thư hoangminhduc_1995@outlook.com lỗi", "hoangminhduc_1995@outlook.com", "<EMAIL_1>", 0, {"EMAIL": 1}),
    ("mật khẩu của tôi là Canary#7781xyz, reset giúp", "Canary#7781xyz", MASK, 1, {}),
    ("password: Hunter2!", "Hunter2!", MASK, 1, {}),
    ("mat khau moi la abc123xyz", "abc123xyz", MASK, 1, {}),
    ("pwd=Q!w2e3r4", "Q!w2e3r4", MASK, 1, {}),
    (f"token {_jwt()} hết hạn", _jwt(), MASK, 1, {}),
    (f"Authorization: Bearer {_jwt()}", _jwt(), MASK, 1, {}),
    (f"khoá:\n{_pem()}\nxong", "MIIEowIBAAKCAQEA7x", MASK, 1, {}),
    (f"{_pem().replace('RSA ', '')}", "q9Zk2pL", MASK, 1, {}),
    ("OTP là 482913", "482913", MASK, 1, {}),
    ("mã xác thực: 55123", "55123", MASK, 1, {}),
    ("stk 1903 6543 2109 87 Techcombank", "1903 6543 2109 87", "<STK_1>", 0, {"STK": 1}),
    ("số tài khoản: 0071000123456", "0071000123456", "<STK_1>", 0, {"STK": 1}),
]


# ---- e2: 20 câu, 8 loại — 100 % che đúng loại, đếm đúng -------------------------------------------------


def test_e2_twenty_cases_cover_eight_kinds() -> None:
    assert len(E2_CASES) == 20
    labels = {label.split("_")[0].strip("<[") for _, _, label, _, _ in E2_CASES}
    assert labels == {"SĐT", "CCCD", "EMAIL", "BÍ", "STK"}  # PEM, JWT, mật khẩu, OTP cùng nhãn bí mật


@pytest.mark.parametrize(("text", "value", "label", "secrets", "pii"), E2_CASES)
def test_e2_redacts_by_kind(
    guard: RegexPrivacyGuard, text: str, value: str, label: str, secrets: int, pii: dict[str, int]
) -> None:
    r = guard.redact_text(text)
    assert value not in r.text
    assert label in r.text
    assert (r.secrets_found, r.pii_found) == (secrets, pii)
    assert r.pii_map_id is None  # 3-Q23: không lưu ánh xạ


def test_e2_notices_verbatim(guard: RegexPrivacyGuard) -> None:
    assert guard.redact_text("mật khẩu là Abc@123").notices == [NOTICE_SECRET]
    assert guard.redact_text("gọi 0912345678").notices == [NOTICE_PII]
    assert guard.redact_text("mk: X9 gọi 0912345678").notices == [NOTICE_SECRET, NOTICE_PII]
    assert guard.redact_text("VPN lỗi 809").notices == []
    assert NOTICE_SECRET == "Vui lòng không gửi mật khẩu hoặc mã bí mật qua chat. Phần đó đã được ẩn và không được lưu."
    assert NOTICE_PII == "Một số thông tin cá nhân trong tin nhắn đã được ẩn."


# ---- e3: không che nhầm ---------------------------------------------------------------------------------


E3_KEEP = ["LAP-0342", "\\\\fs01\\finance\\Q3", "0x8004010F", "nguyen.van.a", "a@congty-abc.vn", "lỗi 809"]


@pytest.mark.parametrize("text", E3_KEEP)
def test_e3_keeps_identifiers(guard: RegexPrivacyGuard, text: str) -> None:
    r = guard.redact_text(text)
    assert (r.text, r.secrets_found, r.pii_found) == (text, 0, {})


# Đối chứng M-3e-5 / M-3e-13: dài ≥ 20, entropy ≥ 4,0 → luật 6 sẽ che nếu thiếu loại trừ tương ứng.
# Q-3e-10: "đường dẫn" = có \, hoặc bắt đầu /, ~/, ./, ../, <ổ đĩa>: (URL là loại trừ riêng).
LONG_KEEP = [
    ("path", "C:\\Users\\nv001\\AppData\\Local\\Temp"),
    ("path", "\\\\fs01\\finance\\Q3\\BaoCao_2026-Q3v2.xlsx"),
    ("path", "C:/Users/nv001/AppData/Local/Temp"),
    ("path", "/home/nv001/.config/abc-connect/profile.xml"),
    ("path", "~/Downloads/ABCConnect-3.2.1.pkg"),
    ("path", "./scripts/Fix-VpnProfile_v2.ps1"),
    ("url", "https://vpn.congty-abc.vn/portal/login?next=abc"),
    ("email", "nguyen.van.a.work2024@congty-abc.vn"),
]


@pytest.mark.parametrize(("rule", "token"), LONG_KEEP)
def test_e3_long_high_entropy_tokens_kept_by_exclusion(guard: RegexPrivacyGuard, rule: str, token: str) -> None:
    assert len(token) >= 20 and shannon_bits(token) >= 4.0, "mẫu phải đủ để luật 6 che nếu không loại trừ"
    r = guard.redact_text(f"xem {token} giúp")
    assert (r.text, r.secrets_found) == (f"xem {token} giúp", 0)


def test_q3e3_personal_email_high_entropy_is_email_not_secret(guard: RegexPrivacyGuard) -> None:
    email = "phamtuananh.work2024@yahoo.com.vn"
    assert len(email) >= 20 and shannon_bits(email) >= 4.0
    r = guard.redact_text(f"gửi {email} nhé")
    assert (r.text, r.secrets_found, r.pii_found) == ("gửi <EMAIL_1> nhé", 0, {"EMAIL": 1})


def test_rule6_masks_random_token(guard: RegexPrivacyGuard) -> None:
    r = guard.redact_text("chuỗi a8F3kL9qZ2xW7vB4nM6tR1yU lạ")
    assert (r.text, r.secrets_found) == (f"chuỗi {MASK} lạ", 1)


def test_q3e10_base64_key_with_slash_masked(guard: RegexPrivacyGuard) -> None:
    """Q-3e-10 (M-3e-15): trước đây mọi token có "/" được coi là đường dẫn → khoá base64 có "/" lọt luật 6."""
    blob = "/".join(("wJalrXUtnFEMI", "K7MDENG", "bPxRfiCY" + "EXAMPLE" + "KEY"))  # ghép lúc chạy (gitleaks)
    assert len(blob) == 40 and shannon_bits(blob) >= 4.0
    r = guard.redact_text(f"secret key {blob} của AWS")
    assert (r.text, r.secrets_found) == (f"secret key {MASK} của AWS", 1)


def test_q3e10_relative_path_below_threshold_kept(guard: RegexPrivacyGuard) -> None:
    token = "share/it/vpn-setup.pdf"
    assert len(token) >= 20 and shannon_bits(token) < 4.0  # dưới ngưỡng: luật 6 không đụng tới
    assert guard.redact_text(f"tải {token} về").text == f"tải {token} về"


# Q-3e-11: đường dẫn tương đối = có "/" VÀ đoạn cuối có đuôi trong danh sách CỐ ĐỊNH (loại trừ `file_path`).
@pytest.mark.parametrize("token", [
    "KeToan/BaoCao/Q3_2026.xlsx",
    "PhongIT/CaiDat/VPN_Setup-v3.2.msi",
    "HR/HopDong/NV0417_2026-09.pdf",
])  # fmt: skip
def test_q3e11_relative_path_known_extension_kept(guard: RegexPrivacyGuard, token: str) -> None:
    assert len(token) >= 20 and shannon_bits(token) >= 4.0  # trên ngưỡng: chỉ loại trừ `file_path` giữ được
    r = guard.redact_text(f"mở {token} lỗi")
    assert (r.text, r.secrets_found) == (f"mở {token} lỗi", 0)


# Đối chứng M-3e-16: đuôi lạ / đuôi không nằm ở đoạn cuối / chữ hoa → vẫn xét entropy (an toàn hơn: che).
@pytest.mark.parametrize("suffix", [".abc12", ".xlsxz", ".XLSX"])
def test_q3e11_base64_slash_unknown_extension_masked(guard: RegexPrivacyGuard, suffix: str) -> None:
    blob = "/".join(("q9Zk3LxW7vB4" + "nM6tR1yU", "aP8fH2jD5sG0")) + suffix  # ghép lúc chạy (gitleaks)
    assert len(blob) >= 20 and shannon_bits(blob) >= 4.0
    r = guard.redact_text(f"key {blob} nhé")
    assert (r.text, r.secrets_found) == (f"key {MASK} nhé", 1)


def test_q3e11_extension_must_be_in_last_segment(guard: RegexPrivacyGuard) -> None:
    blob = "/".join(("q9Zk3LxW7vB4.xlsx", "nM6tR1yU" + "aP8fH2jD5sG0"))
    assert shannon_bits(blob) >= 4.0
    assert guard.redact_text(f"key {blob} nhé").text == f"key {MASK} nhé"


# ---- e4: cùng giá trị → cùng nhãn; không lưu ánh xạ ----------------------------------------------------


def test_e4_same_phone_same_label(guard: RegexPrivacyGuard) -> None:
    r = guard.redact_text("gọi 0912345678, nếu bận gọi lại 0912 345 678 hoặc +84912345678; sếp 0987654321")
    assert r.text == "gọi <SĐT_1>, nếu bận gọi lại <SĐT_1> hoặc <SĐT_1>; sếp <SĐT_2>"
    assert r.pii_found == {"SĐT": 4}  # đếm số chỗ bị thay


def test_e4_numbering_restarts_per_text(guard: RegexPrivacyGuard) -> None:
    assert guard.redact_text("0987654321").text == "<SĐT_1>"
    assert guard.redact_text("0912345678").text == "<SĐT_1>"


# ---- Q-3e-4: cụm mật khẩu (B) + luật (a), (b) --------------------------------------------------------


@pytest.mark.parametrize("text", [
    "mật khẩu cũ của tôi là Abc@123", "mật khẩu tôi là Abc@123", "mật khẩu hiện tại là Abc@123",
    "mật khẩu email là Abc@123", "mật khẩu mới là: Abc@123", "pass của mình: Abc@123", "mk: Abc@123", "mk=Abc@123",
    "mật khẩu hiện tại của tôi là Abc@123",  # Q-3e-9: 4 từ đệm
])  # fmt: skip
def test_q3e4_password_phrases_masked(guard: RegexPrivacyGuard, text: str) -> None:
    r = guard.redact_text(text)
    assert "Abc@123" not in r.text and r.text.endswith(MASK) and r.secrets_found == 1


@pytest.mark.parametrize("text", [
    "mật khẩu hết hạn lỗi là 809",  # (a) từ đệm "lỗi" → không coi 809 là mật khẩu
    "mật khẩu bị khoá mã là 0x8004010F",  # (a) "mã"
    "password reset error: 0x80070005",  # (a) "error"
    "mk là nhân viên mới",  # (b) "mk" = "mình" khi đi với "là"
    "mk la nv phong ke toan",  # (b) không dấu
    "mật khẩu đã đổi, tài khoản là nv001",  # dấu phẩy chặn từ đệm
])  # fmt: skip
def test_q3e4_not_a_password(guard: RegexPrivacyGuard, text: str) -> None:
    r = guard.redact_text(text)
    assert (r.text, r.secrets_found) == (text, 0)


def test_q3e9_five_fillers_not_matched(guard: RegexPrivacyGuard) -> None:
    text = "mật khẩu đăng nhập hiện tại của tôi là Abc@123"  # 5 từ đệm > 4 (chốt Q-3e-9) — giới hạn biết trước
    assert guard.redact_text(text).secrets_found == 0


@pytest.mark.parametrize("text", [
    "mật khẩu wifi công ty là gì", "mật khẩu là gì?", "mat khau la gi", "pass là sao", "mật khẩu là bao nhiêu ký tự",
    "mật khẩu mới là nào vậy", "password: gì cũng được",
])  # fmt: skip
def test_q3e9_question_word_value_not_masked(guard: RegexPrivacyGuard, text: str) -> None:
    r = guard.redact_text(text)
    assert (r.text, r.secrets_found) == (text, 0)


@pytest.mark.parametrize(("text", "value"), [
    ("mật khẩu là gìn123", "gìn123"), ("mật khẩu là Gi@2026", "Gi@2026"), ("mk: sao123", "sao123"),
    ("mật khẩu là bao2026!", "bao2026!"),
])  # fmt: skip
def test_q3e9_question_word_prefix_still_masked(guard: RegexPrivacyGuard, text: str, value: str) -> None:
    r = guard.redact_text(text)
    assert value not in r.text and r.secrets_found == 1


# ---- L0 guard (Q-3e-5) dùng cho L1 ----------------------------------------------------------------------


@pytest.mark.parametrize("text", [
    "ｍật khẩu là Abc@123",  # full-width (e1 cho L1)
    "ｍａｔ ｋｈａｕ ｌａ Abc@123",
    "mật\u200b khẩu là Abc@123",  # zero-width
    "mật khẩu\u00ad là Abc@123",  # soft hyphen (Cf)
    "ma\u0302\u0323t khẩu là Abc@123",  # NFD
    "mật\u00a0khẩu\u2060 là Abc@123",  # NBSP + word joiner
])  # fmt: skip
def test_l0_variants_still_masked(guard: RegexPrivacyGuard, text: str) -> None:
    r = guard.redact_text(text)
    assert "Abc@123" not in r.text and r.secrets_found == 1


def test_l0_stored_text_is_normalized() -> None:
    # như core.normalize: giữ thụt đầu dòng + xuống dòng, gộp khoảng trắng trong dòng; NFKC; bỏ ký tự Cf
    assert l0("  VPN\u200b  ｌỗi ８０９\r\nx") == "  VPN lỗi 809\nx"


# ---- B3: 10.000 ký tự — L1 < 100 ms (L2 thêm ở S3) -------------------------------------------------------


def test_b3_ten_thousand_chars_under_100ms(guard: RegexPrivacyGuard) -> None:
    chunk = "mật khẩu hiện tại của tôi là Abc@123 gọi 0912345678 stk 19036543210987 lỗi 809 LAP-0342 "
    text = (chunk * (10_000 // len(chunk) + 1))[:10_000]
    guard.redact_text(text)  # làm nóng cache regex
    started = time.perf_counter()
    r = guard.redact_text(text)
    elapsed = time.perf_counter() - started
    assert r.secrets_found > 0 and "Abc@123" not in r.text
    assert elapsed < 0.1, f"L1 10.000 ký tự mất {elapsed * 1000:.1f} ms"


# ---- File mẫu hỏng → không khởi động -------------------------------------------------------------------


def _broken(tmp_path: Path, mutate: Any) -> Path:
    doc = json.loads((CONFIG / PRIVACY_FILE).read_text(encoding="utf-8"))
    mutate(doc)
    (tmp_path / PRIVACY_FILE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _set(path: tuple[Any, ...], value: Any) -> Any:
    def mutate(doc: Any) -> None:
        for key in path[:-1]:
            doc = doc[key]
        doc[path[-1]] = value

    return mutate


BROKEN = {
    "regex sai": _set(("rules", 3, "regex"), "(?P<v>[a-z"),
    "thiếu luật": lambda d: d["rules"].pop(),
    "sai thứ tự": lambda d: d["rules"].insert(0, d["rules"].pop(6)),
    "trường lạ": _set(("rules", 0, "flags"), "i"),
    "pii thiếu label": lambda d: d["rules"][6].pop("label"),
    "entropy có regex": _set(("rules", 5, "regex"), "x"),
    "loại trừ rỗng": _set(("entropy_exclude",), []),
    "regex loại trừ sai": _set(("entropy_exclude", 0, "regex"), "["),
}


@pytest.mark.parametrize("name", BROKEN)
def test_broken_pattern_file_refuses_to_load(tmp_path: Path, name: str) -> None:
    folder = _broken(tmp_path, BROKEN[name])
    with pytest.raises(PatternFileError):
        load_privacy_patterns(folder / PRIVACY_FILE)


def test_unreadable_json_refuses(tmp_path: Path) -> None:
    (tmp_path / PRIVACY_FILE).write_text("{không phải json", encoding="utf-8")
    with pytest.raises(PatternFileError):
        load_privacy_patterns(tmp_path / PRIVACY_FILE)


@pytest.mark.parametrize("env", ["dev", "prod"])
def test_create_app_refuses_broken_pattern_file(tmp_path: Path, env: Literal["dev", "prod"]) -> None:
    shutil.copytree(CONFIG, tmp_path / "config")
    _broken(tmp_path / "config", BROKEN["regex sai"])
    settings = Settings(_env_file=None, app_env=env, config_dir=tmp_path / "config")  # type: ignore[call-arg]
    with pytest.raises(PatternFileError):
        create_app(settings, health_checks={}, runtime=no_runtime)


def test_repo_file_has_ten_rules_in_order() -> None:
    patterns = load_privacy_patterns(CONFIG / PRIVACY_FILE)
    assert tuple(r.id for r in patterns.rules) == PRIVACY_RULE_ORDER
    assert len(PRIVACY_RULE_ORDER) == 10
    assert {e for e, _ in patterns.entropy_exclude} >= {"path", "file_path", "device_id", "hex_error", "url",
                                                         "username", "digits", "email"}  # fmt: skip


@pytest.mark.asyncio
async def test_worker_runtime_refuses_broken_pattern_file_before_db(tmp_path: Path) -> None:
    """`open_runtime` (worker và backend) kiểm file mẫu TRƯỚC khi đụng DB — engine chưa từng kết nối."""
    from app.db.session import create_engines
    from app.graph.wiring import open_runtime
    from pydantic import SecretStr

    shutil.copytree(CONFIG, tmp_path / "config")
    _broken(tmp_path / "config", BROKEN["thiếu luật"])
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, app_env="dev", llm_backend="scripted", ml_service_token=SecretStr("t" * 32),
        config_dir=tmp_path / "config", database_url="postgresql+psycopg://x@127.0.0.1:1/khong_co",
    )
    engines = create_engines(settings)
    with pytest.raises(PatternFileError):
        async with open_runtime(settings, engines, clock=None, can_execute=False):  # type: ignore[arg-type]
            pass
    await engines.dispose()
