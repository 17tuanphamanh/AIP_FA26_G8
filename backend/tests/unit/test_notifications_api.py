"""`GET /api/me/notifications` — thông báo trong app (api/notifications.py, db/notifications.py). Không DB: nguồn là
`tests/fakes/notifications.MemoryNotifications` gán vào `app.state.notifications` (SQL thật: test_notifications_pg.py).

- Chỉ ticket của người gọi (an.nv = nv001; binh.tt = nv002), cả qua con trỏ; không token → 401.
- Hai `kind`, mọi `result`; `new_ticket_id` luôn null; ca E0 / E1 `injection_suspected` → CÙNG một câu trung tính cho từng `result`,
  `result` vẫn là giá trị thật; text không mã E*/R*/B*/S_*.
- Phân trang keyset > 2 trang, có dòng trùng `created_at`: không trùng, không sót, đúng thứ tự.
- 422 `limit`/`after` sai (`{"error","fields"}`); ghi chú từ chối chỉ vào text khi qua `OutputGuard`.
- Chuỗi SQL: điều kiện requester có đủ 2 lần (mỗi nhánh một lần) ở cả hai câu; route bind `user_id` của token.
"""

import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.api import notifications as api
from app.db import notifications as db
from app.db.notifications import NotificationRow, decode_cursor, encode_cursor
from app.graph.nodes.b20_audit import SUSPECTED_MESSAGE_CODE
from app.settings import get_escalation_templates
from tests.fakes.auth import EPOCH
from tests.fakes.notifications import MemoryNotifications, StoredNotification
from tests.unit.auth_helpers import AuthEnv, auth_env

URL = "/api/me/notifications"
A, B = "nv001", "nv002"  # an.nv, binh.tt
_CANARY_PARTS = ("CANARY", "notif", "9c2e")
CANARY = "-".join(_CANARY_PARTS)  # ghép lúc chạy — viết liền thì gitleaks có thể coi là khoá thật
CODE_PATTERN = re.compile(r"\bE\d\b|\bR\d+\b|\bB\d+\b|S_[A-Z]")
FORBIDDEN_WORDS = ("tấn công", "injection", "chèn lệnh", "phát hiện")
CLOSE_RESULTS = ("completed", "confirmed_denial", "reopened_as_new")


def _at(minutes: int) -> datetime:
    return (EPOCH + timedelta(minutes=minutes)).astimezone(UTC)


def appr(n: int, who: str, minutes: int, result: str = "approved", note: str | None = None, ticket: str = "T-1") -> StoredNotification:
    return StoredNotification(who, NotificationRow(f"appr:{n}", "approval_decided", ticket, result, _at(minutes), note=note))


def esc(n: int, who: str, minutes: int, result: str = "completed", exit_code: str = "E3", detail: str | None = None,
        ticket: str = "T-2") -> StoredNotification:  # fmt: skip
    return StoredNotification(
        who, NotificationRow(f"esc:{n}", "escalation_closed", ticket, result, _at(minutes), exit_code=exit_code, reason_detail=detail)
    )  # fmt: skip


def _env(*items: StoredNotification, **settings: Any) -> Iterator[tuple[AuthEnv, MemoryNotifications]]:
    source = MemoryNotifications(*items)
    with auth_env(**settings) as env:
        env.app.state.notifications = source
        yield env, source


def _get(env: AuthEnv, user: str = "an.nv", query: str = "") -> Any:
    return env.client.get(URL + query, headers=env.bearer(env.token(user)))


def _walk(env: AuthEnv, limit: int, user: str = "an.nv") -> list[list[dict[str, Any]]]:
    pages, after = [], None
    while True:
        r = _get(env, user, f"?limit={limit}" + (f"&after={after}" if after else ""))
        assert r.status_code == 200, r.text
        body = r.json()
        pages.append(body["items"])
        after = body["next_cursor"]
        if after is None:
            return pages
        assert len(pages) < 50


@pytest.fixture
def mixed() -> Iterator[tuple[AuthEnv, MemoryNotifications]]:
    yield from _env(
        appr(1, A, 10), appr(2, A, 20, "rejected", note="Thiếu thông tin máy"), appr(3, B, 30), appr(4, B, 40, "rejected"),
        esc(1, A, 15), esc(2, A, 25, "confirmed_denial"), esc(3, A, 35, "reopened_as_new"), esc(4, B, 45),
    )  # fmt: skip


