"""Ticket con nhìn từ ticket cha (Phase 5 T20b — phase5 5.2.4, 5.2.5; B03 §5.4; P1 §8.1–8.4; D-17, D-30, D-31) — thuần.

Cha đối soát con từ DB (D-17): `tickets.final_state` + `child_notices` chưa gửi — KHÔNG đọc checkpoint con. `ChildView` là đúng phần đó.

- **Con đã dừng** (P1 §8.1): đã kết thúc (`final_state`), HOẶC có notice chưa gửi `needs ≠ none` (đang chờ người dùng ở
  `clarify_wait`/`confirm_wait`). Con ở `approval_wait` (chờ L1) KHÔNG phải điểm dừng.
- `needs` của con chưa kết thúc = `needs` của notice chưa gửi MỚI NHẤT (một con dừng ở một điểm chờ một lúc).
- `aggregate_children` (bảng 5.2.5): chỉ gọi khi mọi con có `final_state`; ưu tiên ESCALATED > REJECTED > RESOLVED.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final, Literal

from app.domain.states import S_ESCALATED, S_REJECTED, S_RESOLVED

type NoticeKind = Literal["answer", "question", "result", "rejection", "escalation"]
type NoticeNeeds = Literal["none", "answer", "confirm"]

_FINALS: Final = frozenset({S_RESOLVED, S_ESCALATED, S_REJECTED})  # con không bao giờ S_BLOCKED (P1)

# Câu tổng kết vòng cuối (bảng 5.2.5) — thuần mẫu; `{n}` = số con, `{r}` = số con RESOLVED.
SUMMARY: Final = {
    "ALL_RESOLVED": "Cả {n} yêu cầu đã hoàn tất.",
    "PARTIALLY_ESCALATED": "Đã xong {r}/{n} yêu cầu; phần còn lại đã chuyển kỹ thuật viên.",
    "ALL_ESCALATED": "Các yêu cầu đã được chuyển kỹ thuật viên.",
    "PARTIALLY_REJECTED": "Đã xong {r}/{n} yêu cầu; có yêu cầu không được duyệt.",
    "ALL_REJECTED": "Các yêu cầu không được duyệt.",
    "MIXED": "Các yêu cầu không xử lý tự động được (chuyển kỹ thuật viên hoặc không được duyệt).",
}


@dataclass(frozen=True)
class Notice:
    """Một dòng `child_notices` chưa gửi (`delivered_at IS NULL`). `body` đã là chữ mẫu / đã qua output guard ở node con."""

    notice_id: int
    child_id: str
    source_step: str
    kind: NoticeKind
    needs: NoticeNeeds
    body: str
    created_at: datetime


@dataclass(frozen=True)
class ChildView:
    """Một con theo DB: `final_state` (B20 `finalize_once`) + notice chưa gửi theo thứ tự tạo (cũ → mới)."""

    child_id: str
    index: int  # 1..n — hậu tố của `child_id` (`<cha>-<i>`), = thứ tự ý LLM trả
    final_state: str | None
    pending: tuple[Notice, ...] = ()


def child_id(parent_id: str, index: int) -> str:
    """Id con tất định (P4): `<cha>-<i>`, `i` từ 1."""
    return f"{parent_id}-{index}"


def child_index(cid: str) -> int:
    """`i` của `<cha>-<i>` (id cha là uuid có dấu `-` — lấy đoạn SAU dấu `-` cuối)."""
    return int(cid.rsplit("-", 1)[1])


def stopped(view: ChildView) -> bool:
    """Con đã dừng: kết thúc, hoặc có notice chưa gửi `needs ≠ none`. Chờ L1 duyệt KHÔNG phải điểm dừng (D-31)."""
    return view.final_state is not None or any(n.needs != "none" for n in view.pending)


def needs_of(view: ChildView) -> NoticeNeeds:
    """`needs` của notice chưa gửi MỚI NHẤT có `needs ≠ none`; không có → `none`."""
    asking = [n for n in view.pending if n.needs != "none"]
    return max(asking, key=lambda n: (n.created_at, n.notice_id)).needs if asking else "none"


def aggregate_children(view: Sequence[ChildView]) -> tuple[str, str]:
    """(trạng thái cuối của cha, `aggregate_status`) — bảng 5.2.5. Con chưa kết thúc → `ValueError`; con `S_BLOCKED` (không xảy
    ra — P1) → `ValueError` (E9 cha, thấy được)."""
    finals = [v.final_state for v in view]
    if not finals or any(f not in _FINALS for f in finals):
        raise ValueError(f"aggregate_children: con chưa kết thúc / trạng thái lạ {finals}")
    esc, rej, res = (finals.count(s) for s in (S_ESCALATED, S_REJECTED, S_RESOLVED))
    if res == len(finals):
        return S_RESOLVED, "ALL_RESOLVED"
    if esc == len(finals):
        return S_ESCALATED, "ALL_ESCALATED"
    if rej == len(finals):
        return S_REJECTED, "ALL_REJECTED"
    if res == 0:  # ESCALATED + REJECTED, không RESOLVED
        return S_ESCALATED, "MIXED"
    # có RESOLVED → cha RESOLVED; nhãn theo ưu tiên ESCALATED > REJECTED ([Đề xuất] đủ 3 loại → PARTIALLY_ESCALATED)
    return S_RESOLVED, "PARTIALLY_ESCALATED" if esc else "PARTIALLY_REJECTED"


def summary_text(view: Sequence[ChildView]) -> str:
    """Câu tổng kết theo `aggregate_status` (bảng 5.2.5) — chỉ khi mọi con đã kết thúc."""
    _, agg = aggregate_children(view)
    return SUMMARY[agg].format(n=len(view), r=sum(v.final_state == S_RESOLVED for v in view))


# ---- `children_progress` của `GET /api/tickets/{cha}` (P11 — phase5 5.2.6; DỪNG 2) ------------------------------------------------

type Progress = Literal["closed", "pending_approval", "ready", "needs_user", "processing"]
type Outcome = Literal["resolved", "escalated", "rejected"]


@dataclass(frozen=True)
class ChildProgressRow:
    """Một con theo DB (không đọc checkpoint con): `final_state`, có phiếu duyệt `pending`, có notice chưa gửi `needs ≠ none`."""

    child_id: str
    final_state: str | None
    pending_approval: bool
    ready: bool


def children_progress(
    rows: Sequence[ChildProgressRow], titles: Mapping[str, str], awaiting: Mapping[str, str] | None,
) -> list[dict[str, Any]]:  # fmt: skip
    """`[{child_id, index, title, progress, outcome}]` theo `index` (TQ-10, thứ tự xét): có `final_state` → `closed` + `outcome`
    (`S_RESOLVED`→`resolved`, `S_ESCALATED`→`escalated`, `S_REJECTED`→`rejected`); phiếu `pending` → `pending_approval`; notice chưa
    gửi `needs≠none` → `ready`; `awaiting` (cha đang ở `parent_reply_wait`, None nếu không) chứa con → `needs_user`; còn lại →
    `processing`. `outcome` = None khi chưa `closed`. `title` = `titles[child_id]` (route tính bằng `messages.child_title(seed)`)."""
    raise NotImplementedError("T20b S12")
