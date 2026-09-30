"""Node B8–B9 thật trên Qdrant + Postgres 16 thật (thiết kế Phase 3 mục 6.8; PLAN-3c mục 7 — c5, c19).

c5: node b08 → b10 + `Retriever` thật + `MemoryAudit` (không cần runtime graph đầy đủ) — câu hỏi dùng câu MFA đã mô
phỏng ở S2 (PROGRESS, phương án A, mục "Câu c5"), KHÔNG dùng nguyên văn câu của PLAN gốc ("đăng ký MFA thế
nào?") vì câu đó ra điểm CHẠM ngưỡng khi mô phỏng — đã ghi rõ trong PROGRESS, không tự đoán lại ở đây. Phase 4 S0-P1/P2:
B8 không còn nhánh B9 — B9 chạy trong `b10_route` sau `b10_need_type` (preset `info`); kỳ vọng E3 `no_grounding` GIỮ NGUYÊN.
S0-P10: `Retriever.procedure_available` trên Qdrant thật (lọc quyền, alias hiện hành).

c19: `graph_pg.open_pg_runtime(nodes="real")` — B1–B7 vẫn là node THẬT có sẵn từ trước 3c (chỉ B8 đổi từ giả
sang thật ở chặng này; từ 3e B2 cũng thật → ScriptedLLM trả `is_attack=false` cho L4); B3 (`b03_classify`) hiện còn ở dạng "Phase 2a" — CỐ ĐỊNH `intent="vpn"`, không đọc
nội dung câu — nên không cần câu hỏi đặc biệt để "lọt" phân loại. Ticket đi đường MẶC ĐỊNH (không gắn thẻ
FakeScenario) qua B1→…→B6→B8 thật.
"""