# ---- quyền / hình dạng -------------------------------------------------------------------------------------------------


def test_no_token_is_401(mixed: tuple[AuthEnv, MemoryNotifications]) -> None:
    env, source = mixed
    r = env.client.get(URL)
    assert r.status_code == 401 and r.json() == {"detail": "unauthorized"}
    assert source.calls == []


def test_source_missing_is_503(mixed: tuple[AuthEnv, MemoryNotifications]) -> None:
    env, _ = mixed
    env.app.state.notifications = None
    r = _get(env)
    assert r.status_code == 503 and r.json() == {"detail": "notifications_unavailable"}


def test_shape_and_both_kinds_all_results(mixed: tuple[AuthEnv, MemoryNotifications]) -> None:
    env, source = mixed
    r = _get(env)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"items", "next_cursor"} and body["next_cursor"] is None
    assert source.calls[0]["user_id"] == A and source.calls[0]["limit"] == 21  # route bind user của token; +1 dò trang sau
    items = body["items"]
    assert {i["kind"] for i in items} == {"approval_decided", "escalation_closed"}
    assert {i["result"] for i in items} == {"approved", "rejected", *CLOSE_RESULTS}
    for i in items:
        assert set(i) == {"id", "kind", "ticket_id", "text", "result", "new_ticket_id", "created_at"}
        assert i["new_ticket_id"] is None
        assert datetime.fromisoformat(i["created_at"]).tzinfo is not None
    assert [i["id"] for i in items] == ["esc:3", "esc:2", "appr:2", "esc:1", "appr:1"]  # created_at ↓
    by_id = {i["id"]: i for i in items}
    assert by_id["appr:1"]["text"] == api.APPROVED_TEXT
    assert by_id["appr:2"]["text"] == "Yêu cầu của bạn chưa được duyệt. Ghi chú của người duyệt: Thiếu thông tin máy"
    assert by_id["esc:1"]["text"] == api.CLOSED_TEXT["completed"]
    assert by_id["esc:2"]["text"] == api.CLOSED_TEXT["confirmed_denial"]
    assert by_id["esc:3"]["text"] == "Kỹ thuật viên đề nghị bạn gửi một yêu cầu mới cho việc này."
    assert by_id["esc:3"]["new_ticket_id"] is None


KIND_CONTRACT = {
    "approval_decided": ("appr:", {"approved", "rejected"}),
    "escalation_closed": ("esc:", {"completed", "confirmed_denial", "reopened_as_new"}),
}


def test_every_item_kind_result_and_id_prefix_agree(mixed: tuple[AuthEnv, MemoryNotifications]) -> None:
    """Quét MỌI item (mọi trang): kind ↔ tiền tố id ↔ tập result hợp lệ — FE rẽ nhánh theo bộ ba này."""
    env, _ = mixed
    items = [i for page in _walk(env, 2) for i in page]
    assert len(items) == 5
    for i in items:
        prefix, results = KIND_CONTRACT[i["kind"]]
        assert i["id"].startswith(prefix) and i["result"] in results, i


def test_empty_list(mixed: tuple[AuthEnv, MemoryNotifications]) -> None:
    env, source = mixed
    source.items.clear()
    assert _get(env).json() == {"items": [], "next_cursor": None}


# ---- chống xem chéo ----------------------------------------------------------------------------------------------------


def test_employee_never_sees_other_employees_notifications_even_via_cursor(mixed: tuple[AuthEnv, MemoryNotifications]) -> None:
    env, _ = mixed
    mine = {f"appr:{n}" for n in (1, 2)} | {f"esc:{n}" for n in (1, 2, 3)}
    theirs = {"appr:3", "appr:4", "esc:4"}
    seen = [i["id"] for page in _walk(env, 1) for i in page]
    assert set(seen) == mine and not set(seen) & theirs
    # con trỏ lấy từ B đưa cho A: vẫn chỉ ticket của A
    cursor_of_b = encode_cursor(NotificationRow("esc:4", "escalation_closed", "T", "completed", _at(45)))
    r = _get(env, "an.nv", f"?after={cursor_of_b}")
    assert {i["id"] for i in r.json()["items"]} <= mine
    other = {i["id"] for page in _walk(env, 2, "binh.tt") for i in page}
    assert other == theirs


