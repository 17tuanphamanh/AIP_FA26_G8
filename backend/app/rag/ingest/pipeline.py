"""`make ingest` — 14 bước (thiết kế Phase 3 mục 5.8; PLAN-3b mục 7; Q-3b-1…17).

Mã thoát (Q-3b-12): 0 = xong / "KB không đổi" / ghi bù xong; 1 = mọi lỗi TRƯỚC khi đổi alias (alias giữ nguyên);
2 = lỗi ở bước 12–14 (alias ĐÃ đổi — chạy lại để ghi bù). Lỗi dự kiến là GIÁ TRỊ: in rồi trả mã. Exception không
lường trước để nổi lên (CLI in kèm số bước) — gồm cả "process chết" giữa bước 11 và 12 mà test b18 giả lập.

Nguồn sự thật (3-Q16): alias `kb_current` là bản đang chạy. Chết sau khi đổi alias mà chưa ghi DB → lần chạy sau thấy
alias đúng `kb_<v>` nhưng DB lệch → chỉ ghi bù DB, lấy số từ metadata collection (Q-3b-3).
`--dry-run` (người chốt 27/09/2026): chạy bước 1–6, bước 4–5 chỉ đọc (không ghi bù), không lấy khoá, không ghi gì.
"""

import statistics
import sys
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO
from uuid import NAMESPACE_URL, uuid5

from qdrant_client.models import PointStruct
from sqlalchemy.exc import SQLAlchemyError

from app.core.clock import Clock
from app.db.kb import DocRow, KbRepo
from app.ml.ports import MlPort
from app.rag.bm25 import load_lexicon, to_sparse, tokenize_vi
from app.rag.ingest.chunker import chunk_doc
from app.rag.ingest.config import (
    ALIAS,
    DENSE_DIM,
    INGEST_EMBED_GROUP,
    INGEST_LOCK_KEY,
    UPSERT_BATCH,
)
from app.rag.ingest.facts_check import check_facts
from app.rag.ingest.gate import (
    DenseOnlyRetriever,
    GateMetrics,
    decide,
    evaluate,
    load_retrieval_set,
)
from app.rag.ingest.kbversion import content_sha256, kb_version, pipeline_sha
from app.rag.ingest.loader import load_kb
from app.rag.models import (
    Chunk,
    ChunkPayload,
    Doc,
    IngestError,
    IngestIssue,
    IngestMlError,
    IngestReport,
)
from app.rag.token_counter import TokenCounter
from app.rag.vector_store import VectorIndex, VectorStoreError
from app.settings import DEV_FAKE_ENVS

STEP_NOTE = "ingest: lỗi ở bước {}"  # ghi vào exception không lường trước — CLI đọc lại
GATE_KEYS = ("chunk_count", "doc_count", "eval_status", "recall_at5", "false_grounding_rate")  # ghi bù cần đủ


@dataclass(frozen=True)
class IngestOptions:
    kb_dir: Path
    dry_run: bool = False
    allow_unevaluated: bool = False


@dataclass
class IngestDeps:
    index: VectorIndex
    ml: MlPort
    counter: TokenCounter
    repo: KbRepo
    clock: Clock
    app_env: str | None
    retrieval_threshold: float  # get_policy().constants.RETRIEVAL_THRESHOLD — không lặp hằng ở đây
    keep_old: int  # Settings.rag_keep_old_collections
    config_dir: Path
    out: TextIO = field(default_factory=lambda: sys.stdout)
    err: TextIO = field(default_factory=lambda: sys.stderr)


class _Run:
    def __init__(self, opts: IngestOptions, deps: IngestDeps) -> None:
        self.opts = opts
        self.d = deps
        self.step: int | str = 0

    def say(self, msg: str) -> None:
        print(msg, file=self.d.out)

    def fail(self, msg: str, code: int = 1) -> int:
        print(f"bước {self.step}: {msg}", file=self.d.err)
        return code

    def issues(self, issues: list[IngestIssue], what: str) -> int:
        for issue in issues:
            print(issue, file=self.d.err)
        return self.fail(f"{len(issues)} lỗi {what} — sửa rồi chạy lại")


