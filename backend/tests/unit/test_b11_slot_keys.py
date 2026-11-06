"""be-b11-khoa-slot — câu hỏi B11 do LLM viết không lộ tên khoá slot (ticket a162cded: "… mã máy (device_id) …").

Hàm thuần `domain/slot_text.scrub_slot_keys` + node B11 thật (ScriptedLLM, không key): dọn TRƯỚC output guard / notify / conversation; chỉ
nhánh LLM (câu cố định TARGET_QUESTION không đổi); audit chỉ số đếm `slot_keys_removed`.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from app.domain.slot_text import SLOT_LABELS, fallback_question, scrub_slot_keys
from app.domain.states import S_CLARIFYING
from app.domain.target import TARGET_QUESTION
from app.graph.nodes import b11_slots
from app.llm.providers.scripted import Reply
from tests.unit.test_target_guard import b11_state, node

CONFIG = Path(__file__).resolve().parents[3] / "config"


def _all_keys() -> set[str]:
    raw = yaml.safe_load((CONFIG / "slots.yaml").read_text(encoding="utf-8"))
    return {k for spec in raw["intents"].values() for k in [*spec.get("required", []), *spec.get("optional", [])]}


KEYS = _all_keys()


# ---- hàm thuần --------------------------------------------------------------------------------------------------------------


def test_every_known_slot_key_has_a_label() -> None:
    assert set(SLOT_LABELS) == KEYS  # thêm slot mới mà quên nhãn → đỏ
    assert all(v and "_" not in v for v in SLOT_LABELS.values())


@pytest.mark.parametrize(
    ("text", "expected", "n"),
    [
        ("Bạn cho mình xin mã máy (device_id) để kiểm tra nhé?", "Bạn cho mình xin mã máy để kiểm tra nhé?", 1),
        ("Bạn cho mình xin mã máy （device_id） nhé?", "Bạn cho mình xin mã máy nhé?", 1),
        ("Loại tài khoản nào [account_type] ?", "Loại tài khoản nào?", 1),
        ("Bạn cần quyền bao lâu (`duration`) ?", "Bạn cần quyền bao lâu?", 1),
        ("Bạn cần quyền bao lâu `duration`?", "Bạn cần quyền bao lâu?", 1),
        ("Mã máy ( device_id ) và mã lỗi (error_code) là gì?", "Mã máy và mã lỗi là gì?", 2),
        ("Cho mình xin device_id và error_code nhé.", "Cho mình xin mã máy và mã lỗi nhé.", 2),  # khoá trơn → nhãn
        ("Thư mục resource_path , mức quyền?", "Thư mục thư mục cần truy cập, mức quyền?", 1),
    ],
)
def test_scrub_removes_wrapped_and_labels_bare_keys(text: str, expected: str, n: int) -> None:
    assert scrub_slot_keys(text, KEYS, "device_id") == (expected, n)


@pytest.mark.parametrize(
    "text",
    ["Bạn cho mình xin mã máy để kiểm tra nhé?", "Mã lỗi  hiện   trên màn hình là gì ?", "device_idx và my_device_id không phải khoá"],
)
def test_text_without_keys_is_byte_identical(text: str) -> None:
    out, n = scrub_slot_keys(text, KEYS, "device_id")
    assert n == 0 and out is text


@pytest.mark.parametrize("text", ["(device_id)", " [device_id] ? ", "`error_code`."])
def test_empty_after_scrub_falls_back_to_fixed_question(text: str) -> None:
    assert scrub_slot_keys(text, KEYS, "device_id") == (fallback_question("device_id"), 1)
    assert fallback_question("device_id") == "Bạn cho mình biết thêm mã máy nhé?"
    assert fallback_question("khong_co") == "Bạn cho mình biết thêm thông tin còn thiếu nhé?"


# ---- node B11 ---------------------------------------------------------------------------------------------------------------


class RecordingGuard:
    def __init__(self) -> None:
        self.seen: list[str] = []

    def violation(self, text: str) -> str | None:
        self.seen.append(text)
        return None


async def _ask(llm_text: str, **over: Any) -> tuple[dict[str, Any], Any, RecordingGuard]:
    n = node({"b11_clarify_question": lambda _: Reply({"text": llm_text})})
    guard = RecordingGuard()
    out = await n.run("b11_slots", b11_slots, b11_state({"action": "reset_password"}, flag=False), output_guard=guard, **over)
    assert (out["status"], out["next"]) == (S_CLARIFYING, "clarify_wait"), (out.get("exit_code"), out.get("escalation_reason_detail"))
    return out, n, guard


@pytest.mark.asyncio
async def test_node_llm_question_with_key_is_scrubbed_everywhere() -> None:
    out, n, guard = await _ask("Bạn dùng loại tài khoản nào (account_type) và mã máy (device_id) nhé?")
    clean = "Bạn dùng loại tài khoản nào và mã máy nhé?"
    assert guard.seen == [clean]  # (5) guard chạy trên câu ĐÃ dọn
    assert out["conversation"][-1]["text"] == clean  # (1) conversation
    assert [t for _, t, _ in n.h.notifier.sent] == [clean]  # (1) tin gửi người dùng
    detail = n.row("B11", "asked")["detail"]
    assert detail["slot_keys_removed"] == 2 and clean not in repr(detail) and "(device_id)" not in repr(detail)  # chỉ số đếm, không chép câu


@pytest.mark.asyncio
async def test_node_question_without_key_unchanged() -> None:
    text = "Bạn dùng loại tài khoản nào: AD, email hay ERP?"
    out, n, guard = await _ask(text)
    assert guard.seen == [text] and out["conversation"][-1]["text"] == text
    assert n.row("B11", "asked")["detail"]["slot_keys_removed"] == 0


@pytest.mark.asyncio
async def test_node_empty_after_scrub_sends_fixed_question() -> None:
    out, _, _ = await _ask("(account_type)")
    assert out["conversation"][-1]["text"] == "Bạn cho mình biết thêm loại tài khoản nhé?"


@pytest.mark.asyncio
async def test_node_target_question_untouched() -> None:
    """(4) Nhánh câu cố định (cờ người khác, chưa có đích) không gọi LLM, không qua bộ dọn."""
    n = node()
    guard = RecordingGuard()
    out = await n.run("b11_slots", b11_slots, b11_state({"action": "reset_password", "account_type": "ad"}, flag=True), output_guard=guard)
    assert out["conversation"][-1]["text"] == TARGET_QUESTION and guard.seen == [TARGET_QUESTION]
    assert n.row("B11", "asked")["detail"]["slot_keys_removed"] == 0