# ---- ca trung tính E0 / E1 injection_suspected -------------------------------------------------------------------------


NEUTRAL_CASES = [("E0", None), ("E0", "x"), ("E1", "injection_suspected")]


@pytest.mark.parametrize(("exit_code", "detail"), NEUTRAL_CASES)
@pytest.mark.parametrize("result", CLOSE_RESULTS)
def test_suspected_attack_is_neutral_and_result_is_real(exit_code: str, detail: str | None, result: str) -> None:
    [(env, _)] = list(_env(esc(1, A, 5, result, exit_code, detail)))
    [item] = _get(env).json()["items"]
    assert item["text"] == api.NEUTRAL_TEXT == "Yêu cầu của bạn đã được bộ phận IT xem xét xong."
    assert item["result"] == result and item["new_ticket_id"] is None
    low = item["text"].casefold()
    assert not any(w in low for w in FORBIDDEN_WORDS) and not CODE_PATTERN.search(item["text"])


def test_neutral_condition_pinned_to_b20_message_code() -> None:
    """Cùng điều kiện chọn tin của B20: chỉ `injection_suspected` đổi E1 sang tin E0."""
    assert SUSPECTED_MESSAGE_CODE == {api.INJECTION_SUSPECTED: "E0"}
    assert api.is_neutral("E1", "injection_suspected") and api.is_neutral("E0", None)
    for code in ("E1", "E2", "E3", "E5", "E9"):
        assert not api.is_neutral(code, "out_of_scope")
    assert not api.is_neutral("E2", "injection_suspected")


def test_non_neutral_escalation_is_not_the_neutral_sentence() -> None:
    [(env, _)] = list(_env(esc(1, A, 5, "completed", "E1", "out_of_scope")))
    assert _get(env).json()["items"][0]["text"] == api.CLOSED_TEXT["completed"]


def test_neutral_sentence_is_distinct_from_e0_template_words() -> None:
    e0 = get_escalation_templates().of("E0").user_message
    assert not any(w in e0.casefold() for w in FORBIDDEN_WORDS)  # mẫu E0 sẵn có cũng trung tính


# ---- không mã trong text -----------------------------------------------------------------------------------------------


def test_no_internal_codes_in_any_text() -> None:
    items = [appr(1, A, 1), appr(2, A, 2, "rejected"), appr(3, A, 3, "rejected", note="Không đủ thẩm quyền")]
    n = 10
    for code in ("E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9"):
        for result in CLOSE_RESULTS:
            n += 1
            items.append(esc(n, A, n, result, code, "injection_suspected" if code == "E1" else "tool_system_error"))
    [(env, _)] = list(_env(*items))
    texts = [i["text"] for page in _walk(env, 7) for i in page]
    assert len(texts) == len(items)
    for t in texts:
        assert not CODE_PATTERN.search(t), t


# ---- ghi chú từ chối qua OutputGuard -----------------------------------------------------------------------------------


def test_rejection_note_passes_output_guard_or_is_dropped() -> None:
    items = (appr(1, A, 1, "rejected", note=f"Xem {CANARY} nhé"), appr(2, A, 2, "rejected", note="   "), appr(3, A, 3, "rejected", None),
             appr(4, A, 4, "rejected", note="Thiếu thông tin"))  # fmt: skip
    [(env, _)] = list(_env(*items, output_canaries=[CANARY]))
    by_id = {i["id"]: i["text"] for i in _get(env).json()["items"]}
    assert by_id["appr:1"] == by_id["appr:2"] == by_id["appr:3"] == api.REJECTED_TEXT  # canary → bỏ câu ghi chú
    assert by_id["appr:4"].endswith("Thiếu thông tin")
    assert CANARY not in str(by_id)


# ---- phân trang --------------------------------------------------------------------------------------------------------