async def run_ingest(opts: IngestOptions, deps: IngestDeps) -> int:
    run = _Run(opts, deps)
    try:
        return await _run(run)
    except Exception as e:  # không lường trước: để nổi lên, kèm số bước cho CLI
        e.add_note(STEP_NOTE.format(run.step))
        raise


async def _run(run: _Run) -> int:
    opts, d = run.opts, run.d
    # 0 — cờ bỏ cổng kiểm chỉ ở dev/test (kể cả khi có bộ kiểm tra)
    if opts.allow_unevaluated and d.app_env not in DEV_FAKE_ENVS:
        return run.fail(f"--allow-unevaluated chỉ dùng khi APP_ENV ∈ {{dev,test}} (đang là {d.app_env!r})")
    # 1 — front matter + luật loader
    run.step = 1
    docs, issues = load_kb(opts.kb_dir, d.clock)
    if issues:
        return run.issues(issues, "tài liệu")
    # 2 — kb-facts
    run.step = 2
    issues = check_facts(opts.kb_dir, docs)
    if issues:
        return run.issues(issues, "số liệu (kb-facts)")
    # 3 — kb_version, content_sha256, pipeline_sha
    run.step = 3
    docs = [replace(doc, content_sha256=content_sha256(doc)) for doc in docs]
    enabled = [doc for doc in docs if doc.fm.enabled]
    if not enabled:
        return run.issues([IngestIssue(opts.kb_dir.name, None, "KB không có tài liệu enabled")], "KB")
    v = kb_version(docs)
    psha = pipeline_sha(d.config_dir)
    run.say(f"kb_version={v}")
    if opts.dry_run:
        return await _after_lock(run, docs, enabled, v, psha)
    # 3½ — một lượt ingest mỗi lúc (Q-3b-15)
    run.step = "3½"
    try:
        lock = await d.repo.try_lock(INGEST_LOCK_KEY)
    except SQLAlchemyError as e:
        return run.fail(f"không lấy được khoá ingest: {type(e).__name__}: {e}")
    if lock is None:
        return run.fail("đang có lượt ingest khác — chờ lượt đó xong rồi chạy lại")
    try:
        return await _after_lock(run, docs, enabled, v, psha)
    finally:
        try:
            await d.repo.release(lock, INGEST_LOCK_KEY)
        except SQLAlchemyError as e:
            print(f"cảnh báo: nhả khoá ingest lỗi (tự nhả khi đóng kết nối): {e}", file=d.err)


