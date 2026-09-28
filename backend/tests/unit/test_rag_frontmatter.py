"""b1, b2, b21, b22 — front matter + luật loader (thiết kế Phase 3 mục 5.3; PLAN-3b mục 4.2, Q-3b-13).

Mỗi test dựng KB nhỏ trong `tmp_path` (thư mục tên `kb`, nên đường dẫn trong lỗi là `kb/vpn/…`)."""

from pathlib import Path

import pytest
from app.core.clock import FakeClock
from app.db.models import KB_DOC_TYPES, KB_REQUEST_TYPES, KB_SENSITIVITY
from app.rag.ingest.loader import load_kb
from app.rag.models import FrontMatter
from pydantic import ValidationError
from tests.fakes.kb import FRONT, KB_TEST_NOW, write_doc

CLOCK = FakeClock(KB_TEST_NOW)


def _kb(tmp_path: Path) -> Path:
    kb = tmp_path / "kb"
    kb.mkdir()
    return kb


def _errors(kb: Path) -> list[str]:
    return [str(i) for i in load_kb(kb, CLOCK)[1]]


def test_valid_doc_loads(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md")
    docs, issues = load_kb(kb, CLOCK)
    assert issues == []
    assert [d.fm.doc_id for d in docs] == ["KB-VPN-901"]
    assert docs[0].rel_path == "kb/vpn/KB-VPN-901.md"
    assert docs[0].body_start_line == 12  # 1 dòng ---, 9 khoá, 1 dòng ---; thân bài từ dòng 12 (dòng trống)
    assert docs[0].body.startswith("\n## Mục một")


# Dòng file của từng khoá trong `doc_text`: `---` là dòng 1, khoá theo thứ tự FRONT từ dòng 2.
LINE = {k: i for i, k in enumerate(FRONT, start=2)}

B1_CASES = [
    ("thieu-truong", {"drop": ("title",)}, "kb/vpn/KB-VPN-901.md:1: title: thiếu trường"),
    ("truong-la", {"mau": "do"}, f"kb/vpn/KB-VPN-901.md:{len(FRONT) + 2}: mau: trường không được phép"),
    ("version-0", {"version": "0"}, f"kb/vpn/KB-VPN-901.md:{LINE['version']}: version: phải ≥ 1"),
    ("doc-id-sai-mau", {"doc_id": "KB-VPN-9"}, f"kb/vpn/KB-VPN-901.md:{LINE['doc_id']}: doc_id: sai định dạng"),
    ("request-type-la", {"request_type": "printer"},
     f"kb/vpn/KB-VPN-901.md:{LINE['request_type']}: request_type: phải là một trong: account, vpn"),
    ("sensitivity-la", {"sensitivity": "secret"},
     f"kb/vpn/KB-VPN-901.md:{LINE['sensitivity']}: sensitivity: phải là một trong: public, internal, restricted"),
    ("title-ngan", {"title": "VPN"}, f"kb/vpn/KB-VPN-901.md:{LINE['title']}: title: độ dài phải 5–120 ký tự"),
    ("updated-at-tuong-lai", {"updated_at": "2026-09-29"},
     f"kb/vpn/KB-VPN-901.md:{LINE['updated_at']}: updated_at: ngày ở tương lai"),
]  # fmt: skip


@pytest.mark.parametrize(("over", "expected"), [c[1:] for c in B1_CASES], ids=[c[0] for c in B1_CASES])
def test_b1_front_matter_error_points_to_file_line_field(
    tmp_path: Path, over: dict[str, object], expected: str
) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", **over)  # type: ignore[arg-type]
    errors = _errors(kb)
    assert any(e.startswith(expected) for e in errors), errors


def test_b1_future_date_uses_vietnam_day(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", updated_at="2026-09-28")
    # 2026-09-27 17:30 UTC = 2026-09-28 00:30 giờ VN → hôm nay (VN) là 28: không lỗi.
    assert load_kb(kb, FakeClock(KB_TEST_NOW.replace(day=27, hour=17, minute=30)))[1] == []
    # 16:59 UTC = 23:59 ngày 27 giờ VN → 28 là tương lai.
    assert load_kb(kb, FakeClock(KB_TEST_NOW.replace(day=27, hour=16, minute=59)))[1] != []


def test_b1_errors_of_every_file_are_reported(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", version="0")
    write_doc(kb, "vpn/KB-VPN-902.md", doc_id="KB-VPN-902", drop=("owner",))
    errors = _errors(kb)
    assert any(e.startswith("kb/vpn/KB-VPN-901.md:") and "version" in e for e in errors)
    assert any(e.startswith("kb/vpn/KB-VPN-902.md:1: owner: thiếu trường") for e in errors)
    assert errors == sorted(errors)  # sắp theo file rồi dòng


def test_b1_yaml_and_fence_errors(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    (kb / "vpn").mkdir()
    (kb / "vpn" / "KB-VPN-901.md").write_text("## Không có front matter\n", encoding="utf-8")
    (kb / "vpn" / "KB-VPN-902.md").write_text("---\ndoc_id: [a\n---\n## X\n", encoding="utf-8")
    errors = _errors(kb)
    assert "kb/vpn/KB-VPN-901.md:1: file phải bắt đầu bằng dòng --- (front matter)" in errors
    assert any(e.startswith("kb/vpn/KB-VPN-902.md:") and "YAML front matter sai" in e for e in errors)


# ---- b2: bố cục, tên file, doc_id trùng, tiền tố ----------------------------------------------


def test_b2_file_name_must_equal_doc_id(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-902.md")  # doc_id KB-VPN-901
    assert f"kb/vpn/KB-VPN-902.md:{LINE['doc_id']}: doc_id: tên file phải bằng doc_id (KB-VPN-901.md)" in _errors(kb)


def test_b2_duplicate_doc_id_reported_in_both_files(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md")
    write_doc(kb, "account/KB-VPN-901.md", request_type="account")
    dup = [e for e in _errors(kb) if "trùng" in e]
    assert {e.split(":")[0] for e in dup} == {"kb/vpn/KB-VPN-901.md", "kb/account/KB-VPN-901.md"}


def test_b2_folder_must_equal_request_type(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "account/KB-VPN-901.md")  # request_type vpn nằm trong account/
    errors = _errors(kb)
    assert any(e.startswith(f"kb/account/KB-VPN-901.md:{LINE['request_type']}: request_type: phải bằng thư mục")
               for e in errors)  # fmt: skip


def test_b2_doc_id_prefix_must_match_request_type(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "account/KB-VPN-901.md", request_type="account")
    assert any("tiền tố phải là KB-ACC-" in e for e in _errors(kb))
    kb2 = tmp_path / "kb2" / "kb"
    kb2.mkdir(parents=True)
    write_doc(kb2, "account/KB-ACC-901.md", request_type="account", doc_id="KB-ACC-901")
    assert load_kb(kb2, CLOCK)[1] == []


def test_b2_unknown_folder_and_nested_md(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "printer/KB-VPN-901.md")
    write_doc(kb, "vpn/cu/KB-VPN-902.md", doc_id="KB-VPN-902")
    errors = _errors(kb)
    assert any(e.startswith("kb/printer: thư mục không phải request_type") for e in errors)
    assert "kb/vpn/cu/KB-VPN-902.md: tài liệu phải ở kb/<request_type>/<doc_id>.md" in errors


def test_b2_ignored_entries(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md")
    (kb / "README.md").write_text("# KB\n", encoding="utf-8")
    (kb / "kb-facts.md").write_text("# facts\n", encoding="utf-8")
    (kb / "eval").mkdir()
    (kb / "eval" / "ghi-chu.md").write_text("không phải tài liệu\n", encoding="utf-8")
    (kb / "eval" / ".gitkeep").write_text("", encoding="utf-8")
    (kb / "vpn" / ".gitkeep").write_text("", encoding="utf-8")
    (kb / "vpn" / "ghi-chu.txt").write_text("x", encoding="utf-8")
    (kb / ".an").mkdir()
    (kb / ".an" / "x.md").write_text("x", encoding="utf-8")
    docs, issues = load_kb(kb, CLOCK)
    assert issues == [] and [d.fm.doc_id for d in docs] == ["KB-VPN-901"]


# ---- b21: miền giá trị lấy từ db/models --------------------------------------------------------


@pytest.mark.parametrize(("field", "values"), [
    ("request_type", KB_REQUEST_TYPES), ("doc_type", KB_DOC_TYPES), ("sensitivity", KB_SENSITIVITY),
])  # fmt: skip
def test_b21_front_matter_domains_come_from_db_constants(field: str, values: tuple[str, ...]) -> None:
    base = {**FRONT, "enabled": True, "version": 1}
    for v in values:
        FrontMatter.model_validate({**base, field: v})
    with pytest.raises(ValidationError):
        FrontMatter.model_validate({**base, field: "khac"})


# ---- b22: luật bổ sung Q-3b-13 ----------------------------------------------------------------


@pytest.mark.parametrize(("over", "expected"), [
    ({"supersedes": "cu"}, "supersedes: sai định dạng"),
    ({"supersedes": "KB-VPN-901"}, "supersedes: không được trỏ về chính nó"),
    ({"supersedes": "KB-VPN-555"}, "supersedes: KB-VPN-555 không có trong KB"),
], ids=["sai-mau", "chinh-no", "khong-co"])  # fmt: skip
def test_b22_supersedes(tmp_path: Path, over: dict[str, str], expected: str) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", **over)
    assert any(expected in e for e in _errors(kb)), _errors(kb)


def test_b22_supersedes_existing_doc_ok(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", supersedes="KB-VPN-902")
    write_doc(kb, "vpn/KB-VPN-902.md", doc_id="KB-VPN-902", enabled="false")
    assert _errors(kb) == []


# Thân bài bắt đầu ở dòng 12 của file (dòng trống sau `---`, xem test_valid_doc_loads); `body` bắt đầu ở dòng 13.
@pytest.mark.parametrize(("body", "expected"), [
    ("### Con\n\nx\n\n## Mục\n\ny\n", "kb/vpn/KB-VPN-901.md:13: ### phải nằm dưới một ##"),
    ("## Mục\n\n#### Sâu\n", "kb/vpn/KB-VPN-901.md:15: chỉ dùng ## và ###"),
    ("Chỉ có đoạn văn, không heading.\n", "kb/vpn/KB-VPN-901.md:12: thân bài phải có ít nhất một heading ##"),
    ("# Tiêu đề\n\n## Mục\n\nx\n", "kb/vpn/KB-VPN-901.md:13: không dùng heading # (H1)"),
], ids=["h3-truoc-h2", "h4", "khong-h2", "h1"])  # fmt: skip
def test_b22_body_heading_rules(tmp_path: Path, body: str, expected: str) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", body)
    assert any(e.startswith(expected) for e in _errors(kb)), _errors(kb)


def test_b22_headings_inside_code_fence_ignored(tmp_path: Path) -> None:
    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", "## Mục\n\n```\n# không phải H1\n#### cũng không\n```\n")
    assert _errors(kb) == []


@pytest.mark.asyncio
async def test_b1_run_ingest_stops_at_step_1(tmp_path: Path) -> None:
    import io
    from typing import Any, cast

    from app.rag.ingest.pipeline import IngestDeps, IngestOptions, run_ingest
    from tests.fakes.kb import CONFIG_DIR

    kb = _kb(tmp_path)
    write_doc(kb, "vpn/KB-VPN-901.md", version="0")
    write_doc(kb, "vpn/KB-VPN-902.md", doc_id="KB-VPN-902", title="VPN")
    unused = cast(Any, None)  # bước 1 dừng trước khi đụng Qdrant, ml-service, DB
    out, err = io.StringIO(), io.StringIO()
    deps = IngestDeps(index=unused, ml=unused, counter=unused, repo=unused, clock=CLOCK, app_env="test",
                      retrieval_threshold=0.6, keep_old=2, config_dir=CONFIG_DIR, out=out, err=err,
                      rag=unused)  # fmt: skip
    assert await run_ingest(IngestOptions(kb), deps) == 1
    lines = err.getvalue().splitlines()
    assert f"kb/vpn/KB-VPN-901.md:{LINE['version']}: version: phải ≥ 1" in lines
    assert f"kb/vpn/KB-VPN-902.md:{LINE['title']}: title: độ dài phải 5–120 ký tự" in lines
    assert lines[-1].startswith("bước 1: 2 lỗi tài liệu") and out.getvalue() == ""


@pytest.mark.asyncio
async def test_step0_flag_rejected_outside_dev_test(tmp_path: Path) -> None:
    import io
    from typing import Any, cast

    from app.rag.ingest.pipeline import IngestDeps, IngestOptions, run_ingest
    from tests.fakes.kb import CONFIG_DIR

    unused = cast(Any, None)
    for env in ("prod", "staging", None):
        err = io.StringIO()
        deps = IngestDeps(index=unused, ml=unused, counter=unused, repo=unused, clock=CLOCK, app_env=env,
                          retrieval_threshold=0.6, keep_old=2, config_dir=CONFIG_DIR, out=io.StringIO(), err=err,
                          rag=unused)  # fmt: skip
        assert await run_ingest(IngestOptions(tmp_path / "kb", allow_unevaluated=True), deps) == 1
        assert err.getvalue().startswith("bước 0: --allow-unevaluated chỉ dùng khi APP_ENV ∈ {dev,test}")
