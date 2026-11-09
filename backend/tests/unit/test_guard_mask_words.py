"""Gói 1 (D-52) — thay nhãn che trước khi model chặn tấn công chấm: `app.guard.mask_words` (hàm thuần).

Viết TỪ ĐẶC TẢ, trước code: `docs/spec/claude/dac-ta-bat-2-model.md` mục 4.3 (bảng 5 nhãn → bộ từ của Dương; regex
`\\[BÍ_MẬT_ĐÃ_ẨN\\]|<(SĐT|EMAIL|CCCD|STK)_\\d+>`; NFC trước khi so khớp; nhãn lấy từ `label`/`secret_mask` của
`config/privacy_patterns.json`, không chép tay), mục 8 (đủ 5 loại nhãn, nhiều nhãn một câu, chuỗi giống nhãn sai mẫu giữ
nguyên, chạy hai lần như một lần); `PLAN-B2REVIEW.md` mục 3.1, 3.3 C, mục 8 (chữ ký `MASK_WORDS`, `SECRET_WORD`,
`mask_regex`, `replace_masks`; label lạ → `PatternFileError`).

Phần ở node B2 (chỉ áp ở `review`, LLM chấm nhận bản chưa thay, audit `masks_replaced`) ở `test_b02_review.py` (DỪNG 2).
"""

import json
import unicodedata
from pathlib import Path

import pytest
from app.guard.mask_words import MASK_WORDS, SECRET_WORD, mask_regex, replace_masks
from app.guard.patterns import PatternFileError, PrivacyPatterns, load_privacy_patterns
from tests.unit._b2review import CONFIG

PRIVACY = CONFIG / "privacy_patterns.json"


def _patterns_with(tmp_path: Path, *, secret_mask: str | None = None, relabel: tuple[str, str] | None = None) -> PrivacyPatterns:
    """Bản sao `privacy_patterns.json` trong tmp, đổi `secret_mask` hoặc đổi `label` của một luật pii (id, nhãn mới)."""
    spec = json.loads(PRIVACY.read_text(encoding="utf-8"))
    if secret_mask is not None:
        spec["secret_mask"] = secret_mask
    if relabel is not None:
        rule_id, label = relabel
        [rule] = [r for r in spec["rules"] if r["id"] == rule_id]
        rule["label"] = label
    path = tmp_path / "privacy_patterns.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return load_privacy_patterns(path)


# ---- bộ từ (ĐT 4.3 — đúng bộ từ trong bàn giao của Dương) ----------------------------------------------------------------


def test_43_mask_words_exact() -> None:
    assert dict(MASK_WORDS) == {"SĐT": "số điện thoại", "EMAIL": "địa chỉ email", "CCCD": "số CCCD", "STK": "số tài khoản"}
    assert SECRET_WORD == "***"


def test_43_every_pii_label_in_config_has_a_word() -> None:
    """Nhãn pii của config hiện hành ⊆ bộ từ (lệch bộ từ thì không khởi động — PLAN 3.1)."""
    labels = {r.label for r in load_privacy_patterns(PRIVACY).rules if r.kind == "pii"}
    assert labels == set(MASK_WORDS)


# ---- C: đủ 5 loại nhãn ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("masked", "word"), [
    ("[BÍ_MẬT_ĐÃ_ẨN]", "***"),
    ("<SĐT_1>", "số điện thoại"),
    ("<EMAIL_2>", "địa chỉ email"),
    ("<CCCD_1>", "số CCCD"),
    ("<STK_10>", "số tài khoản"),
])  # fmt: skip
def test_c_five_label_kinds(masked: str, word: str) -> None:
    assert replace_masks(f"gửi giúp {masked} nhé") == (f"gửi giúp {word} nhé", 1)


def test_c_regex_built_from_config_matches_every_label() -> None:
    rx = mask_regex(load_privacy_patterns(PRIVACY))
    for label in ("[BÍ_MẬT_ĐÃ_ẨN]", "<SĐT_1>", "<EMAIL_12>", "<CCCD_3>", "<STK_7>"):
        assert rx.fullmatch(label), label


