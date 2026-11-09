"""B15 THẬT trên Postgres 16 thật — Phase 4 chặng 4b DỪNG 2 (PLAN-4b S11). Viết TỪ ĐẶC TẢ, trước code: phase4 mục 5.1 P5, P8, P10,
5.3 b3/b8, 5.6 #4 (Q-4b-4), 3.2 x2 (TC19) + b2 (route dùng cùng hàm xung đột).

- b3 PG: bảng `users` KHÔNG có dòng nào của roster (DB mới cho mỗi test) → node B15 thật qua `rt.deps` trên store SQL (FK thật
  `approvals.approver_id/backup_approver_id`, `audit_logs.approver_id` → `users`) → phiếu tạo được; `users` có người duyệt + chuỗi
  quản lý + dự phòng; số dòng `sessions` không đổi.
- b8 PG: dòng audit B15 `queued` — cột `approver_id, deadline, conflict_detected, action_plan_hash` không NULL; `intended_action` JSONB
  có `type` + `target`; `detail` đúng khoá P10.
- x14 + x14b PG (bổ sung sau soát S14 — agent chính viết, không phải test-writer): chạy lại sau khi chết tại `after_approval_create`
  qua `SqlEffectStore.peek` THẬT — phiếu cũ, 1 phiếu, 1 lần báo `l1_01`, 0 lời gọi AD.
- Route + B15 THẬT (cần CẢ HAI): `ha.lt` (l1_01) xin gia hạn PC-0124 của mình (chưa đăng ký, R17) → B15 giao `it_mgr01` (self → Trưởng
  BP) → `ha.lt` quyết → 403; `quan.tm` quyết → 202. Danh bạ (AD của B1/B15 + IdP đăng nhập) dựng từ `mock_services/seed.json`
  (`tests/fakes/ad_seed.py`, chuỗi P14 l1_01 → l1_lead → it_mgr01) — KHÔNG dùng `tests/fakes/auth.seed_ad_users` (cố ý lệch seed).
Database riêng cho MỖI test: `audit_logs`/`security_events` append-only, và b3 cần bảng `users` chưa có roster.
"""

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import uuid4

import httpx
import pyotp
import pytest
import pytest_asyncio
from alembic import command
from app.audit.security_events import SecurityEventWriter
from app.audit.writer import AuditWriter
from app.auth.mfa import MfaCipher, enroll
from app.auth.store import SqlAuthStore
from app.core.clock import FakeClock
from app.core.hashing import hash_action
from app.db.runtime import SqlEffectStore, SqlSpanSink
from app.domain.action import Action
from app.domain.context import RequesterContext
from app.domain.states import S_ASSESSING, S_PENDING_APPROVAL
from app.domain.ticket_state import ChunkRef
from app.graph.context import RunContext, bind_run
from app.graph.fakes import fake_risk
from app.graph.nodes import b15_prepare_approval
from app.main import create_app
from app.rag.models import RetrievalResult
from app.settings import Settings, get_action_metadata
from app.tools.models import AdUser
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from tests.fakes.ad_seed import seed_ad_records
from tests.fakes.auth import DEMO_PASSWORD, EPOCH, FakeAdUser, FakeIdentityProvider
from tests.fakes.desk import MaskingGuard
from tests.fakes.identity import FakeAd
from tests.fakes.llm import make_gateway
from tests.fakes.rag import FakeRag
from tests.fixtures.llm.vpn import vpn_scripts
from tests.integration.graph_pg import (
    REQUESTER,
    PgRuntime,
    create_ticket,
    open_pg_runtime,
    pg_runtime_factory,
    scalar,
    seed_users,
)
from tests.integration.pg import PgUrls, alembic_config, fresh_database
from tests.unit.auth_helpers import BASE_URL, auth_settings

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)
ROSTER_ROWS = ("it_mgr01", "l1_01", "l1_02", "l1_lead")
POINT5_DETAIL = {"backup_approver_id", "conflict_type", "choice_reason", "rejected_candidates", "sla_minutes", "recovered"}


