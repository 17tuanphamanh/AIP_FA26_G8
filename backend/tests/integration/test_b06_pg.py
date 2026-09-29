"""f17 (thiết kế Phase 3 mục 9.6; PLAN-3f mục 3) — round-trip checkpoint Postgres THẬT sau B6: `diagnostics` (JSON, không
model Pydantic — không thêm vào `STATE_TYPES`), `facts`, `slots`, `ctx_flags` đọc lại từ `AsyncPostgresSaver` bằng đúng giá
trị lượt vừa ghi. Graph `nodes="real"`: B1 → B2 (L4 ScriptedLLM) → B3 (ScriptedLLM `vpn_scripts`) → B6 (VPN giả đọc seed)
→ B8 (RAG giả) → node giả phía sau. Câu có `LAP-0342` → B6 tra theo máy: có thiết bị (datetime → chuỗi ISO) + cert/kết nối
404 (None) cho người gửi `nv-graph` (không có trong seed).
"""

import json
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from app.core.clock import FakeClock
from app.domain.facts import FACT_KEYS
from app.domain.ticket_state import ChunkRef
from app.llm.providers.scripted import Reply
from app.rag.models import RetrievalResult
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts
from tests.integration.graph_pg import (
    SESSION,
    create_ticket,
    open_pg_runtime,
    seed_users,
)
from tests.integration.pg import PgUrls

pytestmark = pytest.mark.asyncio

TEXT = "VPN không vào được, báo lỗi 809 trên máy LAP-0342"
NOT_ATTACK = {"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ VPN bình thường"}


@pytest_asyncio.fixture
async def arw(migrated: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(migrated.role("app_rw"))
    await seed_users(engine)
    yield engine
    await engine.dispose()


def _rag() -> FakeRag:
    chunk = ChunkRef(chunk_id="c1", doc_id="KB-VPN-001", version=1, seq=0, title="T", heading_path="H",
                     score=0.99, excerpt="x")  # fmt: skip
    return FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.99, kb_version="a" * 64,
                                          intent_filter_fallback=False, fallback_tried=False, retries=0,
                                          query_truncated=False))  # fmt: skip


async def test_f17_checkpoint_roundtrip_after_b6_pg(migrated: PgUrls, arw: AsyncEngine) -> None:
    ticket_id = f"b6-{uuid4().hex[:12]}"
    await create_ticket(arw, ticket_id)
    clock = FakeClock()
    llm = make_gateway({"b02_injection_judge": [Reply(NOT_ATTACK)], "b03_classify": vpn_scripts()["b03_classify"]},
                       clock=clock).client  # fmt: skip
    async with open_pg_runtime(migrated.role("app_rw"), clock=clock, llm=llm, rag=_rag(), nodes="real") as rt:
        result = await rt.runner.submit(ticket_id, session_id=SESSION, redacted_request=TEXT)
    async with open_pg_runtime(migrated.role("app_rw"), clock=clock, nodes="real") as rt:  # process mới
        reread = (await rt.runner.snapshot(ticket_id)).values
    written = result.values
    diag = written["diagnostics"]
    assert diag["check_device_registered"][0]["device_id"] == "LAP-0342"
    assert isinstance(diag["check_device_registered"][0]["registered_at"], str)  # datetime → ISO (JSON)
    assert diag["check_vpn_cert_expiry"] is None and diag["check_last_connection"] is None  # 404 = dữ liệu
    json.dumps(diag)
    assert written["facts"] == {"device_registered": True, "device_owner_is_requester": False, "cert_status": "none"}
    assert set(written["facts"]) <= FACT_KEYS
    for key in ("diagnostics", "facts", "slots", "ctx_flags", "tool_retry_count", "rediagnose", "intent", "span"):
        assert reread[key] == written[key], key
