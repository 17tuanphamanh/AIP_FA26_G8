"""G9 — đồng thuận người gán nhãn (`app.eval.stats`: `cohen_kappa`, `weighted_kappa_linear`, `pabak`, `agreement`).

Đáp số tính tay bằng phân số (plan G9, bảng ví dụ). Ma trận hàng = A, cột = B, thứ tự AUTO / HITL / ESCALATE_L2.
"""

from fractions import Fraction as F

import pytest
from app.eval.stats import (
    KAPPA_LABELS,
    KAPPA_PASS,
    Agreement,
    agreement,
    cohen_kappa,
    pabak,
    weighted_kappa_linear,
)

A, H, L = KAPPA_LABELS


def from_matrix(m: list[list[int]]) -> tuple[list[str], list[str]]:
    a: list[str] = []
    b: list[str] = []
    for i, row in enumerate(m):
        for j, count in enumerate(row):
            a += [KAPPA_LABELS[i]] * count
            b += [KAPPA_LABELS[j]] * count
    return a, b


# (a, b, po, pe, κ, κ_w, po_w, pe_w, PABAK, kết luận)
CASES = {
    "E1": ([A, H, L, H], [A, H, L, H], F(1), F(3, 8), F(1), F(1), F(1), None, F(1), "DAT"),
    "E2": ([H, H, H], [H, H, H], F(1), F(1), None, None, F(1), F(1), F(1), "khong_xac_dinh"),
    "E3": ([A, H], [H, A], F(0), F(1, 2), F(-1), F(-1), F(1, 2), F(3, 4), F(-1, 2), "KHONG_DAT"),
    "E4": (*from_matrix([[3, 1, 0], [1, 2, 1], [0, 1, 1]]), F(3, 5), F(9, 25), F(3, 8), F(1, 2), F(4, 5), F(3, 5), F(2, 5),
           "KHONG_DAT"),
    "E5": (*from_matrix([[2, 2, 0], [0, 3, 1], [0, 0, 2]]), F(7, 10), F(17, 50), F(6, 11), F(26, 41), F(17, 20), F(59, 100),
           F(11, 20), "KHONG_DAT"),
    "E6": (*from_matrix([[4, 1, 0], [1, 4, 0], [0, 0, 0]]), F(4, 5), F(1, 2), F(3, 5), F(3, 5), F(9, 10), F(3, 4), F(7, 10), "DAT"),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(CASES))
def test_kappa_hand(case: str) -> None:
    a, b, po, pe, kappa, kappa_w, po_w, pe_w, pab, verdict = CASES[case]
    r = agreement(a, b)
    assert isinstance(r, Agreement)
    assert (r.n, r.po, r.pe) == (len(a), po, pe)
    assert r.kappa.exact == kappa
    assert r.kappa.value == (None if kappa is None else float(kappa))
    assert r.kappa.reason == (None if kappa is not None else "pe_bang_1")
    assert r.kappa_w.exact == kappa_w
    assert r.kappa_w.value == (None if kappa_w is None else float(kappa_w))
    assert r.kappa_w.reason == (None if kappa_w is not None else "mau_so_trong_so_bang_0")
    assert r.kappa_w.po == po_w
    if pe_w is not None:
        assert r.kappa_w.pe == pe_w
    assert r.pabak == pab
    assert r.verdict == verdict
    assert cohen_kappa(a, b) == r.kappa and weighted_kappa_linear(a, b) == r.kappa_w and pabak(a, b) == pab


@pytest.mark.parametrize("case", sorted(CASES))
def test_kappa_symmetric(case: str) -> None:
    a, b, *_ = CASES[case]
    assert agreement(b, a) == agreement(a, b)


def test_kappa_pe_one_null() -> None:
    for label in KAPPA_LABELS:
        r = agreement([label] * 5, [label] * 5)
        assert r.kappa.exact is None and r.kappa.value is None and r.kappa.reason == "pe_bang_1"
        assert r.kappa_w.exact is None and r.kappa_w.reason == "mau_so_trong_so_bang_0"
        assert r.pabak == 1


def test_verdict_boundary_06() -> None:
    a, b, *_ = CASES["E6"]
    r = agreement(a, b)
    assert r.kappa.exact == KAPPA_PASS == F(3, 5)
    assert r.verdict == "DAT"


def test_verdict_undefined() -> None:
    assert agreement([L, L], [L, L]).verdict == "khong_xac_dinh"


def test_kappa_empty() -> None:
    for fn in (cohen_kappa, weighted_kappa_linear, pabak, agreement):
        with pytest.raises(ValueError, match="n = 0"):
            fn([], [])


def test_kappa_len_mismatch() -> None:
    with pytest.raises(ValueError, match="độ dài khác nhau"):
        agreement([A, H], [A])


@pytest.mark.parametrize("bad", ["", "auto", "ESCALATE", "SENTINEL_NHAN"])
def test_kappa_bad_label(bad: str) -> None:
    with pytest.raises(ValueError, match="nhãn ngoài tập") as e:
        agreement([A, bad], [A, H])
    assert "SENTINEL" not in str(e.value)