@pytest.fixture
def db(pg: PgUrls) -> Iterator[PgUrls]:
    with fresh_database(pg) as fresh:
        command.upgrade(alembic_config(fresh), "head")
        yield fresh


@pytest_asyncio.fixture
async def rw(db: PgUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db.role("app_rw"))
    await seed_users(engine)  # người gửi `nv-graph` + phiên của họ (đối chứng số dòng `sessions`), người duyệt GIẢ `l1-fake`
    yield engine
    await engine.dispose()


async def _rows(rw: AsyncEngine, sql: str, **params: Any) -> list[tuple[Any, ...]]:
    async with rw.connect() as conn:
        return [tuple(r) for r in (await conn.execute(text(sql), params)).all()]


def _action(requested_for: str) -> Action:
    m = get_action_metadata().of("vpn")["renew_vpn_cert"]
    return Action(
        type="renew_vpn_cert", target="device:PC-9001", requested_for=requested_for, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": "PC-9001"},
        facts={"device_registered": True, "device_owner_is_requester": True},
    )  # fmt: skip


async def _run_b15(
    rt: PgRuntime, clock: FakeClock, ticket: str, *, turn_id: str | None = None
) -> tuple[Action, dict[str, Any]]:
    """Node B15 THẬT qua `rt.deps` (store SQL) trong RunContext SQL — như runner dựng (`effects` + `audit` cùng DB). `turn_id` cố
    định = chạy lại CÙNG lượt (recover giữ `turn_id` — cùng `effect_key`)."""
    rc = RequesterContext.from_ad(AdUser.model_validate(rt.ad.users[REQUESTER]), clock.now())
    action = _action(REQUESTER)
    state: dict[str, Any] = {
        "ticket_id": ticket, "turn_id": turn_id or f"turn-{uuid4().hex[:8]}", "status": S_ASSESSING, "intent": "vpn",
        "reasoning_loops": 1, "requester_context": rc, "intended_action": action, "ctx_flags": {"target_is_other": False},
        "slots": {"device_id": "PC-9001", "action": "renew_vpn_cert"}, "risk": fake_risk("HITL"),
        "redacted_request": "gia hạn VPN cho máy PC-9001",
    }  # fmt: skip
    engine = rt.engines.main
    run = RunContext(turn_id=state["turn_id"], trace_id="0" * 32, audit=AuditWriter(engine), effects=SqlEffectStore(engine),
                     spans=SqlSpanSink(engine), clock=clock, txlog=rt.deps.txlog)  # fmt: skip
    fn = b15_prepare_approval.make(rt.deps)
    with bind_run(run):
        out = cast(dict[str, Any], await fn(state))
    return action, out


# ---- b3 PG ------------------------------------------------------------------------------------------------------------------


async def test_b3_pg_approver_without_users_row_gets_row_and_chain_no_session(db: PgUrls, rw: AsyncEngine) -> None:
    """b3 (Q-4-N, P5, M-4b-12): chưa ai trong roster có dòng `users` → B15 thật `ensure` TRƯỚC khi tạo phiếu → FK thật qua; `users`
    có l1_01 (→ l1_lead → it_mgr01) + dự phòng l1_02; KHÔNG dòng `sessions` mới."""
    clock = FakeClock(NOW)
    ticket = f"tk-{uuid4().hex[:8]}"
    await create_ticket(rw, ticket, created_at=clock.now())
    in_roster = "SELECT count(*) FROM users WHERE user_id IN ('it_mgr01', 'l1_01', 'l1_02', 'l1_lead')"
    assert await scalar(rw, in_roster) == 0
    sessions = await scalar(rw, "SELECT count(*) FROM sessions")
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        _, out = await _run_b15(rt, clock, ticket)
    assert out["status"] == S_PENDING_APPROVAL
    [approval] = await _rows(rw, "SELECT approver_id, backup_approver_id, conflict_detected, conflict_type FROM approvals "
                                 "WHERE ticket_id = :t", t=ticket)  # fmt: skip
    assert approval == ("l1_01", "l1_02", False, None)
    users = await _rows(rw, "SELECT user_id, role, manager_id FROM users "
                            "WHERE user_id IN ('it_mgr01', 'l1_01', 'l1_02', 'l1_lead') ORDER BY user_id")  # fmt: skip
    assert users == [("it_mgr01", "manager", None), ("l1_01", "l1", "l1_lead"), ("l1_02", "l1", "it_mgr01"),
                     ("l1_lead", "l1", "it_mgr01")]  # fmt: skip
    assert await scalar(rw, "SELECT count(*) FROM sessions") == sessions


