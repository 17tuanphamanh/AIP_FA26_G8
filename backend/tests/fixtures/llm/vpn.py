"""Kịch bản ScriptedLLM dùng chung cho luồng VPN (phase3 mục 3.8, 7.5): TC02 (gia hạn chứng chỉ — `need="action"`),
TC04/TC05 (hỏi hướng dẫn — `need="info"`, câu trả lời có trích dẫn, TC05 đủ bước trải mọi khối bằng chứng), TC06
(chẩn đoán chủ động — không hỏi lại, câu yêu cầu không cần có mã thiết bị).

Mọi bước là HÀM của biến đã render (không phải hàng đợi) → gọi lại bao nhiêu lần cũng được, đầu ra suy từ đầu vào như
một LLM "ngoan": slot chỉ lấy đúng chữ người dùng viết (3-Q1), trích dẫn đúng `anchor_chunk_id` của bằng chứng. Ghi đè
từng prompt bằng `overrides` (vd. `b10_answer=[BadJSON("x"), Reply({...})]`). 3f/3g/3h dùng và mở rộng.
"""

import re
from collections.abc import Mapping
from typing import Any, Literal

from app.llm.providers.scripted import Reply, Script, Step

DEVICE_ID = re.compile(r"\b[A-Z]{2,4}-\d{3,5}\b")  # cùng mẫu value_rules.device_id (phase3 mục 3.2)


def _field(item: Any, name: str) -> Any:
    return item[name] if isinstance(item, Mapping) else getattr(item, name)


def vpn_scripts(
    *, need: Literal["action", "info"] = "action", action: str = "renew_vpn_cert", **overrides: Script
) -> dict[str, Script]:
    def judge(_: Mapping[str, Any]) -> Step:
        return Reply({"is_attack": False, "category": "none", "reason": "yêu cầu hỗ trợ VPN bình thường"})

    def classify(v: Mapping[str, Any]) -> Step:
        text = str(v["redacted_request"])
        found = DEVICE_ID.search(text)
        item = {"type": "vpn", "confidence": 0.92, "span": text[:500],
                "action_hint": action if need == "action" else None,
                "slots": {"device_id": found.group(0)} if found else {}}  # fmt: skip
        return Reply({"intents": [item], "is_multi": False})

    def need_type(_: Mapping[str, Any]) -> Step:
        return Reply({"type": need, "confidence": 0.9})

    def answer(v: Mapping[str, Any]) -> Step:
        evidence = list(v["evidence"] or [])
        if not evidence:
            return Reply({"answer_markdown": "", "citations": [], "cannot_answer": True})
        anchors = [str(_field(e, "anchor_chunk_id")) for e in evidence]
        steps = [f"Bước {i + 1}: làm theo mục «{_field(e, 'heading_path')}»" for i, e in enumerate(evidence)]
        return Reply({"answer_markdown": "Bạn làm theo các bước dưới đây.", "citations": anchors, "steps": steps,
                      "cannot_answer": False})  # fmt: skip

    def clarify(_: Mapping[str, Any]) -> Step:
        return Reply({"text": "Bạn cho mình xin mã thiết bị (ví dụ LAP-0342) để kiểm tra chứng chỉ VPN nhé."})

    def extract(v: Mapping[str, Any]) -> Step:
        found = DEVICE_ID.search(str(v["text"]))
        if found and "device_id" in list(v["missing"]):
            return Reply({"slots": {"device_id": found.group(0)}, "off_topic": False})
        return Reply({"slots": {}, "off_topic": True})

    scripts: dict[str, Script] = {
        "b02_injection_judge": judge, "b03_classify": classify, "b10_need_type": need_type, "b10_answer": answer,
        "b11_clarify_question": clarify, "b11_extract_slots": extract,
    }  # fmt: skip
    scripts.update(overrides)
    return scripts