from collections.abc import AsyncIterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.clock import FakeClock
from app.domain.context import RequesterContext
from app.domain.states import S_ESCALATED, S_RETRIEVING
from app.graph.context import RunContext, bind_run
from app.graph.nodes import b08_retrieve, b10_route
from app.llm.providers.scripted import Reply
from app.rag.bm25 import load_lexicon
from app.rag.ingest.config import ALIAS
from app.rag.ingest.kbversion import pipeline_sha
from app.rag.retriever import RagConfig, Retriever
from app.settings import Settings, get_policy
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.executor import MemoryTxLog
from tests.fakes.graph import GraphHarness, MemoryAudit, MemoryEffects, MemorySpans
from tests.fakes.kb import CONFIG_DIR, KB_TEST_NOW, copy_kb
from tests.fakes.llm import make_gateway
from tests.fixtures.llm.vpn import vpn_scripts
from tests.integration.graph_pg import (
    SESSION,
    create_ticket,
    open_pg_runtime,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls
from tests.integration.test_rag_ingest_pg import Env, _env

pytestmark = pytest.mark.asyncio

MFA_QUESTION = "Làm sao bật xác thực 2 lớp MFA cho email?"  # S2 (PROGRESS) — mọi tổ hợp role/intent < T rõ
VPN_QUESTION = "VPN công ty dùng cổng nào?"  # c4 — top-1 KB-VPN-001 rõ ràng ≥ T


def _ctx(role: str) -> RequesterContext:
    return RequesterContext(
        user_id="u1", role=role, department="it", manager_id=None, employment_status="active",
        tenure_days=10, is_privileged_account=False, captured_at=KB_TEST_NOW,
    )  # fmt: skip


async def _retriever(env: Env) -> Retriever:
    lexicon = load_lexicon(CONFIG_DIR)
    return Retriever(
        env.index, env.fake.client(), RagConfig.from_settings(Settings(_env_file=None)),
        threshold=get_policy().constants.RETRIEVAL_THRESHOLD, pipeline_sha=pipeline_sha(CONFIG_DIR),
        lexicon=lexicon, clock=FakeClock(),
    )  # fmt: skip


@pytest_asyncio.fixture
async def kb_env(clean_qdrant: str, migrated: PgUrls, tmp_path: Path) -> AsyncIterator[Env]:
    """Fixture KB ingest thật (không cổng kiểm — with_eval=False, việc của test_rag_ingest_pg.py/c37)."""
    async with _env(clean_qdrant, migrated) as e:
        kb_dir = copy_kb(tmp_path, with_eval=False)
        r = await e.run(kb_dir, allow_unevaluated=True)
        assert r.code == 0, r.err
        yield e


# ---- c5: node b08 + Retriever thật + MemoryAudit ---------------------------------------------------


@contextmanager
def _run_ctx(audit: MemoryAudit) -> Any:
    ctx = RunContext(
        turn_id="T1", trace_id="0" * 32, audit=audit, effects=MemoryEffects(), spans=MemorySpans(),
        clock=FakeClock(), txlog=MemoryTxLog(),
    )  # fmt: skip
    with bind_run(ctx):
        yield ctx


async def test_c5_mfa_question_gives_e3_no_grounding(kb_env: Env) -> None:
    retriever = await _retriever(kb_env)
    h = GraphHarness(llm=make_gateway({"b10_need_type": vpn_scripts(need="info")["b10_need_type"]}).client)
    h.rag = retriever  # type: ignore[assignment]
    deps = h.deps()
    audit = MemoryAudit()
    state: dict[str, Any] = {
        "ticket_id": "t1", "turn_id": "T1", "status": S_RETRIEVING, "redacted_request": MFA_QUESTION,
        "intent": "vpn", "slots": {}, "requester_context": _ctx("employee"),
    }  # fmt: skip
    with _run_ctx(audit):
        out = await b08_retrieve.make(deps)(state)
        assert (out["status"], out["next"]) == (S_RETRIEVING, "b10_route")  # S0-P1: B8 luôn đi tiếp
        out = await b10_route.make(deps)({**state, **out})
    assert (out["status"], out["exit_code"]) == (S_ESCALATED, "E3")
    assert out["escalation_reason_detail"] == "no_grounding"
    assert audit.events("t1") == [("B8", "retrieved"), ("B9", "no_evidence")]


@pytest.mark.parametrize(
    ("doc", "role", "ok"),
    [("KB-VPN-004", "employee", True), ("KB-VPN-001", "employee", True), ("KB-VPN-002", "employee", False),
     ("KB-VPN-007", "employee", False), ("KB-VPN-007", "l1", True), ("KB-VPN-009", "manager", False)],
    ids=["co", "public", "tat", "restricted-employee", "restricted-l1", "khong-co"],
)  # fmt: skip
async def test_s0_procedure_available_on_real_qdrant(kb_env: Env, doc: str, role: str, ok: bool) -> None:
    """S0-P10 + S0-A3 trên Qdrant THẬT: `procedure_filter` (base_filter + doc_id) đúng ngữ nghĩa Qdrant (SpyIndex chỉ mô phỏng),
    `kb_version` = collection mà alias đang trỏ."""
    retriever = await _retriever(kb_env)
    check = await retriever.procedure_available(doc, _ctx(role))
    assert check.available is ok
    assert f"kb_{check.kb_version}" == await kb_env.index.alias_target(ALIAS)


# ---- c19: graph thật (Postgres checkpoint + audit_logs) ---------------------------------------------


@pytest_asyncio.fixture
async def arw(migrated: PgUrls) -> AsyncIterator[AsyncEngine]:
    """Engine ASYNC role `app_rw` cho phần đồ thị (khác `rw` sync của conftest — `graph_pg` cần async)."""
    engine = create_async_engine(migrated.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ VPN bình thường"}


async def test_c19_checkpoint_and_audit_match_retriever_result(
    migrated: PgUrls, arw: AsyncEngine, kb_env: Env
) -> None:
    retriever = await _retriever(kb_env)
    ticket_id = f"b8-{uuid4().hex[:12]}"
    await create_ticket(arw, ticket_id)
    clock = FakeClock()
    # 3e: B2 cũng là node thật — L3 model_missing → L4 `b02_injection_judge` (ScriptedLLM: không phải tấn công)
    # 3f: B3 thật — kịch bản b03_classify VPN chuẩn; B6 thật trên VPN giả (graph_pg)
    llm = make_gateway({"b02_injection_judge": [Reply(NOT_ATTACK)], "b03_classify": vpn_scripts()["b03_classify"],
                       "b10_need_type": vpn_scripts()["b10_need_type"]},  # 3g: B10 thật — action → B11 như trước
                       clock=clock).client  # fmt: skip
    async with open_pg_runtime(migrated.role("app_rw"), clock=clock, rag=retriever, llm=llm, nodes="real") as rt:
        result = await rt.runner.submit(ticket_id, session_id=SESSION, redacted_request=VPN_QUESTION)
        reread = await rt.runner.snapshot(ticket_id)  # đọc lại checkpoint (không phải giá trị vừa trả về)
    assert result.values["retrieved"], "câu VPN rõ ràng — phải có chunk trả về, không escalate ở B8/B9"
    assert reread.values["retrieved"] == result.values["retrieved"]
    assert reread.values["kb_version"] == result.values["kb_version"]
    assert reread.values["intent_filter_fallback"] == result.values["intent_filter_fallback"]
    kb_version_col = await scalar(
        arw, "SELECT kb_version FROM audit_logs WHERE ticket_id=:t AND step='B8'", t=ticket_id
    )
    assert kb_version_col == result.values["kb_version"]
