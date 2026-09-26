"""Privacy guard ở API (B02 lớp L0–L1, D-07): chạy TRƯỚC khi lưu ticket hay đưa tin nhắn vào graph —
ticket, checkpoint, audit chỉ thấy bản đã che.

2b-3 chỉ có port + `NotRedactingGuard` (trả nguyên văn): guard thật (Presidio + regex bí mật) làm ở
Phase 3. Bản không che CHỈ nạp được khi `APP_ENV` ∈ {dev, test} — môi trường khác từ chối khởi động
(2b-Q2, `Settings.require_dev_fakes`), để không có đường nào lưu dữ liệu thô ở môi trường thật.
"""

from typing import Protocol

from pydantic import BaseModel


class RedactionResult(BaseModel):
    """B02 mục 4 — hợp đồng giữ nguyên khi Phase 3 thay guard thật."""

    text: str  # đã che
    secrets_found: int  # chỉ số lượng, không lưu giá trị
    pii_map_id: str | None  # khoá tới bảng ánh xạ đã mã hoá
    notices: list[str]  # ví dụ "Vui lòng không gửi mật khẩu qua chat"


class PrivacyGuard(Protocol):
    async def redact(self, text: str) -> RedactionResult: ...


class NotRedactingGuard:
    """Không che gì — chỉ dev/test (bên gọi phải qua `Settings.require_dev_fakes` trước)."""

    async def redact(self, text: str) -> RedactionResult:
        return RedactionResult(text=text, secrets_found=0, pii_map_id=None, notices=[])