# ---- b8 PG ------------------------------------------------------------------------------------------------------------------


async def test_b8_pg_point5_columns_and_intended_action_not_null(db: PgUrls, rw: AsyncEngine) -> None:
    """b8 (P10, Q-4b-4, M-4b-14): dòng `audit_logs` step B15 `queued` — cột điểm 5 không NULL, `action_plan_hash` = hash của Action,
    `intended_action` JSONB có `type` + `target`, `detail` đúng khoá P10 + `recovered`."""
    clock = FakeClock(NOW)
    ticket = f"tk-{uuid4().hex[:8]}"
    await create_ticket(rw, ticket, created_at=clock.now())
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        action, out = await _run_b15(rt, clock, ticket)
    assert out["status"] == S_PENDING_APPROVAL
    [row] = await _rows(
        rw, "SELECT approver_id, deadline, conflict_detected, action_plan_hash, intended_action->>'type', "
            "intended_action->>'target', detail FROM audit_logs WHERE ticket_id = :t AND step = 'B15' AND event = 'queued'",
        t=ticket,
    )  # fmt: skip
    approver, deadline, conflict, plan_hash, a_type, a_target, detail = row
    assert None not in (approver, deadline, conflict, plan_hash, a_type, a_target)
    assert (approver, conflict, plan_hash) == ("l1_01", False, hash_action(action))
    assert (a_type, a_target) == ("renew_vpn_cert", "device:PC-9001")
    assert set(detail) == POINT5_DETAIL
    assert (detail["choice_reason"], detail["recovered"], detail["rejected_candidates"]) == ("normal", False, [])


# ---- x14 + x14b PG: chạy lại sau khi chết tại `after_approval_create` — `SqlEffectStore.peek` thật (bổ sung sau soát S14) --------


class _Killed(Exception):
    """Process "chết" TẠI hook `after_approval_create`: phiếu + dòng `side_effects` đã commit, chưa báo người duyệt, chưa `goto`."""


def _kill(_: Any) -> None:
    raise _Killed


async def test_x14_x14b_pg_rerun_after_kill_old_approval_via_sql_peek_no_ad(db: PgUrls, rw: AsyncEngine) -> None:
    """x14 + x14b trên Postgres (P9, TC33, Q-4b-3): x14/x14b unit chạy trên `MemoryEffects`, TC33 PG (`test_graph_pg`) còn B15 GIẢ —
    đây là test duy nhất chạy `SqlEffectStore.peek` thật. Lần 1 tạo phiếu rồi chết tại hook; giữa hai lần chạy `l1_01` bị disabled VÀ
    AD sập; lần 2 (runtime mới, CÙNG `turn_id` + `reasoning_loops` như recover) → `S_PENDING_APPROVAL` với phiếu cũ, vẫn 1 phiếu,
    đúng 1 `notify_approver` cho `l1_01`, 0 lời gọi AD, audit `queued` `recovered=true`. Q3 M4: hook giết process TRƯỚC `queued()` →
    lần 1 chưa gửi tin nào; lần 2 gửi đúng 1 tin "chờ duyệt" (`once` sub `approval_pending`)."""
    clock = FakeClock(NOW)
    ticket, turn = f"tk-{uuid4().hex[:8]}", f"turn-{uuid4().hex[:8]}"
    await create_ticket(rw, ticket, created_at=clock.now())
    async with open_pg_runtime(db.role("app_rw"), clock=clock) as rt:
        rt.scenario.on(ticket, "after_approval_create", _kill)
        with pytest.raises(_Killed):
            await _run_b15(rt, clock, ticket, turn_id=turn)
        assert rt.approvals.notified == []
        ad = rt.ad
    [(aid, approver)] = await _rows(rw, "SELECT approval_id, approver_id FROM approvals WHERE ticket_id = :t", t=ticket)
    assert approver == "l1_01"
    ad.set_status("l1_01", "disabled")
    ad.down = True
    calls = ad.calls
    async with open_pg_runtime(db.role("app_rw"), clock=clock, ad=ad, roster_in_ad=False) as rt2:
        _, out = await _run_b15(rt2, clock, ticket, turn_id=turn)
        notified = list(rt2.approvals.notified)
    assert (out["status"], out["approval_id"], out.get("exit_code")) == (S_PENDING_APPROVAL, str(aid), None)
    assert ad.calls == calls
    assert await _rows(rw, "SELECT approval_id, approver_id, status FROM approvals WHERE ticket_id = :t", t=ticket) == [
        (aid, "l1_01", "pending")
    ]
    assert notified == [(str(aid), "l1_01")]
    assert await _rows(rw, "SELECT kind, count(*) FROM side_effects WHERE ticket_id = :t GROUP BY kind ORDER BY kind",
                       t=ticket) == [("approval_create", 1), ("notify_approver", 1), ("notify_user", 1)]  # fmt: skip
    [(q_approver, detail)] = await _rows(rw, "SELECT approver_id, detail FROM audit_logs WHERE ticket_id = :t AND step = 'B15' "
                                             "AND event = 'queued'", t=ticket)  # fmt: skip
    assert (q_approver, detail["recovered"], detail["rejected_candidates"], detail["choice_reason"]) == (
        "l1_01", True, None, "normal"
    )
    assert await _rows(rw, "SELECT event FROM audit_logs WHERE ticket_id = :t AND step = 'B15' AND event <> 'queued'",
                       t=ticket) == []  # fmt: skip


