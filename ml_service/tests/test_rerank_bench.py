"""`rerank_bench` — phần THUẦN, không torch (Q-3a-16, PLAN-3c mục 6.1 điểm 5): parse tham số, tách mục theo
`##`, cắt đoạn đo theo token (tokenizer giả), báo cáo p50/p95, độ lệch int8. KHÔNG test tốc độ thật (đó là việc
của `measure_speed`, gọi `time.perf_counter` — không unit test)."""

from pathlib import Path

import pytest
from app.rerank_bench import (
    Int8Report,
    _parser,
    int8_deviation,
    load_passages,
    load_queries,
    make_pairs,
    measurement_passage,
    parse_ints,
    percentiles,
)
from tests.conftest import FakeTokenizer


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ---- parse_ints -------------------------------------------------------------------------------


def test_parse_ints_splits_on_comma() -> None:
    assert parse_ints("10,20") == [10, 20]
    assert parse_ints("3") == [3]
    assert parse_ints("3, 4 ,5") == [3, 4, 5]


# ---- load_queries / load_passages --------------------------------------------------------------


def test_load_queries_reads_retrieval_set(tmp_path: Path) -> None:
    _write(tmp_path / "eval" / "retrieval_set.yaml", "items:\n  - query: cau mot\n  - query: cau hai\n")
    assert load_queries(tmp_path) == ["cau mot", "cau hai"]


def test_load_passages_splits_by_h2_and_skips_disabled(tmp_path: Path) -> None:
    _write(
        tmp_path / "vpn" / "KB-VPN-001.md",
        "---\ndoc_id: KB-VPN-001\nenabled: true\n---\n"
        "## Muc mot\nNoi dung mot.\n\n## Muc hai\nNoi dung hai.\n",
    )
    _write(
        tmp_path / "vpn" / "KB-VPN-002.md",
        "---\ndoc_id: KB-VPN-002\nenabled: false\n---\n## Muc ba\nKhong duoc doc.\n",
    )
    passages = load_passages(tmp_path)
    assert passages == ["Muc mot\nNoi dung mot.", "Muc hai\nNoi dung hai."]


def test_load_passages_treats_missing_enabled_as_true(tmp_path: Path) -> None:
    """Front matter test tối giản không ghi `enabled` — không được coi là disabled."""
    _write(tmp_path / "vpn" / "KB-VPN-003.md", "---\ndoc_id: KB-VPN-003\n---\n## X\nY\n")
    assert load_passages(tmp_path) == ["X\nY"]


def test_load_passages_skips_files_without_front_matter(tmp_path: Path) -> None:
    _write(tmp_path / "vpn" / "README.md", "## Khong phai tai lieu KB\n")
    assert load_passages(tmp_path) == []


# ---- measurement_passage / make_pairs ------------------------------------------------------------


def test_measurement_passage_cuts_to_exact_token_length() -> None:
    tok = FakeTokenizer()
    joined_source = ["mot hai ba bon nam", "sau bay tam chin muoi"]
    passage = measurement_passage(tok, joined_source, length=4)
    ids = tok(passage, add_special_tokens=False)["input_ids"]
    assert len(ids) == 4
    assert passage == "mot hai ba bon"  # 4 từ đầu của chuỗi đã ghép


def test_measurement_passage_shorter_than_length_keeps_everything() -> None:
    tok = FakeTokenizer()
    passage = measurement_passage(tok, ["mot hai"], length=100)
    assert passage == "mot hai"


def test_make_pairs_cycles_queries_when_k_exceeds_count() -> None:
    pairs = make_pairs(["q1", "q2", "q3"], "P", k=7)
    assert pairs == [("q1", "P"), ("q2", "P"), ("q3", "P"), ("q1", "P"), ("q2", "P"), ("q3", "P"), ("q1", "P")]


# ---- percentiles (thuần — thay cho đo tốc độ thật) ------------------------------------------------


def test_percentiles_median_and_p95_by_hand() -> None:
    samples = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50, p95 = percentiles(samples)
    assert p50 == pytest.approx(55.0)  # median 10 mẫu 10..100
    assert p95 >= p50  # quantiles(n=20)[18] — không tay tính công thức nội suy, chỉ kiểm quan hệ thứ tự


def test_percentiles_single_sample_returns_it_twice() -> None:
    assert percentiles([42.0]) == (42.0, 42.0)


def test_percentiles_empty_rejected() -> None:
    with pytest.raises(ValueError, match="ít nhất 1 mẫu"):
        percentiles([])


# ---- int8_deviation (thuần, reranker giả) ---------------------------------------------------------


class _StubReranker:
    """Trả logit cố định theo bảng tay — không torch."""

    def __init__(self, table: dict[tuple[str, str], float]) -> None:
        self._table = table

    def logits(self, pairs: list[tuple[str, str]]) -> list[float]:
        return [self._table[p] for p in pairs]


def test_int8_deviation_computes_max_delta_top1_match_and_verdict_changes() -> None:
    # 2 câu, 2 đoạn. Câu 1: fp32 và int8 đồng ý top-1 (P1), lệch điểm nhỏ. Câu 2: bất đồng top-1 VÀ đổi phán
    # quyết ở 0,6 (fp32 max ứng sigmoid(0)=0,5 < 0,6; int8 max ứng sigmoid(1)=0,731 ≥ 0,6).
    fp32 = _StubReranker({("q1", "P1"): 2.0, ("q1", "P2"): 0.0, ("q2", "P1"): -1.0, ("q2", "P2"): 0.0})
    int8 = _StubReranker({("q1", "P1"): 1.9, ("q1", "P2"): 0.1, ("q2", "P1"): 1.0, ("q2", "P2"): -1.0})
    report = int8_deviation(fp32, int8, ["q1", "q2"], ["P1", "P2"], threshold=0.6)
    assert isinstance(report, Int8Report)
    assert report.top1_match_rate == pytest.approx(0.5)  # câu 1 trùng, câu 2 không
    assert report.verdict_changes == 1  # chỉ câu 2 đổi phán quyết ở 0,6
    assert report.max_abs_delta > 0.0


def test_int8_deviation_identical_rerankers_have_zero_delta() -> None:
    same = _StubReranker({("q", "P"): 1.5})
    report = int8_deviation(same, same, ["q"], ["P"])
    assert (report.max_abs_delta, report.top1_match_rate, report.verdict_changes) == (0.0, 1.0, 0)


def test_int8_deviation_rejects_empty_passages() -> None:
    stub = _StubReranker({})
    with pytest.raises(ValueError, match="ít nhất 1 đoạn văn"):
        int8_deviation(stub, stub, ["q"], [])


# ---- CLI parser ---------------------------------------------------------------------------------


def test_cli_parser_defaults_and_required_kb() -> None:
    with pytest.raises(SystemExit):
        _parser().parse_args([])  # --kb bắt buộc
    args = _parser().parse_args(["--kb", "/kb"])
    assert args.kb == Path("/kb")
    assert args.k == "10,20"
    assert args.int8 is False
    assert args.passage_tokens == 380
    assert args.n == 10


def test_cli_parser_reads_int8_and_custom_values() -> None:
    args = _parser().parse_args(["--kb", "/kb", "--k", "5,15", "--threads", "4", "--int8",
                                 "--passage-tokens", "300", "--n", "3"])  # fmt: skip
    assert (args.k, args.threads, args.int8, args.passage_tokens, args.n) == ("5,15", "4", True, 300, 3)