def test_c_many_labels_in_one_sentence_counted() -> None:
    text = "mật khẩu [BÍ_MẬT_ĐÃ_ẨN], gọi <SĐT_1> hoặc <SĐT_2>, mail <EMAIL_1>, STK <STK_1>, CCCD <CCCD_1>"
    want = "mật khẩu ***, gọi số điện thoại hoặc số điện thoại, mail địa chỉ email, STK số tài khoản, CCCD số CCCD"
    assert replace_masks(text) == (want, 6)


def test_c_no_label_unchanged_zero() -> None:
    assert replace_masks("VPN không vào được, báo lỗi 809") == ("VPN không vào được, báo lỗi 809", 0)


@pytest.mark.parametrize("fake", [
    "<SĐT_>", "<SDT_1>", "[BI_MAT_DA_AN]", "<EMAIL_x>",  # PLAN 3.3 C
    "<sđt_1>", "<SĐT_1", "SĐT_1>", "<SĐT 1>", "[BÍ_MẬT]", "<PHONE_1>", "<html>",
])  # fmt: skip
def test_c_lookalike_kept(fake: str) -> None:
    text = f"chuỗi {fake} ở giữa"
    assert replace_masks(text) == (text, 0)


@pytest.mark.parametrize("text", [
    "gọi <SĐT_1> nhé, mật khẩu [BÍ_MẬT_ĐÃ_ẨN]",
    "Tài khoản <STK_1> của chị Đặng",
])  # fmt: skip
def test_c_nfd_input_still_matches(text: str) -> None:
    """ĐT 4.3: chuẩn hoá NFC trước khi so khớp — đầu vào NFD (Đ/Ậ/Ẩ tách dấu) vẫn khớp, đầu ra là NFC."""
    nfd = unicodedata.normalize("NFD", text)
    assert nfd != text
    out, n = replace_masks(nfd)
    want, want_n = replace_masks(text)
    assert (out, n) == (want, want_n) and want_n >= 1
    assert unicodedata.is_normalized("NFC", out)


@pytest.mark.parametrize("text", [
    "mật khẩu [BÍ_MẬT_ĐÃ_ẨN], gọi <SĐT_1> hoặc <EMAIL_1>",
    "không có nhãn nào",
    "<SDT_1> và <SĐT_2>",
])  # fmt: skip
def test_c_twice_same_as_once(text: str) -> None:
    once, _ = replace_masks(text)
    twice, n2 = replace_masks(once)
    assert twice == once and n2 == 0  # từ thay không chứa nhãn


# ---- C: regex dựng từ config (không chép tay) ---------------------------------------------------------------------------


def test_c_secret_mask_from_config(tmp_path: Path) -> None:
    p = _patterns_with(tmp_path, secret_mask="[AN_DI]")
    rx = mask_regex(p)
    assert rx.fullmatch("[AN_DI]") and not rx.search("[BÍ_MẬT_ĐÃ_ẨN]")
    assert replace_masks("mật khẩu [AN_DI] nhé", p) == ("mật khẩu *** nhé", 1)
    assert replace_masks("mật khẩu [BÍ_MẬT_ĐÃ_ẨN] nhé", p) == ("mật khẩu [BÍ_MẬT_ĐÃ_ẨN] nhé", 0)
    assert replace_masks("gọi <SĐT_1>", p) == ("gọi số điện thoại", 1)  # nhãn pii vẫn lấy từ config tạm


def test_c_unknown_pii_label_refused(tmp_path: Path) -> None:
    """Label pii trong config không có trong `MASK_WORDS` → `PatternFileError` (PLAN mục 8)."""
    p = _patterns_with(tmp_path, relabel=("bank_account", "TKNH"))
    with pytest.raises(PatternFileError):
        mask_regex(p)
    with pytest.raises(PatternFileError):
        replace_masks("chuyển vào <TKNH_1>", p)


def test_c_default_patterns_equal_repo_config() -> None:
    """`patterns=None` → `privacy_patterns(get_settings().config_dir)` = config của repo khi test."""
    text = "mail <EMAIL_1>, mật khẩu [BÍ_MẬT_ĐÃ_ẨN]"
    assert replace_masks(text) == replace_masks(text, load_privacy_patterns(PRIVACY)) == ("mail địa chỉ email, mật khẩu ***", 2)