# ---- Route + B15 thật: TC19 (x2) — l1_01 tự gửi → Trưởng BP duyệt ---------------------------------------------------------


def _seed_people(now: datetime) -> tuple[list[dict[str, Any]], list[FakeAdUser]]:
    """Cùng MỘT danh bạ cho AD của graph (B1/B15/B17) và IdP của đăng nhập — đọc `mock_services/seed.json`."""
    records = seed_ad_records(now)
    people = [
        FakeAdUser(r["user_id"], r["username"], list(r["groups"]), r["manager_id"], department=r["department"],
                   full_name=r["full_name"], employment_status=r["employment_status"],
                   hired_at=date.fromisoformat(r["hired_at"]), is_privileged_account=r["is_privileged_account"])
        for r in records
    ]  # fmt: skip
    return records, people


def _rag() -> FakeRag:
    chunk = ChunkRef(chunk_id="c1", doc_id="KB-VPN-004", version=1, seq=0, title="T", heading_path="H",
                     score=0.99, excerpt="x")  # fmt: skip
    return FakeRag(result=RetrievalResult(chunks=[chunk], top_score=0.99, kb_version="a" * 64,
                                          intent_filter_fallback=False, fallback_tried=False, retries=0,
                                          query_truncated=False))  # fmt: skip


@dataclass
class Desk:
    app: FastAPI
    client: httpx.AsyncClient
    clock: FakeClock
    settings: Settings
    rw: AsyncEngine

    async def drain(self) -> None:
        await self.app.state.background.drain()

    async def headers(self, username: str) -> dict[str, str]:
        """Đăng nhập; manager bắt buộc MFA — lần đầu 401 (tạo dòng users), enroll qua đúng hàm CLI, đăng nhập kèm OTP (khuôn
        `test_approvals_route_chain._headers`, bản SQL)."""
        body = {"username": username, "password": DEMO_PASSWORD}
        r = await self.client.post("/api/auth/login", json=body)
        if r.status_code != 200:
            assert r.status_code == 401, r.text
            key = self.settings.mfa_enc_key
            assert key is not None
            enrolled = await enroll(SqlAuthStore(self.rw), SecurityEventWriter(self.rw, self.clock), MfaCipher(key),
                                    username=username, by="ops", reason="test")  # fmt: skip
            r = await self.client.post("/api/auth/login",
                                       json={**body, "otp": pyotp.TOTP(enrolled.secret).at(self.clock.now())})  # fmt: skip
            assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}