async def _after_lock(run: _Run, docs: list[Doc], enabled: list[Doc], v: str, psha: str) -> int:
    opts, d = run.opts, run.d
    name = f"kb_{v}"
    # 4 — sửa nội dung mà không tăng version (3-Q4), với MỌI tài liệu kể cả disabled
    run.step = 4
    try:
        stored = await d.repo.doc_rows([(doc.fm.doc_id, doc.fm.version) for doc in docs])
    except SQLAlchemyError as e:
        return run.fail(f"đọc kb_documents lỗi: {type(e).__name__}: {e}")
    changed = [doc for doc in docs if stored.get(_key(doc)) not in (None, doc.content_sha256)]
    if changed:
        for doc in changed:
            print(f"{doc.fm.doc_id} v{doc.fm.version}: nội dung đã đổi nhưng chưa tăng version", file=d.err)
        return run.fail(f"{len(changed)} tài liệu đổi nội dung mà giữ nguyên version — tăng version rồi chạy lại")
    # 5 — alias đã đúng bản này?
    run.step = 5
    try:
        target = await d.index.alias_target(ALIAS)
        if target == name:
            meta = await d.index.get_metadata(name)
            if meta.get("pipeline_sha") != psha:
                return run.fail(
                    "cấu hình ingest đã đổi (pipeline_sha của collection đang chạy khác cấu hình hiện tại) — "
                    "tăng version một tài liệu rồi chạy lại"
                )
            if await _db_matches(d.repo, v, docs, stored):
                run.say(f"KB không đổi — alias {ALIAS} → {name}, DB khớp")
                return 0
            if not opts.dry_run:
                return await _backfill(run, docs, enabled, v, meta)
            run.say(f"DB lệch với alias {ALIAS} → {name}: sẽ ghi bù DB khi chạy thật (3-Q16)")
    except VectorStoreError as e:
        return run.fail(str(e))
    except SQLAlchemyError as e:
        return run.fail(f"đọc kb_versions lỗi: {type(e).__name__}: {e}")
    # 6 — chia đoạn
    run.step = 6
    per_doc: list[tuple[Doc, list[Chunk]]] = []
    errors: list[IngestIssue] = []
    try:
        for doc in enabled:
            try:
                per_doc.append((doc, await chunk_doc(doc, d.counter)))
            except IngestError as e:
                errors.append(e.issue)
    except IngestMlError as e:
        return run.fail(str(e))
    if errors:
        return run.issues(errors, "chia đoạn")
    chunks = [(doc, c) for doc, cs in per_doc for c in cs]
    run.say(
        f"tài liệu: {len(enabled)} enabled / {len(docs)} tổng; số đoạn: {len(chunks)}; "
        f"max text_tokens: {max(c.text_tokens for _, c in chunks)}; truncated=0"
    )
    if opts.dry_run:
        run.say("dry-run: dừng sau bước 6 — không lấy khoá, không ghi gì")
        return 0
    return await _index_and_switch(run, docs, enabled, chunks, v, psha, target)


