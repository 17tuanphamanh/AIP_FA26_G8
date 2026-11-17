"""D-102 (kiểm thử 17/11 trên máy demo): một câu nêu HAI đối tượng cùng loại nối bằng liên từ — "Cấp quyền đọc shared/templates cho nv005
và nv007", "Cài giúp em Zoom và 7-Zip lên LAP-0342" — mà hành động chỉ dựng được cho MỘT đối tượng (Action có một `target`). Trước đây hệ
thống làm một cái, bỏ cái còn lại không báo (phiếu duyệt ghi "Thực hiện cho nv005"; 7-Zip mất hẳn, còn hỏi thừa "phiên bản nào").

Ở lượt hỏi ĐẦU của B11 (`clarification_turns == 0`) phát hiện ≥ 2 đối tượng KHÁC NHAU cùng loại, đứng liền nhau qua liên từ ("và", "với",
"cùng", "lẫn", "and", "+", "&") hoặc chỉ dấu phẩy/chấm phẩy/gạch chéo → B11 hỏi câu CỐ ĐỊNH "mỗi yêu cầu một …, bạn muốn làm cái nào
trước?" (không LLM), bỏ slot đó để câu trả lời điền lại; cái còn lại người dùng gửi yêu cầu riêng. Chỉ hỏi MỘT lần (lượt sau không xét
lại → không lặp). "hoặc"/"hay" (người dùng chỉ cần một) KHÔNG tính — giữ luồng cũ. Hai mã đứng rời ("Tôi là nv001, đặt lại cho nv005",
"quyền giống nv007") không tính.

Nhận diện TẤT ĐỊNH; chỉ chữ đã qua regex/bảng hằng đi vào câu hỏi: mã nhân viên `nvNNN`, mã máy theo `device_prefixes`, đường dẫn thư mục
(theo dáng `value_rules.resource_path`), tên phần mềm theo bảng `SOFTWARE_MENTIONS` (nhãn hiển thị là HẰNG trong mã). Slot
`software_name` chứa liên từ ("Zoom and Teams") mà câu không đủ hai tên trong bảng → vẫn hỏi, câu hỏi không nêu tên.
"""

import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final, Literal

from app.domain.action import TARGET_USER_INTENTS

type ObjectKind = Literal["target_user", "software_name", "device_id", "resource_path"]
type Hit = tuple[int, int, str]  # (đầu, cuối, nhãn) trên chữ đã chuẩn hoá

_EMPLOYEE_CODE: Final = re.compile(r"(?<![a-z0-9_.@-])nv\d{3,5}(?![a-z0-9_@-])")
# dáng `value_rules.resource_path` (≤ 5 đoạn); đoạn đầu phải có chữ cái — "30/11", "30/11/2026" là ngày, không phải thư mục
_PATH: Final = re.compile(r"(?<![\w/.-])(?=[a-z0-9_-]*[a-z])[a-z0-9_-]+(?:/[a-z0-9_.-]+){1,4}(?![\w/-])", re.IGNORECASE)
_NOT_PATH_WORDS: Final = frozenset({"read", "write", "full", "rw", "r", "w", "view", "edit", "on", "off", "tcp", "udp"})
_JOINER: Final = re.compile(r"(?:^|\s)(?:và|với|cùng|lẫn|and)(?=\s|$)|[+&]")
_PUNCT_ONLY: Final = re.compile(r"\s*[,;/]\s*")
_PAREN: Final = re.compile(r"\([^()]{0,40}\)")
_MAX_GAP_WORDS: Final = 4  # "Zoom và cả phần mềm 7-Zip", "Bình nv005 và Chi nv007"
_SLOT_JOINER: Final = re.compile(r"\s*(?:,|;|\+|&|\bvà\b|\bvới\b|\band\b)\s*")

# Tên phần mềm → nhãn hiển thị HẰNG: danh mục + danh sách cấm của mock (`mock_services/seed.json`) và vài phần mềm hay gặp ngoài danh
# mục (chỉ để nhận ra "hai phần mềm"; có trong bảng KHÔNG có nghĩa là được cài — B12/danh mục vẫn quyết).
SOFTWARE_MENTIONS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("Zoom", re.compile(r"\bzoom\b")),
    ("Visual Studio Code", re.compile(r"\bvs\s*code\b|\bvisual\s+studio\s+code\b")),
    ("7-Zip", re.compile(r"\b7[\s-]?zip\b")),
    ("Microsoft Office", re.compile(r"\b(?:ms\s+|microsoft\s+)?office(?:\s*(?:365|20\d\d))?\b")),
    ("Adobe Acrobat Pro", re.compile(r"\b(?:adobe\s+)?acrobat(?:\s+pro)?\b")),
    ("Microsoft Project", re.compile(r"\b(?:ms|microsoft)\s+project\b")),
    ("AutoCAD", re.compile(r"\bautocad\b")),
    ("uTorrent", re.compile(r"\bu\s?torrent\b")),
    ("BitTorrent", re.compile(r"\bbit\s?torrent\b")),
    ("qBittorrent", re.compile(r"\bqbit\s?torrent\b")),
    ("KMSpico", re.compile(r"\bkms\s?pico\b")),
    ("KMSAuto", re.compile(r"\bkms\s?auto\b")),
    ("Microsoft Teams", re.compile(r"\b(?:ms\s+|microsoft\s+)?teams\b")),
    ("Google Chrome", re.compile(r"\b(?:google\s+)?chrome\b")),
    ("Firefox", re.compile(r"\b(?:mozilla\s+)?firefox\b")),
    ("Slack", re.compile(r"\bslack\b")),
    ("WinRAR", re.compile(r"\bwinrar\b")),
    ("Photoshop", re.compile(r"\b(?:adobe\s+)?photoshop\b")),
    ("Skype", re.compile(r"\bskype\b")),
    ("Notepad++", re.compile(r"\bnotepad\s*\+\+")),
    ("Postman", re.compile(r"\bpostman\b")),
    ("TeamViewer", re.compile(r"\bteam\s?viewer\b")),
    ("AnyDesk", re.compile(r"\banydesk\b")),
    ("UniKey", re.compile(r"\bunikey\b")),
    ("Foxit Reader", re.compile(r"\bfoxit(?:\s+reader)?\b")),
)
QUESTION_NOUN: Final[Mapping[ObjectKind, str]] = {
    "target_user": "tài khoản", "software_name": "phần mềm", "device_id": "máy", "resource_path": "thư mục",
}  # fmt: skip
_WHICH: Final[Mapping[ObjectKind, str]] = {
    "target_user": "Bạn muốn làm cho tài khoản nào trước", "software_name": "Bạn muốn cài phần mềm nào trước",
    "device_id": "Bạn muốn làm cho máy nào trước", "resource_path": "Bạn muốn làm với thư mục nào trước",
}  # fmt: skip


