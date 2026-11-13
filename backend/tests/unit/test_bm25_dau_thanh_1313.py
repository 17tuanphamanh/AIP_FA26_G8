"""R3 (soát 12/11 agent 16 F5): BM25 gộp hai kiểu đặt dấu thanh — "khóa"/"khoá", "hòa"/"hoà", "thủy"/"thuỷ", "khỏe"/"khoẻ" — vì KB trộn
cả hai kiểu (`khóa` 30 / `khoá` 1, `hoà` 16 / `hòa` 1) còn người dùng gõ kiểu nào cũng có.

Chuẩn về kiểu cũ (dấu trên nguyên âm đầu) CHỈ ở âm tiết mở (cụm oa/oe/uy cuối âm tiết): "hoàn", "khoản", "toán", "quý" không đổi.
Ingest và truy vấn dùng chung `tokenize_vi` → `pipeline_sha` có khoá `tokenizer` (đổi phiên bản → collection mới, ingest lại).
"""

from pathlib import Path

import pytest
from app.rag.bm25 import TOKENIZER_VERSION, fold_tone_marks, tokenize_vi
from app.rag.ingest.kbversion import pipeline_sha

CONFIG = Path(__file__).resolve().parents[3] / "config"


@pytest.mark.parametrize(("new", "old"), [
    ("khoá", "khóa"), ("hoà", "hòa"), ("toà", "tòa"), ("hoá", "hóa"), ("xoá", "xóa"), ("loà", "lòa"), ("hoả", "hỏa"),
    ("khoẻ", "khỏe"), ("loè", "lòe"), ("thuỷ", "thủy"), ("huỷ", "hủy"), ("luỹ", "lũy"),
])  # fmt: skip
def test_hai_kieu_ra_cung_mot(new: str, old: str) -> None:
    assert fold_tone_marks(new) == fold_tone_marks(old) == old


@pytest.mark.parametrize("word", ["hoàn", "khoản", "toán", "hoàng", "quý", "quỳ", "khoan", "huyền", "thuyết", "mới", "đã"])
def test_am_tiet_dong_va_qu_khong_doi(word: str) -> None:
    assert fold_tone_marks(word) == word


def test_tach_tu_gop_hai_kieu() -> None:
    assert tokenize_vi("tài khoản bị khoá") == tokenize_vi("tài khoản bị khóa")
    assert tokenize_vi("xoá phần mềm") == tokenize_vi("xóa phần mềm")


def test_pipeline_sha_co_phien_ban_tach_tu(monkeypatch: pytest.MonkeyPatch) -> None:
    before = pipeline_sha(CONFIG)
    monkeypatch.setattr("app.rag.ingest.kbversion.TOKENIZER_VERSION", TOKENIZER_VERSION + 1)
    assert pipeline_sha(CONFIG) != before
