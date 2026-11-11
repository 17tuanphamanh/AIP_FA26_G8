"""Tài khoản dịch vụ BÊN NGOÀI công ty (kiểm thử máy demo 12/11 03:10, LLM thật).

Đo được: lan.dt "Đặt lại mật khẩu Gmail cá nhân giúp chị" → B3 xếp `account` (`account_type=email`) → R01 tự làm → hệ thống đặt lại
mật khẩu email CÔNG TY của chị (mật khẩu tạm gửi qua email). Facebook / Zalo thì LLM đã tự xếp ngoài phạm vi.

Hợp đồng:
- `personal_account_mentioned` THUẦN, tất định, chỉ xét khi có intent `account`; chỉ nhận TÊN dịch vụ ngoài, không nhận "tài khoản cá
  nhân" (KB-ACC-001: là tài khoản công ty của chính người dùng) hay "Outlook" trần (ứng dụng thư công ty).
- B3: khớp → E1 `out_of_scope` (event `intent_out_of_scope`, cờ audit `personal_account`), KHÔNG tới B6/B11, không hành động.
- clarify_wait: câu TRẢ LỜI khớp (bot hỏi "Windows, email hay ERP?" → "Gmail cá nhân") → E1 `out_of_scope`, không gọi LLM trích slot.
"""

from typing import Any

import pytest
from app.domain.personal_account import personal_account_mentioned
from app.domain.states import S_ESCALATED
from app.llm.providers.scripted import Reply
from tests.unit.test_b03_classify import _run, item, out

ACC = {"account"}

POSITIVE = [
    "Đặt lại mật khẩu Gmail cá nhân giúp chị",
    "em quên mật khẩu gmail rồi, reset giúp em",
    "Tài khoản Zalo của em bị khoá, mở giúp em",
    "Em quên mật khẩu Facebook, đặt lại giúp em",
    "reset mk yahoo giup e",
    "mở khoá Apple ID giúp em",
    "đổi mật khẩu iCloud cho em",
    "tai khoan zalo cua em bi khoa",
    "quên mật khẩu internet banking",
    "reset pass hotmail",
]

NEGATIVE = [
    "Đặt lại mật khẩu tài khoản cá nhân của em",  # KB-ACC-001: tài khoản công ty của chính mình
    "Quên mật khẩu email",
    "Outlook không đăng nhập được, đặt lại mật khẩu email giúp em",
    "quen mk ad r reset giup e",
    "tk ad cua e bi khoa r, mo giup e voi",
    "Đặt lại mật khẩu ERP, em cần làm uỷ nhiệm chi ngân hàng gấp",
    "Tài khoản email công ty bị khoá, mở giúp em",
]


@pytest.mark.parametrize("text", POSITIVE)
def test_detects_external_services(text: str) -> None:
    assert personal_account_mentioned(text, ACC)


@pytest.mark.parametrize("text", NEGATIVE)
def test_company_accounts_not_flagged(text: str) -> None:
    assert not personal_account_mentioned(text, ACC)


@pytest.mark.parametrize("intents", [set(), {"vpn"}, {"software"}, {"access"}, {"it_help"}])
def test_only_account_intent(intents: set[str]) -> None:
    """Chỉ intent `account` đặt lại / mở khoá tài khoản; "cài Zalo lên máy" (software) không phải tài khoản cá nhân."""
    assert not personal_account_mentioned("Cài Zalo lên máy LAP-0342 giúp em", intents)


# ---- B3 qua graph --------------------------------------------------------------------------------------------------------------

GMAIL = "Đặt lại mật khẩu Gmail cá nhân giúp chị"


@pytest.mark.asyncio
async def test_b3_gmail_out_of_scope_without_reset() -> None:
    """LLM (giả) xếp như đo trên máy demo: account + reset_password + email → B3 vẫn chuyển E1 ngoài phạm vi, không B6/B11."""
    v, row, h, _gw = await _run(lambda _: out(item("account", 0.95, span=GMAIL, action="reset_password",
                                                  slots={"account_type": "email"})), text=GMAIL)  # fmt: skip
    assert (v["status"], v["exit_code"], v["escalation_reason_detail"]) == (S_ESCALATED, "E1", "out_of_scope")
    assert (row["step"], row["event"]) == ("B4", "intent_out_of_scope")
    assert row["detail"]["personal_account"] is True
    assert GMAIL not in repr(row["detail"])  # chỉ cờ, không chữ người dùng
    assert v.get("intended_action") is None
    assert not [r for r in h.audit.rows if r["step"] in ("B6", "B11", "B12")]


@pytest.mark.asyncio
async def test_b3_company_email_unchanged() -> None:
    v, row, _h, _gw = await _run(lambda _: out(item("account", 0.95, span="Quên mật khẩu email", action="reset_password",
                                                   slots={"account_type": "email"})), text="Quên mật khẩu email")  # fmt: skip
    assert v.get("escalation_reason_detail") != "out_of_scope"
    assert row["detail"]["personal_account"] is False


# ---- clarify_wait --------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarify_reply_gmail_out_of_scope_without_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bot hỏi "Windows, email hay ERP?" → người dùng trả "Gmail cá nhân của em" → không để LLM trích `account_type=email`."""
    from app.graph.nodes import clarify_wait
    from tests.unit.test_target_guard import clarify_state, node

    n = node({"b11_extract_slots": lambda _: Reply({"slots": {"account_type": "email"}, "off_topic": False})})
    monkeypatch.setattr(clarify_wait, "interrupt", lambda _: {"kind": "user_reply", "text": "Gmail cá nhân của em"})
    st = clarify_state(["account_type"], {"action": "reset_password"})
    res: dict[str, Any] = await n.run("clarify_wait", clarify_wait, st)
    assert (res["status"], res["exit_code"], res["escalation_reason_detail"]) == (S_ESCALATED, "E1", "out_of_scope")
    assert n.gw.llm.calls_for("b11_extract_slots") == []
    assert any(m.get("role") == "user" and "Gmail" in m["text"] for m in res["conversation"])


@pytest.mark.asyncio
async def test_clarify_reply_company_email_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.graph.nodes import clarify_wait
    from tests.unit.test_target_guard import clarify_state, node

    n = node({"b11_extract_slots": lambda _: Reply({"slots": {"account_type": "email"}, "off_topic": False})})
    monkeypatch.setattr(clarify_wait, "interrupt", lambda _: {"kind": "user_reply", "text": "email công ty ạ"})
    st = clarify_state(["account_type"], {"action": "reset_password"})
    res: dict[str, Any] = await n.run("clarify_wait", clarify_wait, st)
    assert res.get("escalation_reason_detail") != "out_of_scope"
    assert len(n.gw.llm.calls_for("b11_extract_slots")) == 1
