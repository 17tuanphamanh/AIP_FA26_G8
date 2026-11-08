"""M5 — `scripts/eval/token_estimate_check.py`: tỉ số token THẬT (nhà cung cấp báo) / ƯỚC LƯỢNG (`ceil(ký tự/3)` của gateway) theo `prompt_id`.

Chỉ đọc (SELECT, phiên `default_transaction_read_only=on`), không đổi runtime, không đọc `.env`/Settings, không in DSN. Test dùng DỮ LIỆU TỔNG HỢP
và bộ đọc giả — không kết nối DB nào, không chạy trên máy đo.

Điều gì được tính là 'thật' (đọc `llm/client.py` `_account`): `llm_calls.tokens_in` cộng dồn MỌI lần thử và rơi về chính ước lượng khi nhà cung cấp
không báo usage → chỉ lấy dòng sạch: một lần thử, không fallback, không cache, không lỗi, có `usage_tokens_in`, và `tokens_in == usage_tokens_in`.
Ước lượng: dựng lại từ `prompt_full` (chỉ có khi EVAL_MODE) bằng CHÍNH `app.llm.context.estimate_tokens` trên từng message; không có thì lấy
`est_tokens_in` của span.
"""

import json
import re
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from app.llm import context as llm_context
from tests.unit._b2review import load_script

SCRIPT = "scripts/eval/token_estimate_check.py"


@pytest.fixture
def m(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load_script(SCRIPT, monkeypatch)


def row(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "prompt_id": "b03_classify", "prompt_version": "5", "tokens_in": 120, "usage_tokens_in": 120, "est_tokens_in": 100,
        "attempts": 1, "used_fallback": False, "cache_hit": False, "error": None, "prompt_full": None,
    }  # fmt: skip
    return {**base, **over}


def rows_for(pid: str, pairs: Sequence[tuple[int, int]]) -> list[dict[str, Any]]:
    return [row(prompt_id=pid, tokens_in=t, usage_tokens_in=t, est_tokens_in=e) for t, e in pairs]


# ---- thống kê ------------------------------------------------------------------------------------------------------------------


def test_percentile_is_linear_interpolation(m: ModuleType) -> None:
    assert m.percentile([1.0], 0.95) == 1.0
    assert m.percentile([0.9, 1.1], 0.95) == pytest.approx(1.09)
    assert m.percentile([1.0, 1.2, 1.4, 1.6, 2.0], 0.95) == pytest.approx(1.92)
    assert m.percentile([1.0, 1.2, 1.4, 1.6, 2.0], 0.5) == pytest.approx(1.4)
    with pytest.raises(ValueError):
        m.percentile([], 0.5)


def test_summary_per_prompt_by_hand(m: ModuleType) -> None:
    data = rows_for("b03_classify", [(100, 100), (120, 100), (140, 100), (160, 100), (200, 100)])
    data += rows_for("b10_answer", [(90, 100), (110, 100)])
    rep = m.summarize(data)
    a, b = rep.groups["b03_classify"], rep.groups["b10_answer"]
    assert (a.n, a.median, round(a.p95, 6)) == (5, pytest.approx(1.4), pytest.approx(1.92))
    assert (b.n, b.median, round(b.p95, 6)) == (2, pytest.approx(1.0), pytest.approx(1.09))
    assert rep.excluded == {}


def test_ratio_is_real_over_estimate_not_the_reverse(m: ModuleType) -> None:
    [only] = m.summarize([row(tokens_in=150, usage_tokens_in=150, est_tokens_in=100)]).groups.values()
    assert only.median == pytest.approx(1.5)  # > 1: ước lượng ĐẾM THIẾU token thật


# ---- ước lượng: prompt_full dựng lại bằng đúng hàm của runtime --------------------------------------------------------------------


def test_script_uses_the_runtime_estimator_not_a_copy(m: ModuleType) -> None:
    assert m.estimate_tokens is llm_context.estimate_tokens


def test_estimate_from_prompt_full_sums_ceil_chars_over_three_per_message(m: ModuleType) -> None:
    messages = [{"role": "system", "content": "a" * 10}, {"role": "user", "content": "b" * 7}]  # ceil(10/3)=4, ceil(7/3)=3
    full = json.dumps(messages, ensure_ascii=False)
    assert m.estimate_from_messages(full) == 7  # KHÔNG phải ceil(len(JSON)/3) — JSON dài hơn nội dung
    [g] = m.summarize([row(prompt_full=full, tokens_in=14, usage_tokens_in=14, est_tokens_in=7)]).groups.values()
    assert g.median == pytest.approx(2.0) and g.est_from_prompt_full == 1 and g.est_from_span == 0


def test_estimate_falls_back_to_span_attribute_without_prompt_full(m: ModuleType) -> None:
    [g] = m.summarize([row()]).groups.values()
    assert (g.est_from_prompt_full, g.est_from_span) == (0, 1)


def test_prompt_full_wins_over_span_and_mismatch_is_counted(m: ModuleType) -> None:
    full = json.dumps([{"role": "user", "content": "x" * 30}])  # ước lượng 10
    rep = m.summarize([row(prompt_full=full, tokens_in=20, usage_tokens_in=20, est_tokens_in=99)])
    [g] = rep.groups.values()
    assert g.median == pytest.approx(2.0)  # 20 / 10, không phải 20 / 99
    assert rep.est_mismatch == 1


def test_bad_prompt_full_json_is_excluded_not_crash(m: ModuleType) -> None:
    rep = m.summarize([row(prompt_full="không phải JSON")])
    assert rep.groups == {} and rep.excluded == {"bad_prompt_full": 1}


# ---- loại dòng không sạch ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("over", "reason"), [
    ({"cache_hit": True}, "cache_hit"),
    ({"error": "LLMUnavailable"}, "error"),
    ({"used_fallback": True}, "fallback"),
    ({"attempts": 2}, "retry"),
    ({"usage_tokens_in": None}, "no_usage"),  # nhà cung cấp không báo → tokens_in CHÍNH LÀ ước lượng, tỉ số giả 1,0
    ({"tokens_in": 999}, "usage_mismatch"),
    ({"tokens_in": None}, "no_tokens"),
    ({"est_tokens_in": 0}, "no_estimate"),
    ({"est_tokens_in": None}, "no_estimate"),
])  # fmt: skip
def test_unclean_rows_are_excluded_with_reason(m: ModuleType, over: dict[str, Any], reason: str) -> None:
    rep = m.summarize([row(), row(**over)])
    [g] = rep.groups.values()
    assert g.n == 1 and rep.excluded == {reason: 1}


