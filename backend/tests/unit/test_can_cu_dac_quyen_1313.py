"""13/11 (TA "sửa hết"): thẻ duyệt đặt lại mật khẩu / mở khoá TÀI KHOẢN DỊCH VỤ hay QUẢN TRỊ ghi căn cứ là KB-ACC-001 ("Tự đặt lại
mật khẩu tài khoản cá nhân") — sai bài. `ActionMeta.procedure_doc_privileged` (tuỳ chọn): khi fact cho biết tài khoản đích là
tài khoản dịch vụ hoặc quản trị → căn cứ là bài đó (KB-ACC-003 nói rõ tài khoản dịch vụ / quản trị luôn cần người duyệt).
Bài đặc quyền không có trong KB hiện hành → về bài thường (không chặn). Không đổi B11 (căn cứ kiểm trước khi có fact)."""

from __future__ import annotations

import pytest
from app.domain.action import ActionMeta, procedure_doc_for
from app.settings import get_action_metadata
from pydantic import ValidationError

BASE = {"reversible": True, "reversibility": "partial", "data_sensitivity": "medium", "scope": "single_account",
        "privilege_level": "standard_user", "procedure_doc": "KB-ACC-001"}  # fmt: skip


def test_metadata_reset_va_unlock_co_bai_dac_quyen() -> None:
    acc = get_action_metadata().of("account")
    assert (acc["reset_password"].procedure_doc, acc["reset_password"].procedure_doc_privileged) == ("KB-ACC-001", "KB-ACC-003")
    assert (acc["unlock_account"].procedure_doc, acc["unlock_account"].procedure_doc_privileged) == ("KB-ACC-002", "KB-ACC-003")
    assert get_action_metadata().of("vpn")["renew_vpn_cert"].procedure_doc_privileged is None  # không khai → None


@pytest.mark.parametrize(
    ("facts", "want"),
    [
        ({"target_is_service_account": True, "target_account_privilege": "admin"}, "KB-ACC-003"),  # ca svc_backup thật
        ({"target_is_service_account": True}, "KB-ACC-003"),
        ({"target_account_privilege": "admin"}, "KB-ACC-003"),
        ({"target_is_service_account": False, "target_account_privilege": "standard_user"}, "KB-ACC-001"),
        ({"target_account_privilege": "elevated"}, "KB-ACC-001"),
        ({}, "KB-ACC-001"),
        ({"target_is_service_account": "true"}, "KB-ACC-001"),  # chỉ đúng kiểu bool True — không đoán từ chuỗi
    ],
)
def test_chon_bai_theo_fact(facts: dict[str, object], want: str) -> None:
    meta = ActionMeta.model_validate({**BASE, "procedure_doc_privileged": "KB-ACC-003"})
    assert procedure_doc_for(meta, facts) == want


def test_khong_khai_bai_dac_quyen_thi_luon_bai_thuong() -> None:
    meta = ActionMeta.model_validate(BASE)
    assert procedure_doc_for(meta, {"target_is_service_account": True}) == "KB-ACC-001"


def test_bai_dac_quyen_sai_mau_doc_id_bi_tu_choi() -> None:
    with pytest.raises(ValidationError):
        ActionMeta.model_validate({**BASE, "procedure_doc_privileged": "acc-003"})
