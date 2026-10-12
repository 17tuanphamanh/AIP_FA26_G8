"""Phase 5 T22a P7 (G5-3, phase5 mục 4.1 P7 + cuối 4.7b): 3 trường mới ở model đầu ra tool BẮT BUỘC, không mặc định — mock/AD cũ
thiếu trường → `ValidationError` (registry bọc thành `ToolContractError`), không âm thầm coi là `false` (R01/R02/R11 AUTO nhầm)."""

from typing import Any

import pytest
from app.tools.models import AccountStatus, AdUser, CatalogEntry
from pydantic import ValidationError

ACCOUNT_STATUS: dict[str, Any] = {
    "user_id": "svc_backup", "username": "svc.backup", "full_name": "Backup", "title": "Service", "department": "IT",
    "groups": ["IT-Users"], "manager_id": None, "employment_status": "active", "hired_at": "2020-01-01",
    "is_privileged_account": True, "is_service_account": True, "disable_reason": None,
    "account": {"account_type": "ad", "enabled": True, "locked": False, "lock_reason": None,
                "password_last_set": "2026-09-01T00:00:00+00:00"},
}  # fmt: skip
CATALOG: dict[str, Any] = {
    "name": "autocad", "display_name": "AutoCAD", "in_catalog": True, "license_type": "paid", "paid": True,
    "version": "2026", "requires_approval": True, "requires_local_admin": True,
}  # fmt: skip


def _without(data: dict[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in data.items() if k != key}


def test_full_outputs_validate() -> None:
    status = AccountStatus.model_validate(ACCOUNT_STATUS)
    assert (status.is_service_account, status.disable_reason) == (True, None)
    assert CatalogEntry.model_validate(CATALOG).requires_local_admin is True


@pytest.mark.parametrize("key", ["is_service_account", "disable_reason"])
def test_account_status_missing_field_rejected(key: str) -> None:
    with pytest.raises(ValidationError, match=key):
        AccountStatus.model_validate(_without(ACCOUNT_STATUS, key))


def test_catalog_entry_missing_requires_local_admin_rejected() -> None:
    with pytest.raises(ValidationError, match="requires_local_admin"):
        CatalogEntry.model_validate(_without(CATALOG, "requires_local_admin"))


def test_disable_reason_closed_set() -> None:
    with pytest.raises(ValidationError, match="disable_reason"):
        AccountStatus.model_validate({**ACCOUNT_STATUS, "disable_reason": "hacked"})


def test_ad_user_unchanged_for_b1() -> None:
    """`AdUser` (B1) không đòi 2 trường account — đặt ở `AccountStatus`, không ở `AdUser`."""
    user = AdUser.model_validate(_without(_without(ACCOUNT_STATUS, "is_service_account"), "disable_reason"))
    assert not hasattr(user, "is_service_account")