async def _index_and_switch(
    run: _Run, docs: list[Doc], enabled: list[Doc], chunks: list[tuple[Doc, Chunk]], v: str, psha: str,
    target: str | None,
) -> int:  # fmt: skip
    opts, d = run.opts, run.d
    name = f"kb_{v}"
    # 7 — embed từng nhóm INGEST_EMBED_GROUP (Q-3b-1); không chấp nhận bị cắt
    run.step = 7
    texts = [c.text for _, c in chunks]
    vectors: list[list[float]] = []
    elapsed: list[float] = []
    for i in range(0, len(texts), INGEST_EMBED_GROUP):
        group = texts[i : i + INGEST_EMBED_GROUP]
        started = time.perf_counter()
        result = await d.ml.embed(group)
        elapsed.append((time.perf_counter() - started) * 1000)
        if result.error is not None or result.data is None:
            return run.fail(f"ml-service /embed lỗi: {result.error} sau {result.attempts} lần")
        data = result.data
        cut = [chunks[i + k][1].chunk_id for k, t in enumerate(data.truncated) if t]
        if cut:
            return run.fail(f"{len(cut)} đoạn bị model cắt (truncated) — không được cắt âm thầm: {', '.join(cut)}")
        if data.dim != DENSE_DIM or len(data.vectors) != len(group) or any(len(x) != DENSE_DIM for x in data.vectors):
            return run.fail(f"ml-service /embed trả {len(data.vectors)} vector dim {data.dim} cho {len(group)} đoạn")
        vectors.extend(data.vectors)
    run.say(
        f"embed: {len(texts)} đoạn, tổng {sum(elapsed):.0f} ms, p50 {statistics.median(elapsed):.0f} ms, "
        f"max {max(elapsed):.0f} ms"
    )
    try:
        # 8 — tạo lại collection (bước 5 đã loại ca trùng đích alias)
        run.step = 8
        if await d.index.exists(name):
            await d.index.drop(name)
        await d.index.create(name, {"kb_version": v, "pipeline_sha": psha})
        # 9 — dựng điểm, upsert theo lô, đếm lại
        run.step = 9
        lexicon = load_lexicon(d.config_dir)
        points = [
            PointStruct(
                id=str(uuid5(NAMESPACE_URL, c.chunk_id)),
                vector={"dense": vec, "bm25": to_sparse(tokenize_vi(c.text, lexicon=lexicon))},
                payload=_payload(doc, c, v).model_dump(),
            )
            for (doc, c), vec in zip(chunks, vectors, strict=True)
        ]
        for i in range(0, len(points), UPSERT_BATCH):
            await d.index.upsert(name, points[i : i + UPSERT_BATCH])
        stored = await d.index.count(name)
        if stored != len(points):
            return run.fail(f"{name} có {stored} điểm, cần {len(points)} — collection giữ lại để xem")
        # 10 — cổng kiểm
        run.step = 10
        rs, issues = load_retrieval_set(opts.kb_dir)
        if issues:
            return run.issues(issues, "bộ kiểm tra")
        new = old = None
        if rs is not None:
            retriever = DenseOnlyRetriever(d.index, d.ml)
            new = await evaluate(rs, retriever, name, d.retrieval_threshold)
            if target is not None:
                old = await evaluate(rs, retriever, target, d.retrieval_threshold)  # Q-3b-4
        decision = decide(has_set=rs is not None, allow_unevaluated=opts.allow_unevaluated, new=new, old=old)
        run.say(_gate_line(decision.branch, new, old))
        if not decision.passed:
            return run.fail(
                f"cổng kiểm KHÔNG đạt (nhánh {decision.branch}): {decision.reason}. Alias giữ nguyên"
                f"{'' if target is None else f' ({target})'}; collection {name} giữ lại để xem"
            )
        report = {
            "chunk_count": len(chunks), "doc_count": len(enabled), "eval_status": decision.eval_status,
            "recall_at5": new.recall_at5 if new else None,
            "false_grounding_rate": new.false_grounding_rate if new else None, "mrr": new.mrr if new else None,
        }  # fmt: skip
        await d.index.set_metadata(name, report)
        # 11 — đổi alias NGUYÊN TỬ; lỗi → alias cũ còn nguyên
        run.step = 11
        await d.index.switch_alias(ALIAS, name, had_alias=target is not None)
    except IngestMlError as e:
        return run.fail(str(e))
    except VectorStoreError as e:
        return run.fail(str(e))
    run.say(f"alias {ALIAS} → {name}")
    # 12 — ghi DB, một transaction
    run.step = 12
    try:
        await _write_db(run, docs, v, report)
    except SQLAlchemyError as e:
        return run.fail(_backfill_hint(name, e), code=2)
    code = 0
    # 13 — snapshot
    run.step = 13
    try:
        run.say(f"snapshot: {await d.index.snapshot(name)}")
    except VectorStoreError as e:
        code = run.fail(f"(cảnh báo) snapshot lỗi — alias đã đổi, không quay lui: {e}", code=2)
    # 14 — dọn collection cũ
    run.step = 14
    try:
        dropped = await _cleanup(d, name)
        run.say(f"dọn: {'đã xoá ' + ', '.join(dropped) if dropped else 'không có collection nào cần xoá'}")
    except (VectorStoreError, SQLAlchemyError) as e:
        code = run.fail(f"(cảnh báo) dọn collection cũ lỗi: {e}", code=2)
    run.step = "✓"
    summary = IngestReport(v, name, len(enabled), len(chunks), decision.eval_status)
    run.say(
        f"xong: kb_version={summary.kb_version}, collection={summary.collection}, "
        f"số đoạn={summary.chunk_count}, truncated=0, eval_status={summary.eval_status}"
    )
    return code


# ---- phụ trợ ---------------------------------------------------------------------------------------


def _key(doc: Doc) -> tuple[str, int]:
    return doc.fm.doc_id, doc.fm.version


def _payload(doc: Doc, c: Chunk, v: str) -> ChunkPayload:
    fm = doc.fm
    return ChunkPayload(
        chunk_id=c.chunk_id, doc_id=fm.doc_id, version=fm.version, seq=c.seq, title=fm.title,
        heading_path=c.heading_path, request_type=fm.request_type, doc_type=fm.doc_type,
        sensitivity=fm.sensitivity, enabled=fm.enabled, distractor=fm.distractor, text=c.text,
        token_count=c.text_tokens, kb_version=v, owner=fm.owner,
    )  # fmt: skip


