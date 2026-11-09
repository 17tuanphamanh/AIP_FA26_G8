"""be-b11-khoa-slot — dọn tên khoá slot lộ trong câu hỏi B11 do LLM viết (ticket a162cded: "… mã máy (device_id) …").

Hàm THUẦN, tất định, chạy SAU khi LLM trả câu và TRƯỚC output guard / notify / ghi conversation (chỉ nhánh LLM; câu cố định
`domain/target.TARGET_QUESTION` không đi qua đây). Không đổi prompt, không đổi khoá cache.

1. Khoá bọc ngoặc — `(khoá)`, `（khoá）`, `[khoá]`, `` `khoá` `` (cho phép khoảng trắng bên trong) — bỏ cả cụm cùng khoảng trắng đứng trước.
2. Khoá đứng trơn (ranh giới từ: không dính chữ/số/`_`) → nhãn tiếng Việt `SLOT_LABELS`; khoá không có nhãn → bỏ.
3. CHỈ khi đã bỏ/thay ≥ 1 chỗ: gộp khoảng trắng đôi, bỏ khoảng trắng trước dấu câu, cắt hai đầu. Câu không có khoá → giữ nguyên từng byte.
4. Sau khi dọn không còn chữ nào → câu cố định `fallback_question(slot đầu tiên)`.
Danh sách khoá = mọi khoá slot hệ thống biết (`config/slots.yaml`, mọi intent) — không chỉ slot đang thiếu.
"""

import re
from collections.abc import Iterable, Sequence

# Nhãn tiếng Việt của khoá slot — khai báo MỘT chỗ (test: phủ đủ khoá trong config/slots.yaml).
SLOT_LABELS: dict[str, str] = {
    "device_id": "mã máy",
    "error_code": "mã lỗi",
    "reason": "lý do",
    "action": "việc cần làm",
    "account_type": "loại tài khoản",
    "target_user": "mã tài khoản cần xử lý",
    "software_name": "tên phần mềm",
    "version": "phiên bản",
    "justification": "lý do cần dùng",
    "resource_path": "thư mục cần truy cập",
    "permission_level": "mức quyền",
    "duration": "số ngày cần dùng",
}
FALLBACK_LABEL = "thông tin còn thiếu"
# Q3 M2 (ĐP 09/11): giải thích + ví dụ cho từng khoá slot — nguồn của biến `missing_desc` (prompt `b11_clarify_question` v3). HẰNG, không
# chữ người dùng. Slot `action` không có ví dụ cố định: danh sách việc lấy theo `action_types` của intent (nhãn `ACTION_LABELS`).
# Ví dụ chỉ minh hoạ DẠNG, KHÔNG là định danh có thật (máy/người/thư mục/phần mềm trong danh mục) — be-target-guard-2: câu hỏi không được
# gợi ý máy của người gửi hay đích của người khác.
SLOT_HINTS: dict[str, tuple[str, str | None]] = {
    "device_id": ("mã in trên tem dán ở máy tính", "LAP-1234"),
    "error_code": ("mã lỗi hiện trên màn hình", "809"),
    "reason": ("vì sao bạn cần việc này", None),
    "action": ("việc bạn cần mình làm", None),
    "account_type": ("tài khoản đăng nhập máy tính (Windows), email hay ERP", None),
    "target_user": ("mã nhân viên trong hệ thống của người cần xử lý", "nv123"),
    "software_name": ("tên phần mềm cần cài", None),
    "version": ("phiên bản phần mềm cần cài, nếu cần đúng một bản", None),
    "justification": ("vì sao công việc cần phần mềm hoặc quyền này", None),
    "resource_path": ("đường dẫn thư mục cần truy cập", "phong-ban/thu-muc"),
    "permission_level": ("chỉ đọc hay được chỉnh sửa", None),
    "duration": ("cần dùng trong bao nhiêu ngày, trả lời bằng số ngày", "30"),
}
UNKNOWN_ACTION = "chưa rõ"  # biến `action_label` khi chưa có slot `action`
_WRAPS = ((r"\(", r"\)"), (r"（", r"）"), (r"\[", r"\]"), (r"`", r"`"))
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:!?…)\]）])")
_HAS_WORD = re.compile(r"[^\W\d_]")


def fallback_question(first_missing: str | None) -> str:
    label = SLOT_LABELS.get(first_missing or "", FALLBACK_LABEL)
    return f"Bạn cho mình biết thêm {label} nhé?"


def describe_missing(missing: Sequence[str], *, action_choices: Sequence[str]) -> str:
    """Q3 M2: biến `missing_desc` — mỗi slot thiếu một dòng "- <nhãn>: <giải thích> (ví dụ: …)"; slot `action` thêm "chỉ một trong:
    <các nhãn việc của intent>". Chỉ ghép HẰNG (tên slot → bảng) và nhãn hành động — không có chữ người dùng."""
    lines = []
    for slot in missing:
        label = SLOT_LABELS.get(slot, FALLBACK_LABEL)
        hint, example = SLOT_HINTS.get(slot, ("", None))
        line = f"- {label}: {hint}" if hint else f"- {label}"
        if slot == "action" and action_choices:
            line += f" — chỉ một trong: {', '.join(action_choices)}"
        if example:
            line += f" (ví dụ: {example})"
        lines.append(line)
    return "\n".join(lines)


def scrub_slot_keys(text: str, keys: Iterable[str], first_missing: str | None) -> tuple[str, int]:
    """(câu đã dọn, số chỗ đã bỏ/thay). Số 0 → trả đúng `text` ban đầu."""
    ordered = sorted(set(keys), key=len, reverse=True)  # khoá dài trước: không cắt dở khoá chứa khoá khác
    out, n = text, 0
    for key in ordered:
        k = re.escape(key)
        for left, right in _WRAPS:
            inner = rf"`?{k}`?" if left != "`" else k  # "(`duration`)" — backtick lồng trong ngoặc
            out, c = re.subn(rf"[ \t]*{left}[ \t]*{inner}[ \t]*{right}", "", out)
            n += c
    for key in ordered:
        label = SLOT_LABELS.get(key, "")
        out, c = re.subn(rf"(?<![\w]){re.escape(key)}(?![\w])", label, out)
        n += c
    if n == 0:
        return text, 0
    out = _SPACE_BEFORE_PUNCT.sub(r"\1", _SPACES.sub(" ", out)).strip()
    if not _HAS_WORD.search(out):
        return fallback_question(first_missing), n
    return out, n
