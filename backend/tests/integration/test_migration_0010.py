"""Migration 0010 (gói 2b, D-54 a) trên Postgres 16 thật — viết TỪ ĐẶC TẢ trước code (không mở `0010_rate_limits.py`):
`claude/dac-ta-bat-2-model.md` 4.8 "Migration 0010", 4.10 "Dữ liệu" (`v_leaf` thêm `requester_id`), 8 ("migration 0010 chạy lên và
xuống được; sau khi lên `v_leaf` vẫn `security_invoker`; xuống dừng khi đã có dòng `rate_limited`"), PLAN-2B1 3.4, ca P8–P9.
Mỗi test một database riêng (`fresh_database`)."""

import importlib.util
from types import ModuleType
from typing import Any

import pytest
from alembic import command
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import DBAPIError
from tests.integration.pg import REPO, PgUrls, alembic_config, fresh_database

VIEWS = ("v_leaf", "v_decisions", "v_l2_queue")
NEW_INDEXES = ("ix_tickets_requester_created_at", "ix_rate_hits_user_created_at")


def _load_0008() -> ModuleType:
    """Cột `v_leaf` của 0008 — nạp theo đường dẫn (tên file bắt đầu bằng số), như `test_monitor_dash_views_pg.py`."""
    path = REPO / "backend" / "app" / "db" / "alembic" / "versions" / "0008_monitor_views.py"
    spec = importlib.util.spec_from_file_location("m9_0008_for_0010", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M8 = _load_0008()


def _scalar(engine: Engine, sql: str, **params: Any) -> Any:
    with engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def _version(engine: Engine) -> str:
    return str(_scalar(engine, "SELECT version_num FROM alembic_version"))


def _columns(engine: Engine, view: str) -> list[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = :v "
            "ORDER BY ordinal_position"
        ), {"v": view})  # fmt: skip
        return [r[0] for r in rows]


def _state(engine: Engine) -> dict[str, Any]:
    """Ảnh chụp phần 0010 chạm tới: bảng `rate_hits`, 2 index mới, CHECK `event_type`, cột `v_leaf`, option + GRANT `app_monitor`
    của 3 view."""
    with engine.connect() as conn:
        indexes: set[str] = set(conn.execute(text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")).scalars())
        check = conn.execute(text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'ck_security_events_event_type'"
        )).scalar()  # fmt: skip
        rows = conn.execute(text(
            "SELECT relname, reloptions FROM pg_class WHERE relkind = 'v' AND relname = ANY(:v)"), {"v": list(VIEWS)}
        ).all()  # fmt: skip
        options = {name: opts for name, opts in rows}
        grants = {v: conn.execute(text("SELECT has_table_privilege('app_monitor', :v, 'SELECT')"), {"v": v}).scalar()
                  for v in VIEWS}  # fmt: skip
        table = conn.execute(text("SELECT to_regclass('public.rate_hits')")).scalar()
    return {
        "rate_hits": table is not None, "indexes": {i for i in NEW_INDEXES if i in indexes},
        "rate_limited_in_check": "'rate_limited'" in str(check), "v_leaf": _columns(engine, "v_leaf"),
        "options": options, "monitor_grants": grants,
    }  # fmt: skip


UP = {
    "rate_hits": True, "indexes": set(NEW_INDEXES), "rate_limited_in_check": True,
    "v_leaf": [*M8.LEAF_COLUMNS, "requester_id"],
    "options": {v: ["security_invoker=true"] for v in VIEWS}, "monitor_grants": dict.fromkeys(VIEWS, True),
}  # fmt: skip
DOWN = {**UP, "rate_hits": False, "indexes": set(), "rate_limited_in_check": False, "v_leaf": list(M8.LEAF_COLUMNS)}


def test_p8_0010_up_down_up(pg: PgUrls) -> None:
    """P8: lên — bảng, 2 index, CHECK có `rate_limited`, `v_leaf` có `requester_id` CUỐI, 3 view vẫn `security_invoker=true` + GRANT
    `app_monitor`; xuống `0009` — không còn `rate_hits`, index, cột; `v_leaf` như 0008; option + GRANT của 3 view còn; lên lại như cũ."""
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        owner = create_engine(db.role("app_migrate"))
        mon = create_engine(db.role("app_monitor"))
        try:
            command.upgrade(cfg, "head")
            assert _version(owner) == "0010"
            assert _state(owner) == UP
            assert _scalar(mon, "SELECT count(*) FROM v_leaf WHERE requester_id IS NOT NULL") == 0  # app_monitor đọc được cột mới
            command.downgrade(cfg, "0009")
            assert _version(owner) == "0009"
            assert _state(owner) == DOWN
            for view in VIEWS:
                assert _scalar(mon, f"SELECT count(*) FROM {view}") == 0  # GRANT trên view tạo lại còn hiệu lực
            command.upgrade(cfg, "head")
            assert _state(owner) == UP
        finally:
            owner.dispose()
            mon.dispose()


def test_p8_check_rejects_rate_limited_after_downgrade_accepts_after_upgrade(pg: PgUrls) -> None:
    """P8: CHECK `security_events.event_type` — ở 0009 từ chối `rate_limited`, ở 0010 nhận (dòng ghi được bằng `app_rw`)."""
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "0009")
        rw = create_engine(db.role("app_rw"))
        insert = "INSERT INTO security_events (event_type, detail) VALUES ('rate_limited', '{}'::jsonb)"
        try:
            with pytest.raises(DBAPIError, match="ck_security_events_event_type"), rw.begin() as conn:
                conn.execute(text(insert))
            command.upgrade(cfg, "head")
            with rw.begin() as conn:
                conn.execute(text(insert))
        finally:
            rw.dispose()


def test_p9_downgrade_refused_when_rate_limited_rows_exist(pg: PgUrls) -> None:
    """P9 (4.8 "dừng khi `security_events` đã có dòng `rate_limited` (khuôn 0002)"): `RuntimeError`, DB vẫn ở 0010, không đổi gì."""
    with fresh_database(pg) as db:
        cfg = alembic_config(db)
        command.upgrade(cfg, "head")
        owner = create_engine(db.role("app_migrate"))
        rw = create_engine(db.role("app_rw"))
        try:
            with rw.begin() as conn:
                conn.execute(text("INSERT INTO users (user_id, username, role) VALUES ('rl-mig', 'rl.mig', 'employee')"))
                conn.execute(text(
                    "INSERT INTO security_events (event_type, user_id, route, detail) VALUES ('rate_limited', 'rl-mig', "
                    "'/api/tickets', '{\"counter\": \"tickets\", \"window\": \"10m\", \"limit\": 10}'::jsonb)"
                ))  # fmt: skip
            with pytest.raises(RuntimeError):
                command.downgrade(cfg, "0009")
            assert _version(owner) == "0010"
            assert _state(owner) == UP
        finally:
            owner.dispose()
            rw.dispose()