def test_exclusions_never_reach_the_ratio(m: ModuleType) -> None:
    clean = rows_for("p", [(100, 100)])
    dirty = [row(prompt_id="p", usage_tokens_in=None, tokens_in=100, est_tokens_in=100), row(prompt_id="p", attempts=3)]
    assert m.summarize(clean + dirty).groups["p"].median == pytest.approx(1.0) and m.summarize(clean + dirty).groups["p"].n == 1


# ---- chỉ đọc ------------------------------------------------------------------------------------------------------------------------


def test_query_is_a_single_select(m: ModuleType) -> None:
    sql = m.QUERY.strip()
    assert sql.upper().startswith("SELECT") and ";" not in sql
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|GRANT|COPY|CALL|DO)\b", sql, re.IGNORECASE)
    assert "llm_calls" in sql and "spans" in sql


def test_engine_is_read_only_session(m: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def spy(url: str, **kw: Any) -> object:
        seen.update(url=url, **kw)
        return object()

    monkeypatch.setattr(m, "create_engine", spy)
    m.make_engine("postgresql+psycopg://u:p@h/d")
    assert seen["connect_args"] == {"options": "-c default_transaction_read_only=on"}


def test_script_does_not_touch_env_or_settings(m: ModuleType) -> None:
    assert m.__file__ is not None
    src = Path(m.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\bSettings\b|get_settings|load_dotenv|\.env\b|os\.environ|getenv", src.replace(".env.example", ""))


# ---- CLI ----------------------------------------------------------------------------------------------------------------------------


def test_main_prints_table_legend_and_flags_small_groups(m: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    data = rows_for("b03_classify", [(100, 100), (120, 100), (140, 100), (160, 100), (200, 100)])
    data += rows_for("b10_answer", [(90, 100), (110, 100)]) + [row(prompt_id="b10_answer", cache_hit=True)]
    code = m.main(["--dsn", "postgresql+psycopg://u:secret-pw@h/d", "--min-n", "3"], fetch=lambda dsn, since: data)
    out = capsys.readouterr().out
    assert code == 0 and "secret-pw" not in out
    lines = [ln for ln in out.splitlines() if ln.startswith(("b03_classify", "b10_answer"))]
    assert [ln.split()[0] for ln in lines] == ["b03_classify", "b10_answer"]  # sắp theo prompt_id
    assert "1.400" in lines[0] and "1.920" in lines[0] and "(n<3)" not in lines[0]
    assert "1.000" in lines[1] and "1.090" in lines[1] and "(n<3)" in lines[1]
    assert "cache_hit" in out and "thật / ước lượng" in out and "ĐẾM THIẾU" in out


def test_main_requires_a_dsn_and_never_echoes_it(m: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert m.main([], fetch=lambda dsn, since: []) == 2
    assert "--dsn" in capsys.readouterr().err

    def boom(dsn: str, since: object) -> list[dict[str, Any]]:
        raise RuntimeError(f"không nối được {dsn}")

    assert m.main(["--dsn", "postgresql+psycopg://u:secret-pw@h/d"], fetch=boom) == 2
    err = capsys.readouterr().err
    assert "RuntimeError" in err and "secret-pw" not in err


def test_main_since_is_parsed_and_passed_on(m: ModuleType) -> None:
    got: list[Any] = []

    def fetch(dsn: str, since: Any) -> list[dict[str, Any]]:
        got.append(since)
        return []

    m.main(["--dsn", "x", "--since", "2026-11-01"], fetch=fetch)
    assert str(got[0].date()) == "2026-11-01" and got[0].tzinfo is not None
    assert m.main(["--dsn", "x", "--since", "hôm qua"], fetch=lambda dsn, since: []) == 2


def test_main_no_clean_rows_exits_1_with_reasons(m: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    assert m.main(["--dsn", "x"], fetch=lambda dsn, since: [row(cache_hit=True), row(attempts=2)]) == 1
    out = capsys.readouterr()
    assert "không có dòng sạch" in out.err and "cache_hit" in out.err and "retry" in out.err
