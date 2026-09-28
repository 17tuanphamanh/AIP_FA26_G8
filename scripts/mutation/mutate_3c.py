"""Mutation chặng 3c (RAG truy hồi B8–B9): áp từng đột biến, chạy test, KHÔI PHỤC, so md5; in test đỏ của mỗi
đột biến. Khuôn `mutate_3b.py` — không đọc `.env`, mã thoát 1 nếu có đột biến sống hoặc không áp được. File
luôn được khôi phục trong `finally`, cuối cùng so md5 và `git diff --stat` với lúc đầu.

Chạy từ gốc repo:
  uv run python scripts/mutation/mutate_3c.py                  # M-3c-1…6, 10…12 (sandbox, không Docker)
  uv run python scripts/mutation/mutate_3c.py --integration    # M-3c-1(c7), 2(c8), 7, 8, 9, 12(c19) — cần Docker
  uv run python scripts/mutation/mutate_3c.py --only "M-3c-1"  # chỉ đột biến có tên bắt đầu bằng tiền tố

Lệch với PLAN-3c mục 8 (ghi PROGRESS S11, không tự âm thầm sửa bảng plan): M-3c-7, M-3c-8, M-3c-9 KHÔNG có
phần unit — test duy nhất phủ chúng (c16, c12, c14) chỉ tồn tại ở `integration/test_rag_query_qdrant.py` (Q,
cần Qdrant thật) nên cả 3 mã này chỉ nằm trong `INTEGRATION`, không nằm trong lượt sandbox mặc định — PLAN
mục 9 (S11) ghi "chạy phần U (M-3c-1…6, 8…12 phần unit)" nhưng thực tế chỉ 1,2,3,4,5,6,10,11,12 có phần unit.
M-3c-6 (c17): mã đúng Ý "Retriever bọc thêm quanh ml.embed" nhưng số lời gọi `embed` thực tế đo được KHÔNG
phải 9 như PLAN ghi — với `fail_next("embed","http_500",2)` của c17, muốn khớp đúng "gọi lại 3 lần đều tốn 3
lượt" cần hàng đợi lỗi được nạp lại mỗi lượt gọi lại, điều `FakeMlService.fail_next` không mô phỏng (hàng đợi
hữu hạn, dùng hết là hết) — bất kỳ đột biến "bọc lại gọi ml.embed" hợp lý nào cũng chỉ tạo ra số khác 3 (đã đo
là 4), đủ để c17 đỏ đúng lý do (số lần gọi lệch dự kiến), không nhất thiết đúng con số 9 trong plan.
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


RETRIEVER = "backend/app/rag/retriever.py"
EXPAND = "backend/app/rag/expand.py"
FILTERS = "backend/app/rag/filters.py"
B08 = "backend/app/graph/nodes/b08_retrieve.py"
GOTO = "backend/app/graph/goto.py"
UT_RETRIEVER = "backend/tests/unit/test_rag_retriever.py"
UT_FILTERS = "backend/tests/unit/test_rag_filters.py"
UT_B08 = "backend/tests/unit/test_b08_retrieve.py"
UT_GOTO = "backend/tests/unit/test_graph_goto.py"
IT_QUERY = "backend/tests/integration/test_rag_query_qdrant.py"
IT_B08 = "backend/tests/integration/test_b08_pg.py"

M1_OLD = (
    "        extra = [intent_filter(q.intent)] if use_intent and q.intent is not None else []\n"
    "        flt = query_filter(role, *extra)\n"
)  # fmt: skip
M1_NEW = (
    "        extra = [intent_filter(q.intent)] if use_intent and q.intent is not None else []\n"
    "        from qdrant_client.models import FieldCondition, Filter, MatchValue  # MUTATION\n"
    '        flt = Filter(must=[FieldCondition(key="enabled", match=MatchValue(value=True))])\n'
)  # fmt: skip

M2_OLD = (
    "                flt = query_filter(\n"
    "                    ctx.role,\n"
    '                    FieldCondition(key="doc_id", match=MatchValue(value=c.doc_id)),\n'
    '                    FieldCondition(key="seq", range=Range(gte=c.seq - w, lte=c.seq + w)),\n'
    "                )\n"
)  # fmt: skip
M2_NEW = (
    "                from qdrant_client.models import Filter  # MUTATION bỏ base_filter\n"
    "                flt = Filter(must=[\n"
    '                    FieldCondition(key="doc_id", match=MatchValue(value=c.doc_id)),\n'
    '                    FieldCondition(key="seq", range=Range(gte=c.seq - w, lte=c.seq + w)),\n'
    "                ])\n"
)  # fmt: skip

M7_OLD = "                return first.finish(kb_version, fallback=False, tried=False, retries=retries.total)\n"
M7_NEW = (
    "                if collection is None:  # MUTATION đọc lại alias sau truy vấn\n"
    "                    reread = await self._call(self._index.alias_target, ALIAS, retries=retries)\n"
    "                    if reread is not None:\n"
    '                        kb_version = reread.removeprefix("kb_")\n'
    "                return first.finish(kb_version, fallback=False, tried=False, retries=retries.total)\n"
)  # fmt: skip

M8_OLD = (
    "                    if coll is None:\n"
    '                        raise RetrievalSystemError("alias", retries.total)\n'
)  # fmt: skip
M8_NEW = (
    "                    if coll is None:\n"
    "                        return RetrievalResult(  # MUTATION nuốt lỗi alias — trả rỗng thay vì raise\n"
    "                            chunks=[], top_score=0.0, kb_version=\"\", intent_filter_fallback=False,\n"
    "                            fallback_tried=False, retries=retries.total, query_truncated=False,\n"
    "                        )\n"
)  # fmt: skip

M9_OLD = (
    "        if not hits:  # RỖNG ≠ LỖI → không gọi rerank, B9 xử lý E3\n"
    "            return _Partial(chunks=[], top_score=0.0, query_truncated=False)\n"
)  # fmt: skip
M9_NEW = (
    "        if False:  # MUTATION hit rỗng vẫn gọi rerank\n"
    "            return _Partial(chunks=[], top_score=0.0, query_truncated=False)\n"
)  # fmt: skip

UNIT = [
    ("M-3c-1 D-23 dùng Filter(enabled) thay query_filter(role) [unit]", RETRIEVER, M1_OLD, M1_NEW,
     pt(f"{UT_RETRIEVER}::test_c27_every_filter_has_enabled_and_sensitivity_and_intent_only_on_first_try",
        f"{UT_FILTERS}::test_filter_constructor_called_only_in_filters_py"),
     ["test_c27_every_filter_has_enabled_and_sensitivity_and_intent_only_on_first_try",
      "test_filter_constructor_called_only_in_filters_py"]),
    ("M-3c-2 expand dựng Filter không có base_filter [unit]", EXPAND, M2_OLD, M2_NEW,
     pt(f"{UT_RETRIEVER}::test_c27_expand_filter_uses_role_sensitivity_and_doc_scope",
        f"{UT_FILTERS}::test_filter_constructor_called_only_in_filters_py"),
     ["test_c27_expand_filter_uses_role_sensitivity_and_doc_scope",
      "test_filter_constructor_called_only_in_filters_py"]),
    ("M-3c-3 allowed_sensitivity role lạ → cả 3 mức", FILTERS,
     '    return list(_ALLOWED.get(role, ["public"]))\n',
     '    return list(_ALLOWED.get(role, ["public", "internal", "restricted"]))  # MUTATION\n',
     pt(f"{UT_FILTERS}::test_unknown_role_gets_least"), ["test_unknown_role_gets_least"]),
    ("M-3c-4 B9 < → <=", B08,
     "        if not res.chunks or res.top_score < deps.constants.RETRIEVAL_THRESHOLD:  # B9\n",
     "        if not res.chunks or res.top_score <= deps.constants.RETRIEVAL_THRESHOLD:  # B9 MUTATION\n",
     pt(f"{UT_B08}::test_c15_node_top_score_equal_threshold_routes_to_b10"),
     ["test_c15_node_top_score_equal_threshold_routes_to_b10"]),
    ("M-3c-5 lỗi D-23 bị nuốt, trả first", RETRIEVER,
     ('                if first.top_score < self._threshold and q.intent and self._cfg.intent_fallback:'
      '  # D-23\n                    alt = await self._search(\n'
      '                        coll, q, ctx.role, use_intent=False, dense=dense, sparse=sparse,\n'
      '                        retries=retries, kb_version=kb_version, stage=stage,\n'
      '                    )  # fmt: skip\n                    if alt.top_score >= self._threshold:\n'),
     ('                if first.top_score < self._threshold and q.intent and self._cfg.intent_fallback:'
      '  # D-23\n                    try:  # MUTATION nuốt lỗi D-23\n'
      '                        alt = await self._search(\n'
      '                            coll, q, ctx.role, use_intent=False, dense=dense, sparse=sparse,\n'
      '                            retries=retries, kb_version=kb_version, stage=stage,\n'
      '                        )  # fmt: skip\n                    except RetrievalSystemError:\n'
      '                        alt = first\n                    if alt.top_score >= self._threshold:\n'),
     pt(f"{UT_RETRIEVER}::test_c11_first_search_empty_then_fallback_rerank_fails"),
     ["test_c11_first_search_empty_then_fallback_rerank_fails"]),
    ("M-3c-6 Retriever bọc thêm quanh ml.embed", RETRIEVER,
     ('    async def _embed(self, q: RetrievalQuery, retries: _Counter, kb_version: str) '
      '-> tuple[list[float], Any]:\n        emb = await self._ml.embed([q.text])\n'
      '        retries.add(emb.attempts, failed=emb.error is not None)\n'),
     ('    async def _embed(self, q: RetrievalQuery, retries: _Counter, kb_version: str) '
      '-> tuple[list[float], Any]:\n        for _ in range(3):  # MUTATION bọc thêm quanh ml.embed\n'
      '            emb = await self._ml.embed([q.text])\n            if emb.attempts == 0:\n'
      '                break\n        retries.add(emb.attempts, failed=emb.error is not None)\n'),
     pt(f"{UT_RETRIEVER}::test_c17_embed_retries_inside_single_ml_call"),
     ["test_c17_embed_retries_inside_single_ml_call"]),
    ("M-3c-10 bỏ kiểm pipeline_sha", RETRIEVER,
     ('                if meta.get("pipeline_sha") != self._pipeline_sha:\n'
      '                    raise RetrievalSystemError("pipeline", retries.total, kb_version=kb_version)\n'),
     ('                if False:  # MUTATION bỏ kiểm pipeline_sha\n'
      '                    raise RetrievalSystemError("pipeline", retries.total, kb_version=kb_version)\n'),
     pt(f"{UT_RETRIEVER}::test_c23_pipeline_sha_mismatch_before_any_ml_call"),
     ["test_c23_pipeline_sha_mismatch_before_any_ml_call"]),
    ("M-3c-11 retries cộng attempts cả khi lỗi", RETRIEVER,
     "        self.total += attempt if not failed else max(0, attempt - 1)\n",
     "        self.total += attempt  # MUTATION cộng cả khi lỗi\n",
     pt(f"{UT_RETRIEVER}::test_c13_unreachable_qdrant_gives_search_stage_with_two_retries"),
     ["test_c13_unreachable_qdrant_gives_search_stage_with_two_retries"]),
    ("M-3c-12 bỏ kb_version khỏi _SAME_NAME_COLUMNS [unit]", GOTO,
     ('_SAME_NAME_COLUMNS = frozenset({\n'
      '    "intended_action", "exit_code", "block_reason", "close_reason", "intent",\n'
      '    "approval_result", "action_plan_hash", "approver_id", "note", "kb_version",\n'
      '})  # fmt: skip\n'),
     ('_SAME_NAME_COLUMNS = frozenset({\n'
      '    "intended_action", "exit_code", "block_reason", "close_reason", "intent",\n'
      '    "approval_result", "action_plan_hash", "approver_id", "note",  # MUTATION bỏ kb_version\n'
      '})  # fmt: skip\n'),
     pt(f"{UT_GOTO}::test_goto_copies_kb_version_to_audit_column"),
     ["test_goto_copies_kb_version_to_audit_column"]),
]

INTEGRATION = [
    ("M-3c-1 D-23 dùng Filter(enabled) thay query_filter(role) [c7]", RETRIEVER, M1_OLD, M1_NEW,
     pt(f"{IT_QUERY}::test_c7_account_intent_fallback_still_hides_restricted_from_employee"),
     ["test_c7_account_intent_fallback_still_hides_restricted_from_employee"]),
    ("M-3c-2 expand dựng Filter không có base_filter [c8]", EXPAND, M2_OLD, M2_NEW,
     pt(f"{IT_QUERY}::test_c8_expand_respects_permission_within_neighbor_window"),
     ["test_c8_expand_respects_permission_within_neighbor_window"]),
    ("M-3c-7 kb_version đọc lại alias sau truy vấn", RETRIEVER, M7_OLD, M7_NEW,
     pt(f"{IT_QUERY}::test_c16_alias_switch_mid_query_pins_old_kb_version"),
     ["test_c16_alias_switch_mid_query_pins_old_kb_version"]),
    ("M-3c-8 alias thiếu → trả kết quả rỗng", RETRIEVER, M8_OLD, M8_NEW,
     pt(f"{IT_QUERY}::test_c12_no_alias_raises_stage_alias_no_ml_calls"),
     ["test_c12_no_alias_raises_stage_alias_no_ml_calls"]),
    ("M-3c-9 hit rỗng vẫn gọi rerank", RETRIEVER, M9_OLD, M9_NEW,
     pt(f"{IT_QUERY}::test_c14_empty_collection_gives_e3_no_rerank_call"),
     ["test_c14_empty_collection_gives_e3_no_rerank_call"]),
    ("M-3c-12 bỏ kb_version khỏi _SAME_NAME_COLUMNS [c19]", GOTO,
     ('_SAME_NAME_COLUMNS = frozenset({\n'
      '    "intended_action", "exit_code", "block_reason", "close_reason", "intent",\n'
      '    "approval_result", "action_plan_hash", "approver_id", "note", "kb_version",\n'
      '})  # fmt: skip\n'),
     ('_SAME_NAME_COLUMNS = frozenset({\n'
      '    "intended_action", "exit_code", "block_reason", "close_reason", "intent",\n'
      '    "approval_result", "action_plan_hash", "approver_id", "note",  # MUTATION bỏ kb_version\n'
      '})  # fmt: skip\n'),
     pt(f"{IT_B08}::test_c19_checkpoint_and_audit_match_retriever_result"),
     ["test_c19_checkpoint_and_audit_match_retriever_result"]),
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
