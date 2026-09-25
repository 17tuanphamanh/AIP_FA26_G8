"""seed.json [Chốt P5 mục 7]: đủ các ca mà nhánh sau cần, hash argon2id, tham chiếu hợp lệ."""

import json
from collections import Counter

import pytest
from app.seed_model import SeedData
from app.state import SEED_PATH, load_seed
from argon2 import PasswordHasher
from pydantic import ValidationError

DEMO_PASSWORD = "Demo@2026!"  # mật khẩu demo công khai — ghi ở mock_services/README.md


@pytest.fixture(scope="module")
def seed() -> SeedData:
    return load_seed()


def test_four_employment_statuses(seed: SeedData) -> None:
    assert {u.employment_status for u in seed.users} == {"active", "probation", "disabled", "terminated"}


def test_four_ad_groups_and_one_privileged_group_per_person(seed: SeedData) -> None:
    groups = Counter(g for u in seed.users for g in u.groups)
    assert set(groups) == {"IT-Users", "IT-L1", "IT-Manager", "IT-L2"}
    assert groups["IT-L1"] >= 2  # IDOR: L1-X duyệt phiếu giao cho L1-Y (P6 test 3)
    for u in seed.users:
        assert len(set(u.groups) & {"IT-L1", "IT-Manager", "IT-L2"}) <= 1, u.user_id


def test_d15_disabled_requester_with_active_beneficiary(seed: SeedData) -> None:
    users = {u.user_id: u for u in seed.users}
    disabled = [u for u in seed.users if u.employment_status == "disabled"]
    assert any(
        users[b].employment_status == "active"
        for d in disabled
        for b in users
        if b != d.user_id and users[b].department == d.department
    )


def test_d20_user_with_registered_and_unregistered_device(seed: SeedData) -> None:
    by_owner: dict[str, set[bool]] = {}
    for d in seed.devices:
        by_owner.setdefault(d.owner_id, set()).add(d.registered)
    assert any(states == {True, False} for states in by_owner.values())


def test_scenario_variety(seed: SeedData) -> None:
    assert any(c.expires_in_days < 0 for c in seed.certs)  # TC06: cert hết hạn
    assert any(c.expires_in_days > 0 and not c.revoked for c in seed.certs)
    assert {c.license_type for c in seed.catalog} == {"free", "paid"}
    assert any(p.used < p.total for p in seed.licenses) and any(p.used == p.total for p in seed.licenses)
    assert {r.sensitivity for r in seed.resources} == {"low", "medium", "high"}
    assert any(p.expires_in_days is not None and p.expires_in_days < 0 for p in seed.permissions)
    assert any(a.locked for u in seed.users for a in u.accounts.values())
    assert any(u.is_privileged_account for u in seed.users)


def test_hashes_are_argon2id_and_verify_demo_password(seed: SeedData) -> None:
    hasher = PasswordHasher()
    assert len({u.password_hash for u in seed.users}) == len(seed.users)  # salt riêng từng người
    for u in seed.users:
        assert u.password_hash.startswith("$argon2id$")
    assert hasher.verify(seed.users[0].password_hash, DEMO_PASSWORD)


def test_broken_reference_is_rejected() -> None:
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    raw["devices"][0]["owner_id"] = "khong_ton_tai"
    with pytest.raises(ValidationError, match="tham chiếu không tồn tại"):
        SeedData.model_validate(raw)


def test_plaintext_password_is_rejected() -> None:
    raw = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    raw["users"][0]["password_hash"] = DEMO_PASSWORD
    with pytest.raises(ValidationError, match="argon2id"):
        SeedData.model_validate(raw)