def test_keyset_pagination_no_duplicates_no_gaps_over_many_pages() -> None:
    items = [appr(n, A, n // 3) for n in range(1, 8)] + [esc(n, A, n // 3, "completed") for n in range(1, 8)]  # trùng created_at
    items += [appr(99, B, 1), esc(99, B, 1)]
    [(env, _)] = list(_env(*items))
    expected = [r.row.id for r in sorted((i for i in items if i.requester_id == A), key=lambda i: (i.row.created_at, i.row.id), reverse=True)]
    pages = _walk(env, 3)
    assert len(pages) > 2 and [len(p) for p in pages[:-1]] == [3] * (len(pages) - 1)
    seen = [i["id"] for p in pages for i in p]
    assert seen == expected and len(set(seen)) == len(seen) == 14
    assert "appr:99" not in seen and "esc:99" not in seen


def test_last_page_has_no_cursor_even_when_full() -> None:
    [(env, _)] = list(_env(*[appr(n, A, n) for n in range(1, 5)]))
    pages = _walk(env, 2)
    assert [len(p) for p in pages] == [2, 2]


def test_limit_default_and_max() -> None:
    [(env, source)] = list(_env(*[appr(n, A, n) for n in range(1, 61)]))
    assert len(_get(env).json()["items"]) == 20
    assert len(_get(env, query="?limit=50").json()["items"]) == 50
    assert source.calls[-1]["limit"] == 51


# ---- 422 ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["?limit=0", "?limit=51", "?limit=-1", "?limit=abc", "?limit="])
def test_bad_limit_is_422(mixed: tuple[AuthEnv, MemoryNotifications], query: str) -> None:
    env, source = mixed
    r = _get(env, query=query)
    assert r.status_code == 422 and r.json() == {"error": "invalid_request", "fields": ["query.limit"]}
    assert source.calls == []


GOOD = encode_cursor(NotificationRow("appr:1", "approval_decided", "T", "approved", _at(1)))


@pytest.mark.parametrize(
    "after",
    ["!!!", "abc", "e30", "bnVsbA", "x" * 600, "", "eyJ0IjoiMjAyNi0xMC0wMVQwMDowMDowMCIsImkiOiJhcHByOjEifQ"],  # cuối: t không múi giờ
)
def test_bad_after_is_422(mixed: tuple[AuthEnv, MemoryNotifications], after: str) -> None:
    env, source = mixed
    r = _get(env, query=f"?after={after}")
    assert r.status_code == 422 and r.json() == {"error": "invalid_request", "fields": ["query.after"]}
    assert source.calls == []
    assert _get(env, query=f"?after={GOOD}").status_code == 200


def test_422_never_echoes_input(mixed: tuple[AuthEnv, MemoryNotifications]) -> None:
    env, _ = mixed
    r = _get(env, query="?after=!!!secret!!!&limit=0")
    assert r.status_code == 422 and "secret" not in r.text and "input" not in r.json()


# ---- con trỏ / SQL -----------------------------------------------------------------------------------------------------


def test_cursor_roundtrip_is_opaque_and_utc() -> None:
    row = NotificationRow("esc:12", "escalation_closed", "T", "completed", datetime(2026, 10, 27, 1, 2, 3, 456789, tzinfo=UTC))
    c = encode_cursor(row)
    assert re.fullmatch(r"[A-Za-z0-9_-]+", c)
    back = decode_cursor(c)
    assert (back.at, back.id) == (row.created_at, "esc:12")


@pytest.mark.parametrize("value", ["", "@@", "e30", "W10", "eyJ0IjoxLCJpIjoiYXBwcjoxIn0", "eyJ0IjoiMjAyNi0xMC0wMVQwMDowMDowMCswMDowMCIsImkiOiJ4In0"])
def test_decode_rejects(value: str) -> None:
    with pytest.raises(ValueError, match="cursor"):
        decode_cursor(value)


def test_sql_filters_requester_in_both_branches_of_both_queries() -> None:
    for sql in (db.FIRST_PAGE_SQL, db.NEXT_PAGE_SQL):
        assert sql.count(db.REQUESTER_PREDICATE) == 2
        assert "t.requester_id = :user_id" in sql and sql.count("UNION ALL") == 1
        assert 'COLLATE "C" DESC' in sql and "LIMIT :n" in sql
    assert 'COLLATE "C") < (:c_at, :c_id)' in db.NEXT_PAGE_SQL


def test_openapi_declares_response_model() -> None:
    with auth_env() as env:
        op = env.app.openapi()["paths"][URL]["get"]
        assert op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("NotificationPage")
        assert {"401", "403", "422", "503"} <= set(op["responses"])
