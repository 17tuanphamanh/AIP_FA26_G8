"""`domain/approval.py` — chọn người duyệt B15 (Phase 4 chặng 4b; phase4 mục 3.1, 3.2, 5.1 P1–P4, 5.3 b1). Viết TỪ ĐẶC TẢ, trước code.

- b1: `conflict_type` thuần — 3 loại + thứ tự ưu tiên `self` → `boss_of_approver` → `targets_approver`; chain rỗng; action None.
  `manager_chain` (Q-4-R, P4): ≤ 5 cấp, chặn vòng, dừng khi không có sếp, lỗi tra lan ra.
- P2: `invalid_reason`/`valid` trên AD THẬT của seed (`tests/fakes/ad_seed.py` đọc `mock_services/seed.json`): `probation` không duyệt được;
  không tìm thấy = `not_found` (không phải lỗi); thứ tự kiểm not_found → inactive → wrong_group. P6: `action_has_device_target`.
- `memo_lookup`: mỗi người tra AD tối đa MỘT lần trong một lần chạy node (P3 "cache trong một lần chạy node").
- Bảng 3.2 ở mức `choose_approver` (x1–x4, x7, x8, x10, x11) + ca thêm cho luật `rejected`/backup. x5, x6: `test_hrule_4b_owner.py`;
  x9 (lỗi AD → E2) ở mức hàm: `choose_approver` NÉM `ApproverLookupError` (M-4b-5 "lỗi AD coi như không hợp lệ" phải đỏ ở đây);
  x12–x14b cần node thật (DỪNG 2).
- P1: `Roster` — khoá lạ, id sai mẫu `^[a-z0-9_]{3,64}$`, trùng id → `ValidationError`.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from app.domain.action import Action, FactValue
from app.domain.approval import (
    MAX_CHAIN_DEPTH,
    ApproverLookupError,
    Choice,
    Refuse,
    Rejected,
    Roster,
    action_has_device_target,
    choose_approver,
    conflict_type,
    invalid_reason,
    manager_chain,
    memo_lookup,
    valid,
)
from app.settings import get_action_metadata
from app.tools.models import AdUser
from pydantic import ValidationError
from tests.fakes.ad_seed import seed_ad_records

if TYPE_CHECKING:  # chỉ cho mypy — tên kiểu theo giao diện ghi trong lời giao 4b
    from app.domain.approval import ApproverRole, RejectReason

NOW = datetime(2026, 9, 29, 3, 0, tzinfo=UTC)  # thứ Ba 10:00 giờ VN — không ảnh hưởng chọn người duyệt
META = get_action_metadata().of("vpn")
ROSTER = Roster(primary="l1_01", backup="l1_02", head="it_mgr01")  # config/approvers.yaml (P1)


class Boom(Exception):
    """Lỗi hệ thống giả của `fetch_manager` — không trùng lớp nào của mã sản phẩm (kể cả NotImplementedError)."""


def _action(
    requested_for: str, device_id: str, *, registered: bool = False, owner: bool = True,
    action_type: str = "renew_vpn_cert",
) -> Action:  # fmt: skip
    """Như `test_policy_rules_vpn.py::_action`: thuộc tính rủi ro từ `config/action_metadata.yaml`, đích `device:{id}`."""
    m = META[action_type]
    facts: dict[str, FactValue] = {"device_registered": registered, "device_owner_is_requester": owner}
    return Action(
        type=action_type, target=f"device:{device_id}", requested_for=requested_for, scope=m.scope,
        privilege_level=m.privilege_level, reversible=m.reversible, reversibility=m.reversibility,
        data_sensitivity=m.data_sensitivity, params={"device_id": device_id}, facts=facts,
    )  # fmt: skip


def _seed_users(status: Mapping[str, str] | None = None) -> dict[str, AdUser]:
    """AD của seed (JSON y như `GET /ad/users/{id}` của mock), `status` = `/_admin/users/{id}/status`."""
    records = {r["user_id"]: r for r in seed_ad_records(NOW)}
    for uid, st in (status or {}).items():
        records[uid] = {**records[uid], "employment_status": st,
                        "account": {**records[uid]["account"], "enabled": st not in ("disabled", "terminated")}}  # fmt: skip
    return {uid: AdUser.model_validate(r) for uid, r in records.items()}


SEED = _seed_users()


class SeedLookup:
    """`lookup` của `choose_approver` trên AD seed — đếm ở NƠI NHẬN theo người (quy ước 3.9). `fail` → `ApproverLookupError`
    (lỗi hệ thống sau retry, khác "không tìm thấy" = None)."""

    def __init__(self, status: Mapping[str, str] | None = None, fail: Sequence[str] = ()) -> None:
        self.users = _seed_users(status)
        self.fail = set(fail)
        self.calls: Counter[str] = Counter()

    async def __call__(self, user_id: str) -> AdUser | None:
        self.calls[user_id] += 1
        if user_id in self.fail:
            raise ApproverLookupError(user_id)
        return self.users.get(user_id)


# ---- b1: conflict_type ------------------------------------------------------------------------------------------------

CHAIN_L1_01 = ("l1_lead", "it_mgr01")  # seed sau P14: l1_01 → l1_lead → it_mgr01


@pytest.mark.parametrize(
    ("requester", "cand", "chain", "action", "expected"),
    [
        pytest.param("l1_01", "l1_01", (), None, "self", id="self"),
        pytest.param("l1_lead", "l1_01", CHAIN_L1_01, None, "boss_of_approver", id="boss-truc-tiep"),
        pytest.param("it_mgr01", "l1_01", CHAIN_L1_01, None, "boss_of_approver", id="boss-chuoi-2-cap-Q-4-R"),
        pytest.param("nv003", "l1_01", CHAIN_L1_01, _action("l1_01", "LAP-0501"), "targets_approver", id="targets"),
        pytest.param("nv003", "l1_01", CHAIN_L1_01, _action("nv003", "LAP-0501"), None, id="khong-xung-dot"),
        pytest.param("l1_lead", "l1_01", (), None, None, id="chain-rong-khong-boss"),
        pytest.param("nv003", "l1_01", (), None, None, id="action-none"),
        pytest.param("l1_01", "l1_01", ("l1_01",), None, "self", id="uu-tien-self-hon-boss"),
        pytest.param("l1_01", "l1_01", (), _action("l1_01", "PC-0124"), "self", id="uu-tien-self-hon-targets"),
        pytest.param("l1_lead", "l1_01", ("l1_lead",), _action("l1_01", "LAP-0700"), "boss_of_approver",
                     id="uu-tien-boss-hon-targets"),
    ],
)  # fmt: skip
def test_b1_conflict_type(
    requester: str, cand: str, chain: tuple[str, ...], action: Action | None, expected: str | None
) -> None:
    """b1 (phase4 5.3; P4): hàm thuần, thứ tự `self` → `boss_of_approver` (requester ∈ chain) → `targets_approver`
    (`action.requested_for == cand`) → None."""
    assert conflict_type(requester, cand, chain, action) == expected


# ---- b1: manager_chain (Q-4-R, P4) ------------------------------------------------------------------------------------


def _fetch(graph: Mapping[str, str | None], fail: str | None = None) -> Any:
    async def fetch(uid: str) -> str | None:
        if uid == fail:
            raise Boom(uid)
        return graph.get(uid)

    return fetch


def test_b1_max_chain_depth_is_5() -> None:
    assert MAX_CHAIN_DEPTH == 5  # Q-4-R: ≤ 5 cấp


@pytest.mark.asyncio
async def test_b1_manager_chain_one_level_stops_when_no_boss() -> None:
    assert await manager_chain("l1_02", "it_mgr01", _fetch({"it_mgr01": None})) == ("it_mgr01",)


@pytest.mark.asyncio
async def test_b1_manager_chain_seed_l1_01_two_levels() -> None:
    fetch = _fetch({"l1_lead": "it_mgr01", "it_mgr01": None})
    assert await manager_chain("l1_01", "l1_lead", fetch) == ("l1_lead", "it_mgr01")


@pytest.mark.asyncio
async def test_b1_manager_chain_no_first_manager_is_empty() -> None:
    assert await manager_chain("it_mgr01", None, _fetch({})) == ()


@pytest.mark.asyncio
async def test_b1_manager_chain_exactly_5_levels() -> None:
    graph: dict[str, str | None] = {"m1": "m2", "m2": "m3", "m3": "m4", "m4": "m5", "m5": None}
    assert await manager_chain("u", "m1", _fetch(graph)) == ("m1", "m2", "m3", "m4", "m5")


@pytest.mark.asyncio
async def test_b1_manager_chain_cut_at_5_levels() -> None:
    graph: dict[str, str | None] = {f"m{i}": f"m{i + 1}" for i in range(1, 9)}  # m1 → … → m9, sâu 8+
    chain = await manager_chain("u", "m1", _fetch(graph))
    assert chain == ("m1", "m2", "m3", "m4", "m5")
    assert len(chain) == MAX_CHAIN_DEPTH


@pytest.mark.asyncio
async def test_b1_manager_chain_cycle_between_managers_stops_without_repeat() -> None:
    """Vòng A → B → A: dừng, id lặp KHÔNG đưa vào."""
    assert await manager_chain("u", "a", _fetch({"a": "b", "b": "a"})) == ("a", "b")


@pytest.mark.asyncio
async def test_b1_manager_chain_cycle_back_to_user_stops() -> None:
    """Vòng quay về chính `user_id`: dừng, `user_id` không nằm trong chuỗi của chính mình."""
    assert await manager_chain("u", "a", _fetch({"a": "b", "b": "u", "u": "a"})) == ("a", "b")


@pytest.mark.asyncio
async def test_b1_manager_chain_self_as_first_manager_is_empty() -> None:
    """[Suy luận] `first_manager_id == user_id` (AD tự trỏ) → vòng ngay cấp đầu → chuỗi rỗng."""
    assert await manager_chain("u", "u", _fetch({"u": "u"})) == ()


@pytest.mark.asyncio
async def test_b1_manager_chain_fetch_error_propagates() -> None:
    """P4: tra lỗi giữa chừng → lỗi lan ra (B15 → E2), không coi như hết chuỗi."""
    with pytest.raises(Boom):
        await manager_chain("l1_01", "l1_lead", _fetch({"l1_lead": "it_mgr01", "it_mgr01": None}, fail="l1_lead"))


# ---- P2: invalid_reason / valid trên AD seed; P6: action_has_device_target -------------------------------------------


@pytest.mark.parametrize(
    ("user_id", "role", "expected"),
    [
        pytest.param("l1_01", "l1", None, id="l1_01-l1-hop-le"),
        pytest.param("l1_02", "l1", None, id="l1_02-l1-hop-le"),
        pytest.param("l1_lead", "l1", None, id="l1_lead-l1-hop-le"),
        pytest.param("l1_01", "manager", "wrong_group", id="l1_01-manager-wrong_group"),
        pytest.param("it_mgr01", "manager", None, id="it_mgr01-manager-hop-le"),
        pytest.param("it_mgr01", "l1", "wrong_group", id="it_mgr01-l1-wrong_group"),
        pytest.param("l2_01", "l1", "wrong_group", id="l2_01-l1-wrong_group-L2-khong-duyet"),
        pytest.param("l2_01", "manager", "wrong_group", id="l2_01-manager-wrong_group"),
        pytest.param("nv001", "l1", "wrong_group", id="nv001-employee-wrong_group"),
        pytest.param("nv003", "l1", "inactive", id="nv003-probation-inactive"),
        pytest.param("nv003", "manager", "inactive", id="nv003-probation-inactive-truoc-wrong_group"),
        pytest.param("nv004", "l1", "inactive", id="nv004-disabled-inactive"),
        pytest.param("nv006", "l1", "inactive", id="nv006-terminated-inactive"),
    ],
)  # fmt: skip
def test_p2_invalid_reason_on_seed_ad(user_id: str, role: "ApproverRole", expected: str | None) -> None:
    """P2: hợp lệ ⟺ `employment_status == "active"` và `role_from_groups(groups) == role`; probation không duyệt được;
    thứ tự kiểm not_found → inactive → wrong_group."""
    ad = SEED[user_id]
    assert invalid_reason(ad, role) == expected
    assert valid(ad, role) is (expected is None)


def test_p2_not_found_is_invalid_not_error() -> None:
    assert invalid_reason(None, "l1") == "not_found"
    assert invalid_reason(None, "manager") == "not_found"
    assert valid(None, "l1") is False


@pytest.mark.parametrize("status", ["probation", "disabled", "terminated"])
def test_p2_l1_not_active_is_inactive_even_with_right_group(status: str) -> None:
    ad = _seed_users({"l1_01": status})["l1_01"]
    assert invalid_reason(ad, "l1") == "inactive"
    assert invalid_reason(ad, "manager") == "inactive"  # inactive kiểm trước wrong_group
    assert valid(ad, "l1") is False


def test_p2_two_privileged_groups_is_wrong_group() -> None:
    """`role_from_groups` trả None (hơn 1 nhóm đặc quyền) ≠ role nào → wrong_group (fail-closed)."""
    raw = {**next(r for r in seed_ad_records(NOW, ["l1_01"])), "groups": ["IT-Users", "IT-L1", "IT-Manager"]}
    ad = AdUser.model_validate(raw)
    assert invalid_reason(ad, "l1") == "wrong_group"
    assert invalid_reason(ad, "manager") == "wrong_group"


def test_p6_action_has_device_target() -> None:
    assert action_has_device_target(_action("nv003", "LAP-0501")) is True
    base = _action("nv003", "LAP-0501")
    for target in ("user:nv001", "folder:finance/Q3", "DEVICE:LAP-0501", "xdevice:LAP-0501", "LAP-0501"):
        assert action_has_device_target(base.model_copy(update={"target": target})) is False, target


# ---- memo_lookup (P3: một người tra một lần trong một lần chạy node) ---------------------------------------------------


@pytest.mark.asyncio
async def test_p3_memo_lookup_calls_origin_once_per_user() -> None:
    origin = SeedLookup()
    memo = memo_lookup(origin)
    first = await memo("l1_01")
    second = await memo("l1_01")
    assert first is not None and second is not None and first.user_id == second.user_id == "l1_01"
    assert origin.calls["l1_01"] == 1


@pytest.mark.asyncio
async def test_p3_memo_lookup_remembers_not_found() -> None:
    origin = SeedLookup()
    memo = memo_lookup(origin)
    assert await memo("khong_co") is None
    assert await memo("khong_co") is None
    assert origin.calls["khong_co"] == 1


@pytest.mark.asyncio
async def test_p3_memo_lookup_does_not_remember_errors() -> None:
    origin = SeedLookup(fail=["l1_02"])
    memo = memo_lookup(origin)
    with pytest.raises(ApproverLookupError):
        await memo("l1_02")
    origin.fail.clear()  # AD hồi lại
    again = await memo("l1_02")
    assert again is not None and again.user_id == "l1_02"
    assert origin.calls["l1_02"] == 2


# ---- Bảng 3.2 ở mức choose_approver ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ca:
    requester: str
    action: Action
    approver: str | None  # None = Refuse
    backup: str | None = None
    conflict_type: str | None = None
    reason: str = "normal"
    rejected: tuple[tuple[str, "RejectReason"], ...] = ()
    status: dict[str, str] = field(default_factory=dict)
    roster: Roster = field(default_factory=lambda: ROSTER)


# fmt: off
BANG_3_2 = [
    pytest.param(Ca("nv003", _action("nv003", "LAP-0501", registered=True), "l1_01", "l1_02"),
                 id="x1-nv003-LAP0501-l1_01-backup-l1_02-normal"),
    pytest.param(Ca("l1_01", _action("l1_01", "PC-0124"), "it_mgr01", None, "self", "conflict",
                    rejected=(("l1_01", "self"),)),
                 id="x2-TC19-l1_01-tu-gui-self-truong-BP"),
    pytest.param(Ca("l1_lead", _action("l1_lead", "LAP-0700"), "it_mgr01", None, "boss_of_approver", "conflict",
                    rejected=(("l1_01", "boss_of_approver"),)),
                 id="x3-l1_lead-sep-truc-tiep-truong-BP"),
    pytest.param(Ca("it_mgr01", _action("it_mgr01", "LAP-0900"), None,
                    rejected=(("l1_01", "boss_of_approver"), ("it_mgr01", "self"))),
                 id="x4-it_mgr01-sep-chuoi-roi-head-self-Refuse"),
    pytest.param(Ca("nv003", _action("nv003", "LAP-0501", registered=True), "l1_02", "it_mgr01",
                    rejected=(("l1_01", "inactive"),), status={"l1_01": "disabled"}),
                 id="x7-l1_01-disabled-l1_02-backup-it_mgr01"),
    pytest.param(Ca("nv003", _action("nv003", "LAP-0501", registered=True), "it_mgr01", None, None, "no_valid_l1",
                    rejected=(("l1_01", "inactive"), ("l1_02", "inactive")),
                    status={"l1_01": "disabled", "l1_02": "disabled"}),
                 id="x8-het-L1-hop-le-truong-BP-no_valid_l1"),
    pytest.param(Ca("nv003", _action("nv003", "LAP-0501", registered=True), "l1_02", "it_mgr01",
                    rejected=(("l2_01", "wrong_group"),),
                    roster=Roster(primary="l2_01", backup="l1_02", head="it_mgr01")),
                 id="x10-primary-l2_01-wrong_group-L2-khong-duyet"),
    pytest.param(Ca("nv003", _action("l1_01", "LAP-0501", registered=True), "it_mgr01", None, "targets_approver",
                    "conflict", rejected=(("l1_01", "targets_approver"),)),
                 id="x11-requested_for-l1_01-targets_approver"),
]

# Ca thêm cho luật `rejected`/backup (mục 3.1 dòng `backup = next(...)` và nhánh head làm backup) + P2.
THEM = [
    pytest.param(Ca("l1_02", _action("l1_02", "PC-0200"), "l1_01", "it_mgr01", rejected=(("l1_02", "self"),)),
                 id="backup-L1-tu-gui-bi-loai-self-head-lam-backup"),
    pytest.param(Ca("nv003", _action("nv003", "LAP-0501", registered=True), "l1_01", None,
                    rejected=(("l1_02", "inactive"), ("it_mgr01", "inactive")),
                    status={"l1_02": "disabled", "it_mgr01": "disabled"}),
                 id="backup-head-khong-hop-le-backup-None"),
    pytest.param(Ca("nv003", _action("it_mgr01", "LAP-0501", registered=True), "l1_01", None,
                    rejected=(("l1_02", "inactive"), ("it_mgr01", "targets_approver")),
                    status={"l1_02": "disabled"}),
                 id="backup-head-xung-dot-targets-backup-None"),
    pytest.param(Ca("nv003", _action("nv003", "LAP-0501", registered=True), None,
                    rejected=(("l1_01", "inactive"), ("l1_02", "inactive"), ("it_mgr01", "inactive")),
                    status={"l1_01": "disabled", "l1_02": "disabled", "it_mgr01": "disabled"}),
                 id="het-L1-head-disabled-Refuse"),
    pytest.param(Ca("nv003", _action("it_mgr01", "LAP-0501", registered=True), None,
                    rejected=(("l1_01", "inactive"), ("l1_02", "inactive"), ("it_mgr01", "targets_approver")),
                    status={"l1_01": "disabled", "l1_02": "disabled"}),
                 id="het-L1-head-targets-Refuse"),
    pytest.param(Ca("nv003", _action("nv003", "LAP-0501", registered=True), "l1_02", "it_mgr01",
                    rejected=(("ghost_l1", "not_found"),),
                    roster=Roster(primary="ghost_l1", backup="l1_02", head="it_mgr01")),
                 id="P2-primary-khong-co-trong-AD-not_found-khong-phai-loi"),
    pytest.param(Ca("nv003", _action("nv003", "LAP-0501", registered=True), "l1_02", "it_mgr01",
                    rejected=(("l1_01", "inactive"),), status={"l1_01": "probation"}),
                 id="P2-l1_01-probation-khong-duyet"),
]
# fmt: on


def _check_choice(result: "Choice[Any] | Refuse", ca: Ca) -> None:
    expected_rejected = tuple(Rejected(u, r) for u, r in ca.rejected)
    if ca.approver is None:
        assert isinstance(result, Refuse), result
        assert result.reason_detail == "no_valid_approver"
        assert result.rejected == expected_rejected
        return
    assert isinstance(result, Choice), result
    assert result.approver.user_id == ca.approver
    assert (result.backup.user_id if result.backup is not None else None) == ca.backup
    assert result.conflict_type == ca.conflict_type
    assert result.conflict_detected is (ca.conflict_type is not None)
    assert result.reason == ca.reason
    assert result.rejected == expected_rejected
    assert tuple(u.user_id for u in result.to_sync) == tuple(x for x in (ca.approver, ca.backup) if x is not None)


@pytest.mark.asyncio
@pytest.mark.parametrize("ca", BANG_3_2 + THEM)
async def test_x_table_3_2_choose_approver(ca: Ca) -> None:
    """Bảng 3.2 (phase4) mức hàm + Q-4-L: xung đột → Trưởng BP (không phải dự phòng — M-4b-1); Trưởng BP cũng xung đột/không
    hợp lệ → Refuse (M-4b-2); `boss_of_approver` theo chuỗi (M-4b-3); `valid` kiểm trạng thái (M-4b-4). Mỗi người tra AD ≤ 1 lần."""
    lookup = SeedLookup(ca.status)
    result = await choose_approver(ca.roster, ca.requester, ca.action, lookup)
    _check_choice(result, ca)
    assert lookup.calls and max(lookup.calls.values()) == 1, lookup.calls


def test_x_table_has_all_rows() -> None:
    """Quy ước 3.9: bảng tham số hoá không rỗng — đủ 8 dòng bảng 3.2 ở mức hàm (x1–x4, x7, x8, x10, x11)."""
    ids = [p.id for p in BANG_3_2]
    assert len(ids) == len(set(ids)) == 8
    assert {str(i).split("-")[0] for i in ids} == {"x1", "x2", "x3", "x4", "x7", "x8", "x10", "x11"}


# ---- x9 mức hàm: lỗi AD → NÉM, không Refuse/Choice (M-4b-5) -------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fail", "status"),
    [
        pytest.param("l1_01", {}, id="primary"),
        pytest.param("l1_02", {}, id="backup"),
        pytest.param("l1_lead", {}, id="giua-chuoi-quan-ly-cua-l1_01"),
        pytest.param("it_mgr01", {"l1_01": "disabled", "l1_02": "disabled"}, id="truong-BP"),
    ],
)
async def test_x9_lookup_error_raises_not_invalid(fail: str, status: dict[str, str]) -> None:
    """x9 / P2 / P4: lỗi hệ thống khi tra người duyệt (kể cả giữa chuỗi quản lý) → `ApproverLookupError` lan ra (node → E2
    `approver_lookup_error`); KHÔNG được coi người đó là "không hợp lệ" rồi chọn người khác (M-4b-5)."""
    lookup = SeedLookup(status, fail=[fail])
    with pytest.raises(ApproverLookupError):
        await choose_approver(ROSTER, "nv003", _action("nv003", "LAP-0501", registered=True), lookup)
    assert lookup.calls[fail] == 1


# ---- P1: Roster ----------------------------------------------------------------------------------------------------


def test_p1_roster_valid_loads() -> None:
    r = Roster.model_validate({"primary": "l1_01", "backup": "l1_02", "head": "it_mgr01"})
    assert (r.primary, r.backup, r.head) == ("l1_01", "l1_02", "it_mgr01")


@pytest.mark.parametrize(
    "raw",
    [
        pytest.param({"primary": "l1_01", "backup": "l1_02", "head": "it_mgr01", "note": "x"}, id="khoa-la"),
        pytest.param({"primary": "l1_01", "backup": "l1_02"}, id="thieu-head"),
        pytest.param({"primary": "L1_01", "backup": "l1_02", "head": "it_mgr01"}, id="chu-hoa"),
        pytest.param({"primary": "l1", "backup": "l1_02", "head": "it_mgr01"}, id="ngan-hon-3"),
        pytest.param({"primary": "l1-01", "backup": "l1_02", "head": "it_mgr01"}, id="dau-gach-ngang"),
        pytest.param({"primary": "l1_01", "backup": "l1_02", "head": "a" * 65}, id="dai-hon-64"),
        pytest.param({"primary": "", "backup": "l1_02", "head": "it_mgr01"}, id="rong"),
        pytest.param({"primary": "l1_01 ", "backup": "l1_02", "head": "it_mgr01"}, id="dau-cach"),
        pytest.param({"primary": "l1_01", "backup": "l1_01", "head": "it_mgr01"}, id="trung-primary-backup"),
        pytest.param({"primary": "l1_01", "backup": "l1_02", "head": "l1_02"}, id="trung-backup-head"),
        pytest.param({"primary": "it_mgr01", "backup": "l1_02", "head": "it_mgr01"}, id="trung-primary-head"),
    ],
)
def test_p1_roster_rejects_bad(raw: dict[str, Any]) -> None:
    """P1: `extra=forbid`; mỗi id khớp `^[a-z0-9_]{3,64}$`; 3 id khác nhau."""
    with pytest.raises(ValidationError):
        Roster.model_validate(raw)


def test_p1_roster_boundary_lengths_accepted() -> None:
    r = Roster(primary="abc", backup="a" * 64, head="it_mgr01")
    assert (len(r.primary), len(r.backup)) == (3, 64)
