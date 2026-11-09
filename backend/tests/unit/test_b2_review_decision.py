"""Gói 1 (D-52) — hàm quyết định B2 `app.guard.b2_review` (hàm thuần, không graph, không settings).

Viết TỪ ĐẶC TẢ, trước code: `PLAN-B2REVIEW.md` mục 3.2 (chữ ký `ClfMode`, `Verdict`, `classifier_shortcut`, `after_judge`),
bảng 3.3 A (a1–a12), mục 8; `docs/spec/claude/dac-ta-bat-2-model.md` mục 4.1, 4.2 (dòng #2–#7, biên p = τ rơi vào #4,
#3 áp mọi chế độ, `shadow`/`active` giữ hành vi cũ trừ #3). Ngưỡng `active` (0,90 / 0,10) = `guard/injection.py:19-20`.
"""

import dataclasses
import typing

import pytest
from app.guard import b2_review as b2r
from app.guard.b2_review import Verdict, after_judge, classifier_shortcut

E0_LLM = Verdict(outcome="E0", layer="llm")
E1_CLF = Verdict(outcome="E1", layer="classifier")
PASS_LLM = Verdict(outcome="pass", layer="llm")
ML_ERRORS_INFRA = ("model_missing", "timeout", "connect", "http_5xx", "classify_failed")  # dòng #7


def test_verdict_is_frozen_dataclass() -> None:
    v = Verdict(outcome="E0", layer="llm")
    assert dataclasses.is_dataclass(v)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.outcome = "pass"  # type: ignore[misc]


def test_clf_mode_has_three_values() -> None:
    alias = getattr(b2r.ClfMode, "__value__", b2r.ClfMode)  # `type ClfMode = Literal[...]` hoặc alias thường
    assert set(typing.get_args(alias)) == {"shadow", "active", "review"}


# ---- after_judge (a1–a10) --------------------------------------------------------------------------------------------


def test_a1_review_llm_attack_e0_llm() -> None:
    assert after_judge("review", p_mal=0.30, ml_error=None, is_attack=True, category="override", tau=0.8) == E0_LLM


def test_a2_review_category_not_none_e0_llm_row3() -> None:
    """#3: `is_attack=false` nhưng `category ≠ none` → E0 ở L4 (KHÔNG phải E1 dù p cao)."""
    assert after_judge("review", p_mal=0.95, ml_error=None, is_attack=False, category="other", tau=0.8) == E0_LLM


def test_a3_review_p_equal_tau_is_e1_classifier() -> None:
    """Biên: p = τ rơi vào #4 (≥, không phải >) — mutation 1."""
    assert after_judge("review", p_mal=0.80, ml_error=None, is_attack=False, category="none", tau=0.8) == E1_CLF


def test_a4_review_just_below_tau_passes_llm() -> None:
    assert after_judge("review", p_mal=0.7999, ml_error=None, is_attack=False, category="none", tau=0.8) == PASS_LLM


def test_a4b_review_high_p_e1() -> None:
    """#4 điển hình (p = 0,95 > τ)."""
    assert after_judge("review", p_mal=0.95, ml_error=None, is_attack=False, category="none", tau=0.8) == E1_CLF


def test_a5_review_too_many_windows_e1_classifier() -> None:
    """#5: 422 `too_many_windows` (không có p) + LLM nói không → E1 `injection_suspected`."""
    got = after_judge("review", p_mal=None, ml_error="too_many_windows", is_attack=False, category="none", tau=0.8)
    assert got == E1_CLF


@pytest.mark.parametrize("ml_error", ML_ERRORS_INFRA)
def test_a6_review_infra_error_passes_llm(ml_error: str) -> None:
    """#7: lỗi hạ tầng không phải tín hiệu tấn công → qua B3, `layer_decided=llm`."""
    assert after_judge("review", p_mal=None, ml_error=ml_error, is_attack=False, category="none", tau=0.8) == PASS_LLM


def test_a7_shadow_high_p_still_passes() -> None:
    assert after_judge("shadow", p_mal=0.99, ml_error=None, is_attack=False, category="none", tau=None) == PASS_LLM


@pytest.mark.parametrize("mode", ["shadow", "active"])
@pytest.mark.parametrize("p_mal", [0.05, 0.5, 0.99, None])
def test_a8_row3_every_mode(mode: str, p_mal: float | None) -> None:
    """#3 áp cho MỌI chế độ (ĐT 4.2) — mutation 6."""
    got = after_judge(mode, p_mal=p_mal, ml_error=None, is_attack=False, category="prompt_leak", tau=None)  # type: ignore[arg-type]
    assert got == E0_LLM


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_a8b_llm_attack_every_mode(mode: str) -> None:
    got = after_judge(mode, p_mal=0.5, ml_error=None, is_attack=True, category="other", tau=None)  # type: ignore[arg-type]
    assert got == E0_LLM


@pytest.mark.parametrize("mode", ["shadow", "active"])
def test_a9_too_many_windows_old_modes_pass(mode: str) -> None:
    """`shadow`/`active`: 422 vẫn xuống L4 rồi qua như cũ (T23a) — #5 chỉ ở `review`."""
    got = after_judge(mode, p_mal=None, ml_error="too_many_windows", is_attack=False, category="none", tau=None)  # type: ignore[arg-type]
    assert got == PASS_LLM


@pytest.mark.parametrize("mode", ["shadow", "active"])
@pytest.mark.parametrize("ml_error", ML_ERRORS_INFRA)
def test_a9b_infra_error_old_modes_pass(mode: str, ml_error: str) -> None:
    got = after_judge(mode, p_mal=None, ml_error=ml_error, is_attack=False, category="none", tau=None)  # type: ignore[arg-type]
    assert got == PASS_LLM


def test_a9c_active_middle_band_llm_says_no_passes() -> None:
    assert after_judge("active", p_mal=0.5, ml_error=None, is_attack=False, category="none", tau=None) == PASS_LLM


def test_a10_review_without_tau_value_error() -> None:
    """`review` mà `tau is None` → ValueError (Settings đã chặn — PLAN 3.2)."""
    with pytest.raises(ValueError):
        after_judge("review", p_mal=0.95, ml_error=None, is_attack=False, category="none", tau=None)


# ---- classifier_shortcut (a11, a12) ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("p_mal", "want"), [
    (0.90, Verdict(outcome="E0", layer="classifier")),  # = TAU_BLOCK → chặn
    (0.95, Verdict(outcome="E0", layer="classifier")),
    (0.10, Verdict(outcome="pass", layer="classifier")),  # = TAU_PASS → qua
    (0.05, Verdict(outcome="pass", layer="classifier")),
    (0.5, None), (0.11, None), (0.89, None),
    (None, None),  # lỗi L3 → không quyết thẳng
])  # fmt: skip
def test_a11_active_shortcut(p_mal: float | None, want: Verdict | None) -> None:
    assert classifier_shortcut("active", p_mal) == want


@pytest.mark.parametrize("mode", ["shadow", "review"])
@pytest.mark.parametrize("p_mal", [0.99, 0.95, 0.90, 0.10, 0.01, None])
def test_a12_shadow_review_never_shortcut(mode: str, p_mal: float | None) -> None:
    """`review` không bao giờ quyết thẳng bằng model (ĐT 4.1: mọi câu không khớp regex đều qua L4) — mutation 2."""
    assert classifier_shortcut(mode, p_mal) is None  # type: ignore[arg-type]