@dataclass(frozen=True)
class MultiObject:
    kind: ObjectKind
    names: tuple[str, ...]  # chữ CỐ ĐỊNH (mã đã qua regex / nhãn hằng); rỗng = không nêu tên trong câu hỏi


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", " ".join(unicodedata.normalize("NFC", text).casefold().split()))


def _joined(gap: str) -> bool:
    """Khoảng chữ giữa hai đối tượng là phép NỐI ("và", ",", "+", "cùng với cả"…), không phải câu khác."""
    g = _PAREN.sub(" ", gap).casefold()
    if not g.strip() or _PUNCT_ONLY.fullmatch(g):
        return True
    return len(g.split()) <= _MAX_GAP_WORDS and _JOINER.search(g) is not None


def _longest_first(hits: Iterable[Hit]) -> list[Hit]:
    """Bỏ đoạn trùng: một vùng chữ chỉ tính cho mẫu khớp DÀI nhất ("microsoft office 365" không đếm thêm "office")."""
    kept: list[Hit] = []
    for hit in sorted(hits, key=lambda h: (h[0], -(h[1] - h[0]))):
        if any(hit[0] < e and s < hit[1] for s, e, _ in kept):
            continue
        kept.append(hit)
    return sorted(kept)


def joined_run(text: str, hits: Iterable[Hit]) -> tuple[str, ...]:
    """Chuỗi đối tượng liền nhau qua liên từ ĐẦU TIÊN có ≥ 2 nhãn khác nhau (nhãn không trùng, theo thứ tự), hoặc ()."""
    ordered = _longest_first(hits)
    run: list[str] = []
    for i, (_, _, label) in enumerate(ordered):
        if i and not _joined(text[ordered[i - 1][1] : ordered[i][0]]):
            if len(set(run)) >= 2:
                break
            run = []
        run.append(label)
    distinct = tuple(dict.fromkeys(run))
    return distinct if len(distinct) >= 2 else ()


def software_hits(text: str) -> list[Hit]:
    return [(m.start(), m.end(), label) for label, pattern in SOFTWARE_MENTIONS for m in pattern.finditer(text)]


def multi_object(
    intent: str, text: str, slots: Mapping[str, object], *, device_prefixes: Iterable[str]
) -> MultiObject | None:
    """Loại đối tượng ĐẦU TIÊN có ≥ 2 giá trị khác nhau nối liền trong câu (tài khoản, phần mềm, máy, thư mục), hoặc None."""
    t = _norm(text)
    codes = ((m.start(), m.end(), m.group(0)) for m in _EMPLOYEE_CODE.finditer(t))
    if intent in TARGET_USER_INTENTS and (names := joined_run(t, codes)):
        return MultiObject("target_user", names)
    if intent == "software":
        if names := joined_run(t, software_hits(t)):
            return MultiObject("software_name", names)
        raw = slots.get("software_name")
        if isinstance(raw, str) and len([p for p in _SLOT_JOINER.split(raw.casefold()) if p.strip()]) >= 2:
            return MultiObject("software_name", ())
    alts = "|".join(sorted({p.casefold() for p in device_prefixes}, key=len, reverse=True))
    if intent in {"vpn", "software"} and alts:
        device = re.compile(rf"(?<![a-z0-9-])(?:{alts})-\d{{3,5}}(?![a-z0-9-])")
        if names := joined_run(t, ((m.start(), m.end(), m.group(0).upper()) for m in device.finditer(t))):
            return MultiObject("device_id", names)
    if intent == "access":
        raw_text = unicodedata.normalize("NFC", " ".join(text.split()))  # giữ hoa thường của đường dẫn (khớp IGNORECASE)
        paths = [(m.start(), m.end(), m.group(0)) for m in _PATH.finditer(raw_text)
                 if not set(m.group(0).casefold().split("/")) <= _NOT_PATH_WORDS]  # fmt: skip
        if names := joined_run(raw_text, paths):
            return MultiObject("resource_path", names)
    return None


def multi_object_question(found: MultiObject) -> str:
    noun = QUESTION_NOUN[found.kind]
    options = f": {', '.join(found.names[:-1])} hay {found.names[-1]}" if found.names else ""
    return (
        f"Mỗi yêu cầu mình chỉ xử lý một {noun}. {_WHICH[found.kind]}{options}? "
        f"{noun[:1].upper() + noun[1:]} còn lại bạn gửi một yêu cầu riêng nhé."
    )