@asynccontextmanager
async def _desk(db: PgUrls, rw: AsyncEngine, clock: FakeClock) -> AsyncIterator[Desk]:
    """`create_app` + auth SQL + runtime SQL với node THẬT (B1 → … → B12 → B15 thật sau S12 → B16/B17). `approver_id=None`: không
    có người duyệt GIẢ — phiếu chỉ có được nếu B15 THẬT chạy."""
    url = db.role("app_rw")
    records, people = _seed_people(clock.now())
    settings = auth_settings(database_url=url, fake_approver_id=None)
    gw = make_gateway(vpn_scripts(), clock=clock)  # type: ignore[arg-type]
    app = create_app(
        settings, health_checks={}, idp=FakeIdentityProvider(people), clock=clock, guard=MaskingGuard(),
        runtime=pg_runtime_factory(url, clock=clock, ad=FakeAd(*records), nodes="real", llm=gw.client, rag=_rag(),
                                   approver_id=None),
    )  # fmt: skip
    transport = httpx.ASGITransport(app=app, client=("203.0.113.9", 50000))
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client,
    ):
        assert app.state.runtime_status == "up"
        yield Desk(app, client, clock, settings, rw)
        await app.state.background.drain()


async def test_x2_tc19_pg_route_and_real_b15_self_conflict_head_decides(db: PgUrls, rw: AsyncEngine) -> None:
    """x2 / TC19 (bảng 3.2, cổng 4 1.3) + b2: `ha.lt` (l1_01) xin gia hạn PC-0124 của mình (chưa đăng ký → R17) → B15 THẬT: l1_01
    xung đột `self` → giao Trưởng BP `it_mgr01`, dự phòng None. Route dùng CÙNG hàm xung đột: `ha.lt` quyết → 403 (không phải người
    được giao, và tự duyệt), phiếu vẫn `pending`; `quan.tm` quyết → 202, phiếu `approved` bởi it_mgr01."""
    clock = FakeClock(EPOCH)
    async with _desk(db, rw, clock) as d:
        ha = await d.headers("ha.lt")
        r = await d.client.post("/api/tickets", json={"text": "gia hạn VPN cho máy PC-0124"}, headers=ha)
        assert r.status_code == 202, r.text
        ticket = str(r.json()["ticket_id"])
        await d.drain()
        view = await d.client.get(f"/api/tickets/{ticket}", headers=ha)
        assert view.status_code == 200 and view.json()["status"] == S_PENDING_APPROVAL, view.text
        [(aid, approver, backup, conflict, ctype)] = await _rows(
            rw, "SELECT approval_id, approver_id, backup_approver_id, conflict_detected, conflict_type FROM approvals "
                "WHERE ticket_id = :t", t=ticket,
        )  # fmt: skip
        assert (approver, backup, conflict, ctype) == ("it_mgr01", None, True, "self")
        [(matched,)] = await _rows(rw, "SELECT matched_rule_id FROM audit_logs WHERE ticket_id = :t "
                                       "AND event = 'risk_decided'", t=ticket)  # fmt: skip
        assert matched == "R17"
        [(choice,)] = await _rows(rw, "SELECT detail->>'choice_reason' FROM audit_logs WHERE ticket_id = :t "
                                      "AND step = 'B15' AND event = 'queued'", t=ticket)  # fmt: skip
        assert choice == "conflict"

        r = await d.client.post(f"/api/approvals/{aid}/decision", json={"decision": "approved"}, headers=ha)
        assert r.status_code == 403, r.text
        await d.drain()
        assert await scalar(rw, "SELECT status FROM approvals WHERE approval_id = :a", a=aid) == "pending"

        quan = await d.headers("quan.tm")
        r = await d.client.post(f"/api/approvals/{aid}/decision", json={"decision": "approved"}, headers=quan)
        assert r.status_code == 202, r.text
        await d.drain()
    [(status, decided_by)] = await _rows(rw, "SELECT status, decided_by FROM approvals WHERE approval_id = :a", a=aid)
    assert (status, decided_by) == ("approved", "it_mgr01")
