"""Mutation chặng 3b (RAG ingest): áp từng đột biến, chạy test, KHÔI PHỤC, so md5; in test đỏ của mỗi đột biến.

Chạy từ gốc repo:
  uv run python scripts/mutation/mutate_3b.py                  # M-3b-1/3/4/7 + spy của M-3b-5 (sandbox, không Docker)
  uv run python scripts/mutation/mutate_3b.py --integration    # M-3b-2, M-3b-6, S1–S3 (cần Docker — người chạy)
  uv run python scripts/mutation/mutate_3b.py --only M-3b-4    # chỉ đột biến có tên bắt đầu bằng tiền tố

M-3b-3 cần tokenizer bge-m3 thật (`make tokenizer` hoặc `make models`) — thiếu thì b4 bị skip và đột biến "SỐNG".
M-3b-5 (đổi alias bằng hai lệnh) chính thức kiểm bằng REVIEW (spec 5.12); ở đây chạy thêm test spy b27.
Không đọc `.env`: pytest chạy qua `conftest.py` gốc. Mã thoát 1 nếu có đột biến sống hoặc không áp được. File luôn
được khôi phục trong `finally`, cuối cùng so md5 và `git diff --stat` với lúc đầu.
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def pt(*args: str) -> list[str]:
    return ["uv", "run", "pytest", *args, "-q", "-p", "no:cacheprovider"]


UNIT = [
    ("M-3b-1 bỏ sorted trong kb_version", "backend/app/rag/ingest/kbversion.py",
     'sha256("\\n".join(sorted(f"{d.fm.doc_id}:{d.fm.version}" for d in docs if d.fm.enabled)).encode())',
     'sha256("\\n".join(f"{d.fm.doc_id}:{d.fm.version}" for d in docs if d.fm.enabled).encode())',
     pt("backend/tests/unit/test_rag_kbversion.py"), ["test_b10_order_independent"]),
    ("M-3b-3 trần nội dung 380 → 480", "backend/app/rag/ingest/config.py",
     "CHUNK_TOKENS_MAX = 380  #", "CHUNK_TOKENS_MAX = 480  # MUTATION",
     pt("backend/tests/unit/test_rag_chunker.py", "-k", "b4"),
     ["test_b4_fixture_chunks_within_limits_real_tokenizer"]),
    ("M-3b-4 bỏ gộp va chạm băm", "backend/app/rag/bm25.py",
     "    c = Counter(_token_hash(t) for t in tokens)  # gộp va chạm băm\n",
     "    c = {_token_hash(t): 1 for t in tokens}  # MUTATION gán đè\n",
     pt("backend/tests/unit/test_rag_bm25.py"), ["test_b9_to_sparse_merges_collisions"]),
    ("M-3b-5 đổi alias bằng hai lệnh (spy b27)", "backend/app/rag/vector_store.py",
     "            await self._client.update_collection_aliases(change_aliases_operations=ops)  # MỘT lệnh, nguyên tử\n",
     ("            for op in ops:  # MUTATION hai lệnh\n"
      "                await self._client.update_collection_aliases(change_aliases_operations=[op])\n"),
     pt("backend/tests/unit/test_rag_vector_store_spy.py"), ["test_switch_alias_single_atomic_call"]),
    ("M-3b-7 stopword thêm \"không\"", "config/vi_stopwords.txt",
     "nữa\nhãy\n", "nữa\nhãy\nkhông\n",
     pt("backend/tests/unit/test_rag_bm25.py", "backend/tests/unit/test_config_files.py"),
     ["test_b8_tokenize_vi[negation]", "test_stopwords_exclude_negation"]),
]  # fmt: skip

ING = "backend/tests/integration/test_rag_ingest_pg.py"
MIG = ["backend/tests/integration/test_migration.py", "backend/tests/integration/test_migration_0006.py"]
INTEGRATION = [
    ("M-3b-2 bỏ kiểm content_sha256 (bước 4)", "backend/app/rag/ingest/pipeline.py",
     "changed = [doc for doc in docs if stored.get(_key(doc)) not in (None, doc.content_sha256)]",
     "changed = [doc for doc in docs if False]  # MUTATION",
     pt(ING, "-k", "b11"), ["test_b11_same_version_changed_content_stops"]),
    ("M-3b-6 nhánh (a) luôn đạt", "backend/app/rag/ingest/gate.py",
     '        return GateDecision(False, "a", "unevaluated",',
     '        return GateDecision(True, "a", "unevaluated",  # MUTATION',
     pt(ING, "-k", "b15"), ["test_b15_no_eval_no_flag_keeps_alias"]),
    ("M-3b-S1 migration bỏ index duy nhất", "backend/app/db/alembic/versions/0006_kb_content_hash.py",
     ('    op.create_index(\n        "ux_kb_versions_current", "kb_versions", ["is_current"], unique=True,\n'
      '        postgresql_where=sa.text("is_current"),\n    )  # fmt: skip\n'),
     "    pass  # MUTATION bỏ create_index\n",
     pt(*MIG), ["test_0006_single_current", "test_models_match_migration"]),
    ("M-3b-S2 model bỏ content_sha256", "backend/app/db/models.py",
     "    content_sha256: Mapped[str | None] = mapped_column(CHAR(64))\n", "    # MUTATION bỏ content_sha256\n",
     pt(MIG[0], "-k", "models_match"), ["test_models_match_migration"]),
    ("M-3b-S3 migration bỏ CHECK eval_status", "backend/app/db/alembic/versions/0006_kb_content_hash.py",
     "    op.create_check_constraint(\n", "    (lambda *a: None)(  # MUTATION bỏ CHECK\n",
     pt(MIG[1], "-k", "eval_status"), ["test_0006_eval_status_check"]),
]  # fmt: skip

MUTATIONS = INTEGRATION if "--integration" in sys.argv else UNIT
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in UNIT + INTEGRATION if m[0].startswith(prefix)]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def main() -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    before = {m[1]: md5(REPO / m[1]) for m in MUTATIONS}
    diff_before = git_diff_stat()
    bad = 0
    for name, rel, old, new, cmd, expect in MUTATIONS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if original.count(old) != 1:
            print(f"!! {name}: chuỗi gốc xuất hiện {original.count(old)} lần — bỏ qua")
            bad += 1
            continue
        mutated = original.replace(old, new)
        try:
            path.write_text(mutated, encoding="utf-8")
            out = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=1200, check=False)
        finally:
            path.write_text(original, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?)(?: - |$)", out.stdout, re.MULTILINE)))
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        missing = [e for e in expect if not any(f.endswith("::" + e) or ("::" + e + "[") in f for f in failed)]
        status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        if missing:
            bad += 1
        print(f"{name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
        if missing:
            print(f"    thiếu test dự đoán: {missing}")
            print("    " + "\n    ".join(out.stdout.strip().splitlines()[-5:]))
    after = {rel: md5(REPO / rel) for rel in before}
    assert after == before, "md5 khác sau khôi phục!"
    print("md5 sau khôi phục: khớp")
    assert git_diff_stat() == diff_before, "git diff --stat khác lúc đầu!"
    print("git diff --stat: khớp lúc đầu")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
