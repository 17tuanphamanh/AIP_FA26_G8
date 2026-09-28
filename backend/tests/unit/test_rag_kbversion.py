"""b10 — `kb_version`, `content_sha256`, `pipeline_sha` (thiết kế Phase 3 mục 5.7; PLAN-3b mục 4.6, Q-3b-2, Q-3b-8)."""

import shutil
from dataclasses import replace
from pathlib import Path

from app.core.clock import FakeClock
from app.rag.ingest.kbversion import content_sha256, kb_version, pipeline_sha
from app.rag.ingest.loader import load_kb
from app.rag.models import Doc
from tests.fakes.kb import CONFIG_DIR, FIXTURE_KB, KB_TEST_NOW


def _docs() -> list[Doc]:
    docs, issues = load_kb(FIXTURE_KB, FakeClock(KB_TEST_NOW))
    assert issues == []
    return docs


def _bump(doc: Doc, **fm: object) -> Doc:
    return replace(doc, fm=doc.fm.model_copy(update=fm))


def test_b10_order_independent() -> None:
    docs = _docs()
    assert kb_version(list(reversed(docs))) == kb_version(docs)
    assert len(kb_version(docs)) == 64


def test_b10_version_change_changes_kb_version() -> None:
    docs = _docs()
    changed = [_bump(d, version=2) if d.fm.doc_id == "KB-VPN-003" else d for d in docs]
    assert kb_version(changed) != kb_version(docs)


def test_b10_disabled_docs_do_not_matter() -> None:
    docs = _docs()
    disabled = next(d for d in docs if not d.fm.enabled)
    edited = [_bump(d, version=9, title="Tiêu đề khác hẳn") if d is disabled else d for d in docs]
    assert kb_version(edited) == kb_version(docs)
    assert kb_version([d for d in docs if d is not disabled]) == kb_version(docs)
    extra = _bump(disabled, doc_id="KB-VPN-099")
    assert kb_version([*docs, extra]) == kb_version(docs)
    # bật lại tài liệu disabled thì đổi
    assert kb_version([_bump(d, enabled=True) if d is disabled else d for d in docs]) != kb_version(docs)


def test_b10_content_sha_changes_on_enabled_or_one_char() -> None:
    doc = next(d for d in _docs() if d.fm.doc_id == "KB-VPN-003")
    base = content_sha256(doc)
    assert content_sha256(_bump(doc, enabled=False)) != base
    assert content_sha256(replace(doc, body=doc.body.replace("809", "808", 1))) != base
    assert content_sha256(replace(doc, body=doc.body + " ")) != base
    assert content_sha256(doc) == base  # tất định


def test_content_sha_includes_default_fields() -> None:
    doc = next(d for d in _docs() if d.fm.doc_id == "KB-VPN-001")
    assert content_sha256(_bump(doc, distractor=True)) != content_sha256(doc)


def test_pipeline_sha_follows_config_files(tmp_path: Path) -> None:
    cfg = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, cfg)
    base = pipeline_sha(cfg)
    assert base == pipeline_sha(CONFIG_DIR) and len(base) == 64
    with (cfg / "vi_stopwords.txt").open("a", encoding="utf-8") as f:
        f.write("thêm\n")
    assert pipeline_sha(cfg) != base
