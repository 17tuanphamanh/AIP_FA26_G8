"""b8, b9 — BM25 tiếng Việt (thiết kế Phase 3 mục 5.6; PLAN-3b mục 4.5, Q-3b-9)."""

import pytest
from app.rag import bm25
from app.rag.bm25 import to_sparse, tokenize_vi


@pytest.mark.parametrize(("text", "check"), [
    ("mật khẩu", lambda t: t == ["mật_khẩu"]),
    ("lỗi 809", lambda t: "809" in t),
    ("0x8004010F", lambda t: t == ["0x8004010f"]),
    ("mk", lambda t: t == ["mật_khẩu"]),
    ("LAP-0342", lambda t: t == ["lap-0342"]),
    ("vpn không kết nối được", lambda t: "không" in t),
    ("pm-0123", lambda t: t == ["pm-0123"]),
    ("máy LAP-0342 báo lỗi 809, cài pm ko dc", lambda t: t == [
        "máy", "lap-0342", "báo", "lỗi", "809", "cài", "phần_mềm", "không"]),
], ids=["mat-khau", "loi-809", "hex", "viet-tat", "ma-may", "negation", "ma-truoc-viet-tat", "cau-tron"])  # fmt: skip
def test_b8_tokenize_vi(text: str, check: object) -> None:
    toks = tokenize_vi(text)
    assert check(toks), toks  # type: ignore[operator]


def test_b8_stopwords_and_punctuation_dropped() -> None:
    assert tokenize_vi("Giúp mình với, VPN bị lỗi ạ!") == ["vpn", "lỗi"]


def test_b9_to_sparse_merges_collisions(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = {"a": 7, "b": 7, "c": 3}
    monkeypatch.setattr(bm25, "_token_hash", lambda tok: fake[tok])
    sv = to_sparse(["a", "b", "c"])
    assert sv.indices == [3, 7]
    assert sv.values == [1.0, 2.0]
    assert len(set(sv.indices)) == len(sv.indices) and sv.indices == sorted(sv.indices)


def test_to_sparse_real_hash_counts_frequency() -> None:
    sv = to_sparse(["vpn", "vpn", "809"])
    assert sorted(sv.values) == [1.0, 2.0]
    assert all(0 <= i < 2**31 for i in sv.indices)
    assert to_sparse(["vpn"]).indices == to_sparse(["vpn"]).indices  # tất định giữa các lần gọi
