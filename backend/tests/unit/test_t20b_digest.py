"""T20b — hàm THUẦN của vòng cha (phase5 5.2.4, 5.2.5, 5.2.6; P9, P10). Viết TỪ ĐẶC TẢ trước code (thân hàm chưa đọc).

Phủ: m1 (`compose_digest`: tiêu đề `ACTION_LABELS` / nhãn loại / ý E1, thứ tự `index`, vòng cuối chỉ câu tổng kết), m2 (hình dạng tin
`digest`, `items[].kind` ∈ 4 giá trị FE), p5 (`aggregate_children` 6 dòng + dòng đủ 3 loại, bảng 5.2.5; con chưa kết thúc / `S_BLOCKED`
→ `ValueError`), câu tổng kết (`summary_text`), `stopped`/`needs_of` (5.2.4), `reply_text` (P8, hợp đồng FE (d)).
Mọi ca thuộc DỪNG 1.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.domain.children import (
    SUMMARY,
    ChildView,
    Notice,
    aggregate_children,
    child_id,
    child_index,
    needs_of,
    stopped,
    summary_text,
)
from app.domain.messages import (
    ACTION_LABELS,
    CONFIRMED_TEXT,
    DIGEST_ITEM_KINDS,
    INTENT_LABELS,
    OTHER_LABEL,
    UNRESOLVED_TEXT,
    Digest,
    child_title,
    compose_digest,
    reply_text,
)
from app.domain.states import S_BLOCKED, S_ESCALATED, S_REJECTED, S_RESOLVED

T0 = datetime(2026, 10, 15, 3, 0, tzinfo=UTC)



P = "P1"
ITEM_KEYS = {"child_id", "index", "title", "kind", "text", "needs", "step"}  # `step` = `source_step` của notice (Q6 c2)
MSG_KEYS = {"role", "kind", "round", "text", "items"}


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


RESET_TITLE = cap(ACTION_LABELS["reset_password"])
INSTALL_TITLE = cap(ACTION_LABELS["install_software"])


def notice(nid: int, cid: str, kind: Any, needs: Any, body: str, *, step: str = "B18", minutes: int = 0) -> Notice:
    """`kind`/`needs` là Literal của `domain.children` — nhận `Any` để tham số hoá bằng chuỗi."""
    return Notice(nid, cid, step, kind, needs, body, T0 + timedelta(minutes=minutes))


def view(i: int, final: str | None, *pending: Notice) -> ChildView:
    return ChildView(child_id(P, i), i, final, tuple(pending))


SEEDS: dict[str, dict[str, Any]] = {
    child_id(P, 1): {"intent": "account", "slots": {"action": "reset_password", "account_type": "ad"}},
    child_id(P, 2): {"intent": "software", "slots": {"action": "install_software", "software_name": "Zoom"}},
    child_id(P, 3): {"intent": "access", "slots": {}},
    child_id(P, 4): {"exit_code": "E1", "escalation_reason_detail": "out_of_scope", "slots": {}},
}


# ---- child_id / child_index (đã có) -------------------------------------------------------------------------------------------


def test_child_id_deterministic_and_index() -> None:
    """P4: `cid = f"{cha}-{i}"` tất định; `index` = đoạn sau dấu "-" cuối (cha có thể chứa "-")."""
    assert child_id("abc-def", 2) == "abc-def-2"
    assert child_index("abc-def-2") == 2


# ---- m1: tiêu đề ----------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("seed", "title"),
    [
        pytest.param({"intent": "account", "slots": {"action": "reset_password"}}, RESET_TITLE, id="action-label"),
        pytest.param({"intent": "software", "slots": {"action": "install_software"}}, INSTALL_TITLE, id="install-label"),
        pytest.param({"intent": "vpn", "slots": {}}, "VPN", id="intent-vpn"),
        pytest.param({"intent": "account", "slots": {}}, "Tài khoản", id="intent-account"),
        pytest.param({"intent": "software", "slots": {}}, "Phần mềm", id="intent-software"),
        pytest.param({"intent": "access", "slots": {}}, "Quyền truy cập", id="intent-access"),
        pytest.param({"exit_code": "E1", "slots": {}}, "Yêu cầu khác", id="e1-no-intent"),
    ],
)
def test_m1_child_title(seed: dict[str, Any], title: str) -> None:
    """m1 (P9): `ACTION_LABELS[slots.action]` (viết hoa chữ đầu) nếu có, không thì nhãn loại; ý E1 (không `intent`) → "Yêu cầu khác"."""
    assert child_title(seed) == title


def test_m1_labels_constants() -> None:
    """P9: nhãn loại chốt 10/10 (a) — không để LLM đặt."""
    assert INTENT_LABELS == {"account": "Tài khoản", "vpn": "VPN", "software": "Phần mềm", "access": "Quyền truy cập"}
    assert OTHER_LABEL == "Yêu cầu khác"
    assert RESET_TITLE == "Đặt lại mật khẩu"


# ---- m1/m2: compose_digest ------------------------------------------------------------------------------------------------------


def _line(i: int, title: str, body: str) -> str:
    return f"Ý {i} – {title}: {body}"


def test_m1_m2_digest_round1_order_by_index_and_shape() -> None:
    """m1 + m2 (5.2.6): mỗi notice chưa gửi một item, theo `index` rồi thứ tự tạo (view đưa vào lộn xộn); `answer` → `result`;
    `text` = các dòng "Ý i – tiêu đề: thân" nối "\\n"; chưa con nào kết thúc → KHÔNG câu tổng kết; `notice_ids` = notice đã gom."""
    v = [
        view(2, None, notice(12, child_id(P, 2), "question", "answer", "Máy nào?", step="B11", minutes=2)),
        view(1, None, notice(10, child_id(P, 1), "answer", "confirm", "Theo KB, làm A.", step="B10", minutes=1),
             notice(11, child_id(P, 1), "result", "confirm", "Đã đặt lại mật khẩu.", minutes=3)),
    ]  # fmt: skip
    d = compose_digest(v, SEEDS, round_no=1)
    assert isinstance(d, Digest)
    assert set(d.msg) == MSG_KEYS
    assert (d.msg["role"], d.msg["kind"], d.msg["round"]) == ("assistant", "digest", 1)
    assert d.msg["items"] == [
        {"child_id": "P1-1", "index": 1, "title": RESET_TITLE, "kind": "result", "text": "Theo KB, làm A.", "needs": "confirm",
         "step": "B10"},
        {"child_id": "P1-1", "index": 1, "title": RESET_TITLE, "kind": "result", "text": "Đã đặt lại mật khẩu.",
         "needs": "confirm", "step": "B18"},
        {"child_id": "P1-2", "index": 2, "title": INSTALL_TITLE, "kind": "question", "text": "Máy nào?", "needs": "answer",
         "step": "B11"},
    ]  # fmt: skip
    assert d.msg["text"] == "\n".join([
        _line(1, RESET_TITLE, "Theo KB, làm A."), _line(1, RESET_TITLE, "Đã đặt lại mật khẩu."),
        _line(2, INSTALL_TITLE, "Máy nào?"),
    ])  # fmt: skip
    assert sorted(d.notice_ids) == [10, 11, 12]
    assert all(set(it) == ITEM_KEYS for it in d.msg["items"])


@pytest.mark.parametrize("kind", ["answer", "question", "result", "rejection", "escalation"])
def test_m2_item_kind_in_four_fe_values(kind: str) -> None:
    """m2: `items[].kind` ∈ {result, question, rejection, escalation} — `answer` (B10) hiển thị như `result`."""
    needs = {"answer": "confirm", "question": "answer", "result": "confirm"}.get(kind, "none")
    final = S_ESCALATED if kind == "escalation" else S_REJECTED if kind == "rejection" else None
    d = compose_digest([view(1, final, notice(1, "P1-1", kind, needs, "x"))], SEEDS, round_no=1)
    [it] = d.msg["items"]
    assert it["kind"] in DIGEST_ITEM_KINDS == ("result", "question", "rejection", "escalation")
    assert it["kind"] == ("result" if kind == "answer" else kind)


def test_m1_final_round_with_notices_adds_summary_line() -> None:
    """m1 (P9 + 5.2.5): mọi con đã kết thúc → thêm MỘT dòng câu tổng kết sau các khối (con 2 E1 vừa để lại notice `escalation`)."""
    v = [view(1, S_RESOLVED), view(4, S_ESCALATED, notice(7, "P1-4", "escalation", "none", "Đã chuyển kỹ thuật viên.",
                                                          step="B20"))]  # fmt: skip
    d = compose_digest(v, SEEDS, round_no=2)
    summary = "Đã xong 1/2 yêu cầu; phần còn lại đã chuyển kỹ thuật viên."
    assert d.msg["text"] == "\n".join([_line(4, "Yêu cầu khác", "Đã chuyển kỹ thuật viên."), summary])
    assert d.msg["round"] == 2 and [it["child_id"] for it in d.msg["items"]] == ["P1-4"]
    assert d.notice_ids == (7,)


def test_m1_final_round_without_notices_only_summary() -> None:
    """m1: vòng cuối không còn notice nào → `text` CHỈ câu tổng kết, `items` rỗng, không notice nào để đánh dấu."""
    d = compose_digest([view(1, S_RESOLVED), view(2, S_RESOLVED)], SEEDS, round_no=3)
    assert d.msg == {"role": "assistant", "kind": "digest", "round": 3, "text": "Cả 2 yêu cầu đã hoàn tất.", "items": []}
    assert d.notice_ids == ()


def test_m1_no_text_outside_notices_and_templates() -> None:
    """m1 (5.2.10 mục 7): tin chỉ ghép chữ mẫu + `body` notice + số — không lấy chữ nào từ seed ngoài nhãn (vd `span`)."""
    seeds = {**SEEDS, "P1-1": {**SEEDS["P1-1"], "span": "CHU-NGUOI-DUNG-khong-duoc-chep", "redacted_request": "CAU-GOC"}}
    d = compose_digest([view(1, None, notice(1, "P1-1", "result", "confirm", "Thân."))], seeds, round_no=1)
    assert "CHU-NGUOI-DUNG" not in repr(d.msg) and "CAU-GOC" not in repr(d.msg)


# ---- p5: aggregate_children + câu tổng kết (bảng 5.2.5) -----------------------------------------------------------------------

R, E, J = S_RESOLVED, S_ESCALATED, S_REJECTED
TABLE_525 = [
    pytest.param([R, R], R, "ALL_RESOLVED", "Cả 2 yêu cầu đã hoàn tất.", id="all-resolved"),
    pytest.param([R, E, R], R, "PARTIALLY_ESCALATED", "Đã xong 2/3 yêu cầu; phần còn lại đã chuyển kỹ thuật viên.",
                 id="partially-escalated"),
    pytest.param([E, E], E, "ALL_ESCALATED", "Các yêu cầu đã được chuyển kỹ thuật viên.", id="all-escalated"),
    pytest.param([J, R], R, "PARTIALLY_REJECTED", "Đã xong 1/2 yêu cầu; có yêu cầu không được duyệt.",
                 id="partially-rejected"),
    pytest.param([J, J, J], J, "ALL_REJECTED", "Các yêu cầu không được duyệt.", id="all-rejected"),
    pytest.param([E, J], E, "MIXED",
                 "Các yêu cầu không xử lý tự động được (chuyển kỹ thuật viên hoặc không được duyệt).", id="mixed"),
    pytest.param([R, E, J, R], R, "PARTIALLY_ESCALATED",
                 "Đã xong 2/4 yêu cầu; phần còn lại đã chuyển kỹ thuật viên.", id="du-3-loai"),
]  # fmt: skip


@pytest.mark.parametrize(("finals", "parent", "status", "summary"), TABLE_525)
def test_p5_aggregate_children_table_525(finals: list[str], parent: str, status: str, summary: str) -> None:
    """p5 (P10): 6 trường hợp [Chốt B5] + đủ 3 loại [Đề xuất] — ưu tiên ESCALATED > REJECTED > RESOLVED (M-T20b-8)."""
    v = [view(i, f) for i, f in enumerate(finals, 1)]
    assert aggregate_children(v) == (parent, status)


@pytest.mark.parametrize(("finals", "parent", "status", "summary"), TABLE_525)
def test_p5_summary_text_table_525(finals: list[str], parent: str, status: str, summary: str) -> None:
    """Câu tổng kết (P9): thuần mẫu, `{n}` = số con, `{r}` = số con RESOLVED."""
    v = [view(i, f) for i, f in enumerate(finals, 1)]
    assert summary_text(v) == summary


def test_p5_summary_six_keys() -> None:
    assert set(SUMMARY) == {"ALL_RESOLVED", "PARTIALLY_ESCALATED", "ALL_ESCALATED", "PARTIALLY_REJECTED", "ALL_REJECTED",
                            "MIXED"}  # fmt: skip


@pytest.mark.parametrize("finals", [[R, None], [R, S_BLOCKED]], ids=["chua-ket-thuc", "blocked"])
def test_p5_aggregate_rejects_unfinished_or_blocked(finals: list[str | None]) -> None:
    """P10: chỉ gọi khi mọi con có `final_state`; con `S_BLOCKED` không xảy ra (P1) → `ValueError` (E9 cha, thấy được)."""
    with pytest.raises(ValueError):
        aggregate_children([view(i, f) for i, f in enumerate(finals, 1)])


# ---- stopped / needs_of (5.2.4) ------------------------------------------------------------------------------------------------


def test_stopped_and_needs_of() -> None:
    """5.2.4: dừng = có `final_state` HOẶC có notice chưa gửi `needs≠none`; `approval_wait` (không notice, chưa final) = CHƯA dừng
    (D-31, M-T20b-4); `needs` = của notice chưa gửi MỚI NHẤT có `needs≠none`."""
    approval = view(1, None)
    only_none = view(2, None, notice(1, "P1-2", "escalation", "none", "x"))
    asked_then_result = view(3, None, notice(2, "P1-3", "question", "answer", "q", minutes=1),
                             notice(3, "P1-3", "result", "confirm", "r", minutes=2))  # fmt: skip
    done = view(4, S_RESOLVED)
    assert [stopped(c) for c in (approval, only_none, asked_then_result, done)] == [False, False, True, True]
    assert needs_of(asked_then_result) == "confirm"
    assert needs_of(view(5, None, notice(4, "P1-5", "question", "answer", "q"))) == "answer"
    assert needs_of(approval) == "none" and needs_of(only_none) == "none"


# ---- reply_text (P8, hợp đồng FE (d)) ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("items", "text"),
    [
        pytest.param([(1, {"confirmed": True}), (2, {"answer": "30"})], "Ý 1: Đã ổn · Ý 2: 30", id="confirm-answer"),
        pytest.param([(1, {"confirmed": False, "note": "vẫn chưa đăng nhập được"})],
                     "Ý 1: Chưa ổn — vẫn chưa đăng nhập được", id="chua-on-ghi-chu"),
        pytest.param([(1, {"confirmed": False, "note": None}), (3, {"confirmed": True, "note": None})],
                     "Ý 1: Chưa ổn · Ý 3: Đã ổn", id="chua-on-khong-ghi-chu"),
        pytest.param([(2, {"confirmed": False, "note": ""})], "Ý 2: Chưa ổn", id="ghi-chu-rong"),
    ],
)  # fmt: skip
def test_reply_text(items: list[tuple[int, dict[str, Any]]], text: str) -> None:
    """P8: "Ý 1: Đã ổn · Ý 2: <câu trả lời>", "Chưa ổn — <ghi chú>" — ghép theo thứ tự ý."""
    assert (CONFIRMED_TEXT, UNRESOLVED_TEXT) == ("Đã ổn", "Chưa ổn")
    assert reply_text(items) == text
