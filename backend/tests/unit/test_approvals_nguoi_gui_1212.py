"""Q3 (soát 12/11, agent 13 V3): thẻ duyệt cho biết AI đã gửi yêu cầu.

Trước sửa `requester` chỉ có {role, department}: người duyệt không biết ai gửi — nhất là khi người BỊ TÁC ĐỘNG khác người gửi (nhờ hộ).
Nay `requester` = {user_id, full_name, role, department}: `user_id` lấy từ ticket (phía server, không từ client), `full_name` đọc bảng
`users` như `affected.manager.full_name` (chưa có dòng → null; lỗi đọc nổi lên, không nuốt). `role`/`department` giữ nguồn cũ
(`requester_context` bản chụp B1 — đúng hợp đồng B15 §4).
"""

import pytest
from tests.fakes.desk import desk_env
from tests.unit.test_approvals_view import BACKUP, _login, _pending, _put_user, _view

pytestmark = pytest.mark.asyncio


async def test_the_duyet_co_ma_va_ho_ten_nguoi_gui() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env, requester="duc.pv")
        rc = (await env.h.runner.snapshot(ticket)).values["requester_context"]
        _put_user(env, rc.user_id, username="duc.pv", department="it", manager_id=None, full_name="Phạm Văn Đức")
        r = await _view(env, aid, await _login(env, "ha.lt"))
        assert r.status_code == 200, r.text
        assert r.json()["requester"] == {"user_id": BACKUP, "full_name": "Phạm Văn Đức", "role": "l1", "department": "it"}


async def test_chua_co_dong_users_thi_ho_ten_null() -> None:
    async with desk_env() as env:
        ticket, aid = await _pending(env)
        rc = (await env.h.runner.snapshot(ticket)).values["requester_context"]
        ha = await _login(env, "ha.lt")
        env.store.users.pop(rc.user_id, None)
        r = await _view(env, aid, ha)
        assert r.status_code == 200, r.text
        body = r.json()["requester"]
        assert (body["user_id"], body["full_name"]) == (rc.user_id, None)
        assert (body["role"], body["department"]) == (rc.role, rc.department)
