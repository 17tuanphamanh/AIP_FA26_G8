"""M1 — báo trùng yêu cầu: phần THUẦN (`domain/dedup.py`) + cấu hình (`config/dedup.yaml`).

Mọi điều kiện lọc nằm ở `pick_duplicate` (store chỉ trả TẬP CHA có thể thừa) nên mutation "bỏ điều kiện X" bắt được ở unit test, không cần
Postgres. Node B3 dùng hàm này: `test_dedup_b3.py`.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from app.domain.dedup import OpenCandidate, duplicate_text, pick_duplicate
from app.settings import DedupConfig, load_dedup
from pydantic import ValidationError

NOW = datetime(2026, 11, 8, 9, 0, tzinfo=UTC)
SINCE = NOW - timedelta(hours=24)
CONFIG = Path(__file__).resolve().parents[3] / "config"


def cand(tid: str, *, requester: str = "nv001", intent: str | None = "vpn", final: str | None = None,
         is_parent: bool = False, parent: str | None = None, age_h: float = 1.0) -> OpenCandidate:  # fmt: skip
    return OpenCandidate(ticket_id=tid, requester_id=requester, intent=intent, final_state=final, is_parent=is_parent,
                         parent_ticket_id=parent, created_at=NOW - timedelta(hours=age_h))  # fmt: skip


def pick(cands: list[OpenCandidate], **over: object) -> str | None:
    args: dict[str, object] = {"ticket_id": "me", "parent_ticket_id": None, "requester_id": "nv001", "intent": "vpn",
                               "since": SINCE}  # fmt: skip
    return pick_duplicate(cands, **{**args, **over})  # type: ignore[arg-type]


def test_same_requester_same_intent_open_in_window_matches() -> None:
    assert pick([cand("old")]) == "old"


def test_other_requester_is_not_a_duplicate() -> None:
    assert pick([cand("old", requester="nv002")]) is None


def test_other_intent_is_not_a_duplicate() -> None:
    assert pick([cand("old", intent="account")]) is None
    assert pick([cand("old", intent=None)]) is None  # chưa qua B3 → chưa có intent → không so được


def test_closed_ticket_is_not_a_duplicate() -> None:
    assert pick([cand("old", final="S_RESOLVED")]) is None
    assert pick([cand("old", final="S_ESCALATED")]) is None  # đã qua B20 (chờ L2) — "còn mở" = chưa có final_state


def test_window_start_is_inclusive_and_older_is_out() -> None:
    assert pick([cand("edge", age_h=24)]) == "edge"
    assert pick([cand("old", age_h=24.01)]) is None


def test_ignores_itself_parent_siblings_and_parent_rows() -> None:
    """Con không báo trùng với cha (và anh em cùng cha): cùng một câu gốc, không phải yêu cầu chồng."""
    assert pick([cand("me")]) is None
    assert pick([cand("P")], ticket_id="P-1", parent_ticket_id="P") is None
    assert pick([cand("P-2", parent="P")], ticket_id="P-1", parent_ticket_id="P") is None
    assert pick([cand("P", is_parent=True)], ticket_id="x") is None  # dòng cha không có intent riêng — không bao giờ là ứng viên
    assert pick([cand("P-2", parent="P")], ticket_id="x") == "P-2"  # con của ticket KHÁC thì vẫn là yêu cầu đang mở


def test_picks_newest_then_largest_id() -> None:
    assert pick([cand("a", age_h=5), cand("b", age_h=2), cand("c", age_h=9)]) == "b"
    assert pick([cand("a", age_h=2), cand("b", age_h=2)]) == "b"


def test_empty_candidates() -> None:
    assert pick([]) is None


# ---- mẫu tin ---------------------------------------------------------------------------------------------------------------

TEMPLATE = "Bạn đang có một yêu cầu {loai} đang xử lý (mã {ma}). Yêu cầu này vẫn được tiếp nhận."


@pytest.mark.parametrize(("intent", "loai"), [
    ("vpn", "VPN"), ("account", "tài khoản"), ("software", "phần mềm"), ("access", "quyền truy cập"),
])  # fmt: skip
def test_text_uses_fixed_template_with_type_and_code(intent: str, loai: str) -> None:
    assert duplicate_text(TEMPLATE, intent, "abc-123") == (
        f"Bạn đang có một yêu cầu {loai} đang xử lý (mã abc-123). Yêu cầu này vẫn được tiếp nhận."
    )  # fmt: skip


def test_text_rejects_unknown_intent() -> None:
    with pytest.raises(KeyError):
        duplicate_text(TEMPLATE, "out_of_scope", "x")


# ---- config/dedup.yaml -----------------------------------------------------------------------------------------------------


def _write(tmp_path: Path, data: dict[str, object]) -> Path:
    path = tmp_path / "dedup.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_repo_config_defaults() -> None:
    cfg = load_dedup(CONFIG / "dedup.yaml")
    assert cfg.DEDUP_WINDOW_HOURS == 24 and cfg.window == timedelta(hours=24)
    assert cfg.template == TEMPLATE


@pytest.mark.parametrize("bad", [
    {"DEDUP_WINDOW_HOURS": 0},
    {"DEDUP_WINDOW_HOURS": -1},
    {"DEDUP_WINDOW_HOURS": 24.5},
    {"DEDUP_WINDOW_HOURS": 10_000},
    {"template": "Bạn đang có yêu cầu {loai}."},  # thiếu {ma}
    {"template": "Mã {ma}."},  # thiếu {loai}
    {"template": "Loại {loai} mã {ma} {khac}"},  # placeholder lạ
    {"template": "Loại {loai} mã {ma} {0}"},
    {"khoa_la": 1},
])  # fmt: skip
def test_bad_config_is_rejected(tmp_path: Path, bad: dict[str, object]) -> None:
    good = {"DEDUP_WINDOW_HOURS": 24, "template": TEMPLATE}
    with pytest.raises((ValidationError, ValueError)):
        load_dedup(_write(tmp_path, {**good, **bad}))


def test_config_model_is_frozen() -> None:
    cfg = DedupConfig(DEDUP_WINDOW_HOURS=24, template=TEMPLATE)
    with pytest.raises(ValidationError):
        cfg.DEDUP_WINDOW_HOURS = 1  # type: ignore[misc]
