"""Q13b (D-79, 11/11, bản nộp main) — "hỏi tiếp" sau khi ticket đã kết thúc: ngữ cảnh CÓ CẤU TRÚC của ticket trước.

Người dùng mở ô "Hỏi tiếp về yêu cầu này" trên ticket ĐÃ kết thúc của chính mình → API tạo ticket MỚI kèm `follows_ticket_id`. Ticket mới
chạy ĐỦ B1→B20 như mọi ticket (mọi phiếu duyệt / quyền của ticket cũ KHÔNG có hiệu lực). Thứ duy nhất mang sang là MỘT dòng gợi ý dựng
TỪ CỘT ĐÓNG của dòng `tickets` cũ (`intent`, kết quả cuối) — KHÔNG chép câu người dùng, KHÔNG chép câu bot, KHÔNG slot (mã máy, người
đích…): L-03 — đối tượng của ticket mới chỉ lấy từ câu người dùng gõ ở ticket mới.

Dòng gợi ý đi vào biến `label_hint` có sẵn của `b03_classify` ("Gợi ý nhãn (nếu có) chỉ để tham khảo") — không đổi prompt, không đổi
hợp đồng LLM. Câu ngắn "vẫn chưa được" nhờ đó được phân loại theo việc trước thay vì hỏi phân loại lại.
"""

from dataclasses import dataclass
from typing import Final

from app.domain.intents import IT_HELP

# Nhãn loại việc — CHỈ các intent đã biết; intent khác / rỗng → không gợi ý.
_INTENT_HINT: Final = {
    "vpn": "vpn", "account": "account", "software": "software", "access": "access", IT_HELP: IT_HELP,
}  # fmt: skip
# Kết quả cuối → câu cố định (không chữ tự do).
_OUTCOME: Final = {
    "S_RESOLVED": "đã xong",
    "S_ESCALATED": "đã chuyển kỹ thuật viên",
    "S_REJECTED": "bị từ chối",
    "S_BLOCKED": "bị chặn",
}


@dataclass(frozen=True)
class FollowUpSource:
    """Cột đóng của dòng `tickets` cũ mà API cần để kiểm quyền + dựng gợi ý (đọc DB, không đọc checkpoint)."""

    ticket_id: str
    requester_id: str
    parent_ticket_id: str | None
    is_parent: bool
    final_state: str | None
    intent: str | None


def can_follow(src: FollowUpSource | None, requester_id: str) -> bool:
    """Ticket cũ hợp lệ để hỏi tiếp: tồn tại, của ĐÚNG người gửi, là ticket GỐC (không phải con), đã kết thúc. Sai bất kỳ → API trả 404
    giống hệt "không có" (không lộ ticket người khác có tồn tại)."""
    return (
        src is not None
        and src.requester_id == requester_id
        and src.parent_ticket_id is None
        and src.final_state is not None
    )


def prior_label_hint(src: FollowUpSource) -> str | None:
    """Một dòng gợi ý cho `b03_classify.label_hint`, hoặc None khi ticket cũ không có intent đã biết (cha nhiều ý, E1 ngay ở B3…)."""
    label = _INTENT_HINT.get(src.intent or "")
    if label is None:
        return None
    outcome = _OUTCOME.get(src.final_state or "", "đã kết thúc")
    return f"{label} (câu này có thể nói tiếp yêu cầu trước của người dùng — loại {label}, {outcome})"
