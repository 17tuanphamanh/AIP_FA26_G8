"""b3 — kiểm số liệu với `kb-facts.md` (thiết kế Phase 3 mục 5.4; PLAN-3b mục 4.3). Dùng đúng bản
`kb-facts.md` của fixture (chép nguyên văn `docs/spec/build/kb-mau/kb-facts.md`)."""

import shutil
from pathlib import Path

from app.core.clock import FakeClock
from app.rag.ingest.facts_check import check_facts, load_facts
from app.rag.ingest.loader import load_kb
from tests.fakes.kb import FIXTURE_KB, KB_TEST_NOW, write_doc

SPEC_FACTS = Path(__file__).resolve().parents[3] / "docs" / "spec" / "build" / "kb-mau" / "kb-facts.md"


def _kb(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir()
    shutil.copy(FIXTURE_KB / "kb-facts.md", kb / "kb-facts.md")
    return kb


def _check(kb: Path) -> list[str]:
    docs, issues = load_kb(kb, FakeClock(KB_TEST_NOW))
    assert issues == []
    return [str(i) for i in check_facts(kb, docs)]


def test_fixture_facts_is_spec_sample_verbatim() -> None:
    assert (FIXTURE_KB / "kb-facts.md").read_bytes() == SPEC_FACTS.read_bytes()
    facts, issues = load_facts(FIXTURE_KB)
    assert issues == [] and len(facts) == 10


def test_b3_wrong_sstp_port_reported_on_file_line(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    body = "## Giao thức\n\nDòng đầu không nhắc số.\n\nGiao thức dự phòng SSTP, dùng cổng TCP 1194 khi bị chặn.\n"
    write_doc(kb, "vpn/KB-VPN-901.md", body)
    # Thân bài từ dòng 12 (dòng trống sau ---): "## Giao thức" 13, trống 14, "Dòng đầu" 15, trống 16, SSTP 17.
    assert _check(kb) == [
        'kb/vpn/KB-VPN-901.md:17: "1194" không khớp kb-facts vpn_sstp_port (cho phép: 443)'
    ]


def test_b3_doc_without_the_number_has_no_error(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", "## Giao thức\n\nSSTP là giao thức dự phòng, chỉ đổi khi IT hướng dẫn.\n")
    assert _check(kb) == []


def test_b3_correct_numbers_and_optional_group_none(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    body = ("## Cổng\n\nIKEv2 dùng cổng UDP 500. SSTP dùng cổng TCP 443. Máy lẻ 1234.\n\n"
            "Giờ hành chính (08:00–18:00). Được duyệt trong 30 phút.\n")  # fmt: skip
    write_doc(kb, "vpn/KB-VPN-901.md", body)
    assert _check(kb) == []  # nhóm thứ hai của vpn_ikev2_ports là None → bỏ qua


def test_b3_fact_only_applies_to_listed_request_types(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "account/KB-ACC-901.md", "## X\n\nSSTP dùng cổng TCP 1194.\n", doc_id="KB-ACC-901",
              request_type="account")  # fmt: skip
    assert _check(kb) == []  # vpn_sstp_port chỉ áp cho vpn


def test_b3_disabled_doc_is_checked_too(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", "## X\n\nLiên hệ máy lẻ 9999.\n", enabled="false")
    assert _check(kb) == ['kb/vpn/KB-VPN-901.md:15: "9999" không khớp kb-facts it_extension (cho phép: 1234)']


def test_b3_missing_facts_file(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    assert [str(i) for i in load_facts(kb)[1]] == ["kb/kb-facts.md: thiếu file kb-facts.md"]


def test_b3_two_yaml_blocks(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "kb-facts.md").write_text("# F\n\n```yaml\nfacts: []\n```\n\n```yaml\nfacts: []\n```\n", encoding="utf-8")
    assert [str(i) for i in load_facts(kb)[1]] == ["kb/kb-facts.md:7: phải có đúng một khối ```yaml (đang có 2)"]


def test_b3_fact_without_capture_group_is_config_error(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "kb-facts.md").write_text(
        "# F\n\n```yaml\nfacts:\n  - id: ok\n    applies_to: [vpn]\n    regex: 'a(\\d)'\n    allowed: ['1']\n"
        "  - id: khong_nhom\n    applies_to: [vpn]\n    regex: 'TCP \\d+'\n    allowed: ['443']\n```\n",
        encoding="utf-8",
    )
    assert [str(i) for i in load_facts(kb)[1]] == [
        "kb/kb-facts.md:9: regex: khong_nhom: regex phải có ít nhất một nhóm bắt"
    ]


def test_b3_schema_errors(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    (kb / "kb-facts.md").write_text(
        "```yaml\nfacts:\n  - id: a\n    applies_to: [printer]\n    regex: '(x)'\n    allowed: []\n    them: 1\n```\n",
        encoding="utf-8",
    )
    errors = [str(i) for i in load_facts(kb)[1]]
    assert len(errors) == 3 and all(e.startswith("kb/kb-facts.md:3: facts.0.") for e in errors), errors
