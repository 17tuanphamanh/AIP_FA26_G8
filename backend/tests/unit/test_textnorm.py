"""b20 — `core/textnorm` (PLAN-3b mục 4.1)."""

import unicodedata

from app.core.textnorm import fold_diacritics, normalize


def test_nfc_composes_decomposed_text() -> None:
    decomposed = unicodedata.normalize("NFD", "mật khẩu")
    assert decomposed != "mật khẩu"
    assert normalize(decomposed) == "mật khẩu"


def test_invisible_characters_removed_and_nbsp_is_space() -> None:
    assert normalize("lỗi\u200b 809\ufeff\u200d") == "lỗi 809"
    assert normalize("cổng\u00a0443") == "cổng 443"


def test_inline_whitespace_collapsed_and_trailing_removed() -> None:
    assert normalize("a  \t b  ") == "a b"


def test_indentation_kept() -> None:
    assert normalize("- mục\n    - mục  con   lồng") == "- mục\n    - mục con lồng"


def test_crlf_and_cr_become_lf() -> None:
    assert normalize("a\r\nb\rc") == "a\nb\nc"


def test_blank_lines_kept() -> None:
    assert normalize("a\n\n\n   \nb") == "a\n\n\n\nb"


def test_fold_diacritics() -> None:
    assert fold_diacritics("Đường mật khẩu") == "Duong mat khau"
    assert fold_diacritics(unicodedata.normalize("NFD", "lỗi kết nối")) == "loi ket noi"
