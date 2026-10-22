"""G11 — chỉ số trên dữ liệu dựng tay (số tính tay, 1e-12) + khoảng tin cậy bootstrap theo họ."""

import pytest
from app.eval.groundedness.scoring import answer_pairs, score
from app.eval.stats import BOOTSTRAP_N, LEVEL, SEED
from tests.unit.eval._g11 import claim, judged


def _fixture() -> list:  # type: ignore[type-arg]
    return [
        # A (họ F1): 4 ý — 2 supported, 1 partial, 1 unsupported; dẫn a, b, x (x không có trong chunks) → chính xác a, b = 2/3
        judged("F1-v1", (claim(1, "supported", "a"), claim(2, "supported", "a", "b"), claim(3, "partial", "b"),
                         claim(4, "unsupported")), ("a", "b", "x"), invalid=("x",)),
        # B (họ F1): 2 ý supported bởi c; dẫn c, d → 1/2
        judged("F1-v2", (claim(1, "supported", "c"), claim(2, "supported", "c")), ("c", "d")),
        # C (họ F2): không trích dẫn → 3 ý unsupported, 0 cặp
        judged("F2-v1", (claim(1, "unsupported"), claim(2, "unsupported"), claim(3, "unsupported")), (), flags=("no_citation",)),
        judged("F2-v2", (), (), status="cannot_answer"),
        judged("F2-v3", (), (), status="error", error="LLMSchemaError"),
        judged("F2-v4", (), (), status="no_claims"),
    ]


def test_counts_and_rates_hand_computed() -> None:
    s = score(_fixture(), n_boot=50)
    assert (s["n_answers"], s["n_judged"], s["n_cannot_answer"], s["n_no_claims"], s["n_errors"]) == (6, 3, 1, 1, 1)
    assert s["n_families"] == 2 == s["supported_rate_ci"]["n_families"]  # họ của các ca được chấm (F1, F2); ca lỗi/cannot_answer không tính
    assert (s["n_claims"], s["n_supported"], s["n_partial"], s["n_unsupported"]) == (9, 4, 1, 4)
    assert s["supported_rate"] == pytest.approx(4 / 9, abs=1e-12)
    assert s["partial_rate"] == pytest.approx(1 / 9, abs=1e-12)
    assert s["unsupported_rate"] == pytest.approx(4 / 9, abs=1e-12)
    assert s["supported_rate_macro"] == pytest.approx((2 / 4 + 2 / 2 + 0 / 3) / 3, abs=1e-12)
    assert s["n_no_citation"] == 1


def test_citation_precision_hand_computed() -> None:
    s = score(_fixture(), n_boot=50)
    assert (s["n_citation_pairs"], s["n_citation_pairs_precise"], s["n_invalid_citation_pairs"]) == (5, 3, 1)
    assert s["citation_precision"] == pytest.approx(3 / 5, abs=1e-12)


def test_partial_only_chunk_is_not_precise_and_partial_is_not_supported() -> None:
    a = judged("P-v1", (claim(1, "partial", "e"),), ("e",))
    assert answer_pairs(a) == (0, 1)
    s = score([a], n_boot=10)
    assert s["supported_rate"] == 0.0 and s["partial_rate"] == 1.0 and s["citation_precision"] == 0.0


def test_citation_not_in_chunks_counts_against_precision() -> None:
    a = judged("I-v1", (claim(1, "supported", "k"),), ("k", "ghost"), invalid=("ghost",))
    assert answer_pairs(a) == (1, 2)


def test_answers_without_pairs_leave_precision_undefined_not_zero() -> None:
    s = score([judged("N-v1", (claim(1, "unsupported"),), (), flags=("no_citation",))], n_boot=10)
    assert s["citation_precision"] is None and s["supported_rate"] == 0.0
    assert s["citation_precision_ci"]["lo"] is None


def test_empty_input_does_not_crash_and_rates_are_none() -> None:
    s = score([], n_boot=10)
    assert s["n_answers"] == 0 and s["supported_rate"] is None and s["supported_rate_macro"] is None
    assert s["supported_rate_ci"]["lo"] is None and s["supported_rate_ci"]["n_families"] == 0


def test_errors_and_cannot_answer_never_enter_the_denominator() -> None:
    base = score(_fixture()[:3], n_boot=10)
    full = score(_fixture(), n_boot=10)
    for key in ("n_claims", "supported_rate", "citation_precision", "supported_rate_macro"):
        assert full[key] == base[key], key


def test_ci_is_deterministic_defaults_follow_p8_and_resamples_families_not_claims() -> None:
    s1, s2 = score(_fixture(), n_boot=200), score(_fixture(), n_boot=200)
    assert s1 == s2
    ci = s1["supported_rate_ci"]
    assert (ci["seed"], ci["level"], ci["n_families"]) == (SEED, LEVEL, 2) and BOOTSTRAP_N == 2000
    assert ci["lo"] is not None and ci["hi"] is not None and 0.0 <= ci["lo"] <= ci["hi"] <= 1.0
    assert score(_fixture(), n_boot=7)["supported_rate_ci"]["n_boot"] == 7


def test_single_family_bootstrap_has_zero_width() -> None:
    """Một họ → mọi lần rút lại chính họ đó → khoảng suy biến về giá trị điểm. Rút theo ca/ý thì khoảng sẽ rộng (ca khác nhau)."""
    good = (claim(1, "supported", "a"), claim(2, "supported", "a"))
    bad = (claim(1, "unsupported"), claim(2, "unsupported"))
    one = [judged(f"ONE-v{i}", good if i % 2 else bad, ("a",)) for i in range(6)]
    s = score(one, n_boot=300)
    ci = s["supported_rate_ci"]
    assert s["supported_rate"] == 0.5 and ci["lo"] == ci["hi"] == 0.5 and ci["n_used"] == 300 and ci["n_families"] == 1
    assert s["citation_precision_ci"]["lo"] == s["citation_precision_ci"]["hi"] == s["citation_precision"] == 0.5


def test_precision_ci_undefined_draws_are_counted_not_zeroed() -> None:
    mixed = [
        judged("A-v1", (claim(1, "supported", "a"),), ("a",)),
        judged("B-v1", (claim(1, "unsupported"),), (), flags=("no_citation",)),  # họ B không có cặp nào
    ]
    ci = score(mixed, n_boot=400)["citation_precision_ci"]
    assert ci["n_undefined"] > 0 and ci["n_used"] + ci["n_undefined"] == 400  # rút ra toàn họ B → mẫu số 0