async def _db_matches(repo: KbRepo, v: str, docs: list[Doc], stored: dict[tuple[str, int], str | None]) -> bool:
    row = await repo.version_row(v)
    return row is not None and row.is_current and all(stored.get(_key(doc)) == doc.content_sha256 for doc in docs)


def _backfill_hint(name: str, e: Exception) -> str:
    return (
        f"alias đã đổi sang {name} nhưng chưa ghi DB — chạy lại `make ingest` để ghi bù (3-Q16). "
        f"Lỗi: {type(e).__name__}: {e}"
    )


async def _write_db(run: _Run, docs: list[Doc], v: str, report: dict[str, Any]) -> None:
    """Bước 12 (và ghi bù ở bước 5): owner chưa có trong `users` → NULL + một dòng cảnh báo mỗi owner (3-Q40)."""
    d = run.d
    known = await d.repo.known_users(doc.fm.owner for doc in docs)
    for owner in sorted({doc.fm.owner for doc in docs} - known):
        print(f"cảnh báo: owner {owner} chưa có trong bảng users — ghi kb_documents.owner = NULL", file=d.err)
    rows = [
        DocRow(
            doc_id=doc.fm.doc_id, version=doc.fm.version, title=doc.fm.title, request_type=doc.fm.request_type,
            doc_type=doc.fm.doc_type, owner=doc.fm.owner if doc.fm.owner in known else None,
            updated_at=doc.fm.updated_at, sensitivity=doc.fm.sensitivity, enabled=doc.fm.enabled,
            distractor=doc.fm.distractor, content_sha256=doc.content_sha256,
            kb_version=v if doc.fm.enabled else None,
        )
        for doc in docs
    ]  # fmt: skip
    await d.repo.write_version(
        v, doc_count=int(report["doc_count"]), chunk_count=int(report["chunk_count"]), recall=report["recall_at5"],
        fg=report["false_grounding_rate"], eval_status=str(report["eval_status"]), docs=rows,
    )  # fmt: skip


async def _backfill(run: _Run, docs: list[Doc], enabled: list[Doc], v: str, meta: dict[str, Any]) -> int:
    name = f"kb_{v}"
    missing = [k for k in GATE_KEYS if k not in meta]
    if missing:
        return run.fail(f"không ghi bù được: metadata collection {name} thiếu {', '.join(missing)}")
    try:
        await _write_db(run, docs, v, meta)
    except SQLAlchemyError as e:
        return run.fail(_backfill_hint(name, e), code=2)
    run.say(f"đã ghi bù DB cho {name} (số đo lấy từ metadata collection)")
    return 0


async def _cleanup(d: IngestDeps, current: str) -> list[str]:
    """Giữ đích alias + `keep_old` bản mới nhất theo `kb_versions.created_at` (không có dòng DB = cũ nhất)."""
    order = await d.repo.created_order()
    oldest = datetime.min.replace(tzinfo=UTC)
    others = [c for c in await d.index.list_kb_collections() if c != current]
    others.sort(key=lambda c: order.get(c.removeprefix("kb_"), oldest), reverse=True)
    dropped = others[d.keep_old :]
    for c in dropped:
        await d.index.drop(c)
    return dropped


def _gate_line(branch: str, new: GateMetrics | None, old: GateMetrics | None) -> str:
    if new is None:
        return f"cổng kiểm (nhánh {branch}): không có bộ kiểm tra — eval_status=unevaluated, số đo NULL"
    line = (
        f"cổng kiểm (nhánh {branch}, dense-only): Recall@5 {new.recall_at5:.3f}, trả lời bừa "
        f"{new.false_grounding_rate:.3f}, MRR {new.mrr:.3f}; câu có đáp án {new.positives}, câu âm tính {new.negatives}"
    )
    if old is not None:
        line += (
            f"; bản đang chạy: Recall@5 {old.recall_at5:.3f} (đổi {new.recall_at5 - old.recall_at5:+.3f}), "
            f"trả lời bừa {old.false_grounding_rate:.3f} "
            f"(đổi {new.false_grounding_rate - old.false_grounding_rate:+.3f})"
        )
    return line
