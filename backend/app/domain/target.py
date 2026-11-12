"""target — chốt "hành động chạy trên SAI ĐỐI TƯỢNG" (L-03, nhánh be-target-guard). Hàm THUẦN, hằng trong code (không cấu hình).

Lỗ: người gửi nhắm NGƯỜI KHÁC ("đặt lại mật khẩu cho tài khoản dịch vụ svc-backup") mà LLM KHÔNG đưa khoá `target_user` → `requested_for_of`
về người gửi (fail-open) → luật allow (R01) chạy trên CHÍNH người gửi. Cờ `ctx_flags.target_is_other` cũ chỉ bật khi đúng khoá
`target_user` bị `sanitize_slots` bỏ — không đủ.

`target_check` (B3 một ý, B5 từng con, `clarify_wait`): intent ∈ {account, access} (`TARGET_USER_INTENTS`) → lý do bật cờ:
- `target_user` bị bỏ (BẤT KỲ lý do) → `dropped` — luôn bật như Q-T20a-4/6 cũ (kể cả khi đã có `target_user` hợp lệ: không yếu hơn bản cũ);
- chưa có `target_user` hợp lệ VÀ: câu nêu người khác (`mention_reason`: `identifier` | `phrase`), hoặc có khoá bị bỏ `unknown_key` NẰM
  NGOÀI `spec.keys` (khoá lạ của LLM như `account_name` — khoá đã khai báo mà không đang hỏi ở B11 không tính) → `unknown_key`.
Không bao giờ trả lý do để HẠ cờ; nơi gọi chỉ ghi True.

`mention_reason(text, requester_id, ignore=…)`:
- `identifier`: token định danh ASCII `[a-z0-9][a-z0-9._-]*[a-z0-9]` (casefold) có ≥ 1 chữ VÀ (≥ 1 số hoặc `.`/`_`/`-`), khác `requester_id`.
  LOẠI: token chứa `/` (đường dẫn), `@`, `:`; mã máy `^[a-z]{2,4}-\\d{3,5}$`; mã lỗi hex; phiên bản `v1.2`; đuôi tệp; URL/tên miền;
  `STOPLIST`; token TRÙNG ĐÚNG (casefold) giá trị slot TÀI NGUYÊN đã qua `sanitize_slots` (`RESOURCE_SLOTS`: `resource_path`,
  `software_name`, `device_id` — truyền qua `ignore`, A1). Mặt nạ PII `<LOẠI_n>`
  TÍNH là định danh lạ (thận trọng); `[BÍ_MẬT_ĐÃ_ẨN]` KHÔNG tính.
- `phrase`: cụm gợi ý người khác, so cả bản có dấu lẫn bản bỏ dấu. Tự xưng ("cho em", "giúp em", "của em", "mình", "tôi") không tính.

be-target-guard-2 (L-03 Phần 2 D, D-72 bổ sung): intent ∈ {vpn, software} (`DEVICE_INTENTS`) → lý do bật cờ (thứ tự kiểm):
- `dropped`: khoá `device_id` hoặc `target_user` bị bỏ (BẤT KỲ lý do — "lap-0610" sai mẫu, mã không có trong câu…);
- `identifier`: CHỈ mã nhân viên `^nv\\d{3,5}$` (casefold) khác người gửi — KHÔNG dùng phép dò định danh ASCII rộng (tên phần mềm/phiên bản
  như 7-zip, python3.11 sẽ bật nhầm);
- `phrase`: cụm gợi ý người khác như trên + cụm máy: "máy (tính )?(của )?(anh|chị|bạn|sếp|cô|chú|cậu) <Tên viết hoa>", "máy (tính )?của
  (anh|chị|bạn|sếp|cô|chú|cậu)", "của (anh|chị|…) <Tên viết hoa>". "máy của em/mình/tôi" không tính;
- `device_text`: câu có chuỗi dạng mã máy (`[a-z]{2,4}[- ]?\\d{3,5}`, không phân biệt hoa thường — "LAP 0610", "lap-0610") mà dạng chuẩn
  (`LAP-0610`) KHÁC `device_id` sạch (LLM bỏ khoá mã máy) và không nằm trong tên phần mềm đã sạch.
Cờ bật → B6 KHÔNG tự suy máy duy nhất của người gửi (`allow_infer`) → B11 hỏi mã máy → máy người khác → B15 chốt P6 (E5).

Q4 (ĐP 09/11 — bớt báo nhầm, KHÔNG nới lưới cuối: fact chủ máy từ tool + `build_ctx.target_is_other` + chốt P6 ở B15):
- mã máy (`device_text`, loại trừ mã máy của `identifier`) dùng CHUNG `domain/slots.py` + `device_prefixes` (config): "loi 809",
  "cong 443", "VPN-2025-0342" không còn là mã máy; tiền tố lạ chỉ tính ngay sau "máy/laptop/pc/thiết bị"; "kt-0012" nay là định danh lạ;
- vpn/software: cụm CHUNG (`_GENERIC`: đồng nghiệp, người khác, nhân viên mới, X ấy) bật ở MỌI vị trí, CHỈ miễn khi ở ngữ cảnh SO SÁNH —
  đứng sau "giống (như)/so với", hoặc "như" khi không "cũng/chẳng hạn/ví dụ như" và 200 ký tự trước không có cho/giúp/hộ/dùm/giùm/để/cài/
  cấp/gia hạn (liệt kê), hoặc theo sau là "vẫn (≤ 4 từ) được|bình thường" / "thì (≤ 2 từ) được"
  rồi HẾT câu hoặc dấu . , ; ! — cùng vế câu (từ = chữ/số liền nhau; mọi ký tự khác và liên từ — cả "dù/tuy" — là hết vế); từ chen giữa (trước
  lẫn sau "vẫn/thì") không là phủ định, lỗi/nhu cầu (lỗi, bị, cần, mới…) hay tự xưng (em/mình/tôi — trừ "em" sở hữu ngay sau cụm).
  Cụm ngay sau "cho/giúp/hộ/dùm/giùm/của/để" không bao giờ miễn. Danh sách CHO PHÉP, không danh sách cấm. account/access: không đổi;
- nhiều ý (B5): tập bỏ qua của `identifier` thêm slot tài nguyên đã sạch của các ý CHẠY ĐƯỢC khác (`sibling_slots`), trừ giá trị (sau
  casefold) dáng mã người `^[a-z0-9_]{3,64}$` có số hoặc `_` (nv005, svc_backup…) hoặc có trong span của chính ý (`own_span`) — chống LLM
  điền slot ý bên cạnh để che đích. Không dùng danh mục alias phần mềm (chỉ có qua tool); không tính mã máy của ý bên cạnh cho vpn/software.

Audit chỉ ghi lý do (hằng) + bool — KHÔNG ghi câu hay token.
"""

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from typing import Any, Literal

from app.domain.action import TARGET_USER_INTENTS
from app.domain.context import RequesterContext
from app.domain.slots import device_ids_in_text, is_device_code, phrase_in_text

type MentionReason = Literal["identifier", "phrase"]
type FlagReason = Literal["identifier", "phrase", "dropped", "unknown_key", "device_text"]

DEVICE_INTENTS = frozenset({"vpn", "software"})  # be-target-guard-2: đích là MÁY

# B11 hỏi `target_user` khi cờ bật mà chưa có đích — câu CỐ ĐỊNH, không gọi LLM (vẫn qua output guard, notify, hạn).
TARGET_QUESTION = (
    "Bạn cần xử lý cho tài khoản của ai? Vui lòng ghi đúng mã tài khoản trong hệ thống (ví dụ: nv005). "
    "Nếu là tài khoản của chính bạn, hãy ghi mã nhân viên của bạn."
)

# A1: slot TÀI NGUYÊN — giá trị đã sạch của các khoá này không phải định danh người.
RESOURCE_SLOTS = frozenset({"resource_path", "software_name", "device_id"})

STOPLIST = frozenset({
    "e-mail", "wi-fi", "log-in", "log-out", "sign-in", "sign-up", "sign-out", "check-in", "plug-in", "add-in", "pop-up",
    "set-up", "back-up", "follow-up", "re-login", "utf-8", "office365", "o365", "m365", "microsoft365", "2fa", "mfa-2fa",
    "win7", "win10", "win11", "windows7", "windows10", "windows11", "ipv4", "ipv6", "3g", "4g", "5g", "mp3", "mp4", "a3", "a4",
    "covid-19", "24h", "24-7",
})  # fmt: skip

_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]*[a-z0-9]")
_HEX = re.compile(r"0x[0-9a-f]+|[0-9a-f]{8}")
_VERSION = re.compile(r"v\d+(?:[._-]\d+)*")
_FILE_EXT = re.compile(
    r".+\.(?:pdf|docx?|xlsx?|pptx?|txt|csv|exe|msi|zip|rar|7z|png|jpe?g|gif|log|ini|cfg|conf|json|xml|ya?ml|bat|ps1|sh|dmg|pkg|"
    r"iso|apk|mp3|mp4|pst|ost)"
)
_DOMAIN = re.compile(r"(?:www\..+|.+\.(?:com|vn|net|org|local|io|edu|gov|info|biz|co|corp|lan|int|dev|app))")
_PII_MASK = re.compile(r"<[^\s<>]+_\d+>")  # guard/privacy.py: `<LOẠI_n>`
_SECRET_MASK = "[BÍ_MẬT_ĐÃ_ẨN]"
_EDGE_PUNCT = ".,;:!?()[]{}<>\"'“”‘’«»…"

_SPECIFIC = (
    r"tài khoản dịch vụ", r"service account", r"\bsvc\b", r"tài khoản của (?:anh|chị|bạn|sếp|cô|chú)\b", r"\bhộ (?:anh|chị|bạn)\b",
)  # fmt: skip
_GENERIC = (r"người khác", r"đồng nghiệp", r"nhân viên mới", r"\b(?:anh|chị|em|bạn|cậu|cô|chú) ấy\b")  # Q4: cụm CHUNG
_PHRASES = _SPECIFIC + _GENERIC  # account/access: mọi cụm, mọi vị trí (như be-target-guard)
# Q4 — ngữ cảnh SO SÁNH (chỉ miễn cụm chung của vpn/software). Từ = chuỗi không khoảng trắng/dấu câu (không vượt sang vế câu khác).
# Q4 ngữ cảnh so sánh — DANH SÁCH CHO PHÉP (soát S6 hai lần: danh sách cấm không đủ). Từ = `\w+` cách nhau bằng [ \t] — mọi ký tự khác
# (dấu câu, …, -, ngoặc, emoji, xuống dòng) là hết vế câu; liên từ (`_STOP`) cũng hết vế. Cụm chung ngay sau giới từ người-được-làm-hộ
# (`_BENEFIT`) KHÔNG BAO GIỜ miễn. Trước: "giống/như/so với" nhưng không "cũng/hạn/dụ như". Sau: "vẫn (≤ 4 từ) được|bình thường" hoặc
# "thì (≤ 2 từ) được", ≤ 4 từ chen trước (+ "em/mình/tôi/tớ" sở hữu ngay sau cụm), mọi từ chen giữa không là liên từ/phủ định/lỗi-nhu cầu/
# tự xưng, rồi CHỈ được là hết câu hoặc dấu . , ; ! (không "?").
_NEG = r"(?:không|chưa|chẳng|chả|ko|kh|k|hk|hok|hông|khum|kg|khg|hem|hổng|đâu)"
_STOP = r"(?:nhưng|và|còn|mà|song|vì|chứ|để|nên|nếu|tại|bởi|do|khi|hay|hoặc|dù|tuy)"
# Soát S6 lần 3: từ chen giữa (cả TRƯỚC "vẫn/thì") không được là phủ định, lỗi/nhu cầu, hay đại từ tự xưng (đổi chủ ngữ: "đồng nghiệp
# không vào được VPN em vẫn vào được") — "em/mình/tôi/tớ" chỉ được ngay sau cụm (sở hữu: "đồng nghiệp em vẫn vào được").
_BAD = r"(?:mới|phải|cần|lỗi|bị|hỏng|hư|muốn|nhờ|xin)"
_SELF = r"(?:em|mình|tôi|tớ)"
_WOK = rf"(?!(?:{_STOP}|{_NEG}|{_BAD}|{_SELF})(?!\w))\w+[ \t]+"
_QUANT = r"(?:(?:các|mấy|những|mọi|cả)[ \t]+)?"
_BENEFIT = rf"(?<!\w)(?:cho|giúp|hộ|dùm|giùm|của|để)[ \t]+{_QUANT}\Z"  # \Z (không `$`): `$` khớp cả trước "\n" cuối lát cắt
_CMP_BEFORE = rf"(?<!\w)(?:giống(?:[ \t]+như)?|so với)[ \t]+{_QUANT}\Z"
# Soát S6 lần 4: "như" ĐỨNG MỘT MÌNH còn là liệt kê ("cài Zoom cho các bạn như nhân viên mới") — chỉ miễn khi không "cũng/hạn/dụ như" VÀ
# trong `_REQ_LOOKBACK` ký tự trước không có giới từ/động từ yêu cầu (`_REQ`).
_CMP_NHU = rf"(?<!\w)như[ \t]+{_QUANT}\Z"
_CMP_BEFORE_NOT = rf"(?<!\w)(?:cũng|hạn|dụ)\s+như[ \t]+{_QUANT}\Z"
_REQ = r"(?<!\w)(?:cho|giúp|hộ|dùm|giùm|để|cài|cấp|gia hạn)(?!\w)"
_REQ_LOOKBACK = 200
_CMP_AFTER = (rf"[ \t]*(?:{_SELF}[ \t]+)?(?:{_WOK}){{0,4}}?(?:vẫn[ \t]+(?:{_WOK}){{0,4}}?(?:được|bình thường)|thì[ \t]+(?:{_WOK}){{0,2}}?được)"
              r"(?:[ \t]+bình thường)?(?=[ \t]*(?:\Z|[.,;!\n]))")  # fmt: skip
_LOOKBACK = 60  # ký tự xét phía trước cụm chung (giới từ / "giống như …") — giữ tuyến tính theo độ dài câu
_NAMED = r"(?i:\bcho (?:anh|chị|bạn|sếp|cô|chú)) (\w)"  # "cho chị Hoa" — tên viết hoa (so trên bản giữ hoa/thường)
# be-target-guard-2: cụm MÁY của người khác ("máy của chị Hoa", "máy anh Nam", "máy của sếp") — không có "em/mình/tôi" (tự xưng)
_DEVICE_PHRASES = (r"\bmáy (?:tính )?của (?:anh|chị|bạn|sếp|cô|chú|cậu)\b",)
_DEVICE_NAMED = r"(?i:\b(?:máy (?:tính )?(?:của )?|của )(?:anh|chị|bạn|sếp|cô|chú|cậu)) (\w)"  # + "máy lap-0610 của chị Hoa"
# V5 (soát 12/11, D-91): tên TRẦN sau giới từ người-được-làm-hộ ("của Bình", "cho Bình", "hộ Bình", "giúp chị Lan") và "máy (của) Bình" —
# trước chỉ nhận "cho + kính ngữ + Tên" / "máy + kính ngữ + Tên"; LLM bỏ sót `target_user` là làm trên CHÍNH người gửi (R01/R10/R11/R20 AUTO).
# Tên = MỘT từ chữ cái, hoa chữ đầu, phần còn lại thường, ≥ 2 ký tự, không thuộc `_NOT_NAMES` (sản phẩm, hãng máy, hệ thống, phòng ban, đại
# từ). Chiều an toàn: bắt nhầm chỉ thêm câu hỏi đích. Cùng mẫu: vai trò người khác ("cho sếp", "của trưởng phòng", "giúp quản lý").
_HONORIFIC = r"(?:anh|chị|bạn|sếp|cô|chú|cậu|em|ông|bà|bác)"
_BARE_NAMED = rf"(?i:(?<!\w)(?:của|cho|hộ|giúp|giùm|dùm)\s+(?:{_HONORIFIC}\s+)?)(\w+)"
_DEVICE_BARE = rf"(?i:(?<!\w)máy\s+(?:tính\s+)?(?:của\s+)?(?:{_HONORIFIC}\s+)?)(\w+)"
_ROLE_BENEFIT = (r"(?<!\w)(?:của|cho|hộ|giúp|giùm|dùm)\s+(?:sếp|trưởng phòng|trưởng nhóm|trưởng bộ phận|quản lý|giám đốc|phó giám đốc"
                 r"|leader|manager)(?!\w)")  # fmt: skip
_NOT_NAMES = frozenset({
    # đại từ / kính ngữ viết hoa
    "em", "anh", "chi", "ban", "minh", "toi", "to", "tao", "no", "ho", "sep", "co", "chu", "cau", "ong", "ba", "bac", "chung", "may",
    # sản phẩm, dịch vụ, hệ thống
    "windows", "zoom", "outlook", "teams", "office", "excel", "word", "powerpoint", "onenote", "onedrive", "sharepoint", "adobe",
    "acrobat", "photoshop", "illustrator", "chrome", "firefox", "edge", "safari", "slack", "skype", "zalo", "facebook", "messenger",
    "gmail", "google", "microsoft", "apple", "mac", "macbook", "imac", "iphone", "ipad", "android", "dell", "lenovo", "asus", "acer",
    "thinkpad", "cisco", "forticlient", "fortinet", "anydesk", "teamviewer", "ultraviewer", "vpn", "wifi", "jira", "confluence", "git",
    "github", "gitlab", "visual", "studio", "python", "java", "docker", "postman", "notepad", "kaspersky", "bitdefender", "sophos",
    "erp", "sap", "misa", "bravo", "oracle", "vnpt", "viettel", "mobifone", "vinaphone", "shopee", "lazada", "tiki", "momo", "grab",
    "telegram", "discord", "steam", "linux", "ubuntu", "unikey", "foxit", "winrar", "vlc", "spotify", "canva", "figma", "notion",
    "trello", "dropbox", "autocad", "matlab", "tableau", "power", "sql", "server", "admin", "administrator", "user", "guest", "test",
    "ad", "it", "hr", "email", "mail", "web", "app", "phan", "phong", "cong", "tong", "nhanh", "ke", "nhan", "kinh",
    "ky", "hanh", "marketing", "sales", "finance", "legal", "support", "helpdesk", "service", "desk", "team", "nhom", "tai", "khoan",
    "thu", "muc", "quyen", "file", "folder", "drive", "shared", "public", "templates", "reports", "mat", "khau", "laptop", "pc",
})  # fmt: skip
_EMPLOYEE = re.compile(r"nv\d{3,5}")  # mã nhân viên (seed nvXXX) — dò riêng cho vpn/software
_USER_LIKE = re.compile(r"[a-z0-9_]{3,64}")  # dáng `target_user` (slots.yaml) — giá trị ý bên cạnh dáng này không bao giờ bỏ qua


def fold(text: str) -> str:
    """Bỏ dấu tiếng Việt (giữ hoa/thường): NFD → bỏ dấu kết hợp, đ/Đ → d/D."""
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    return unicodedata.normalize("NFC", "".join(c for c in decomposed if not unicodedata.combining(c)))


_PHRASE_RES = tuple(re.compile(p) for p in _PHRASES) + tuple(re.compile(fold(p)) for p in _PHRASES)
_SPECIFIC_RES = tuple(re.compile(p) for p in _SPECIFIC) + tuple(re.compile(fold(p)) for p in _SPECIFIC)
# (cụm chung, giới từ, trước-so-sánh, trừ-"cũng như", sau-so-sánh) cho bản có dấu và bản bỏ dấu — so cùng một bản
type _Pat = re.Pattern[str]
type _Forms = tuple[tuple[_Pat, ...], _Pat, _Pat, _Pat, _Pat, _Pat, _Pat]


def _forms(f: Callable[[str], str]) -> _Forms:
    """(cụm chung, giới từ, trước-so-sánh, "như", trừ-"cũng như", yêu cầu, sau-so-sánh) — một bản (có dấu / bỏ dấu)."""
    def c(p: str) -> _Pat:
        return re.compile(f(p))

    return tuple(c(p) for p in _GENERIC), c(_BENEFIT), c(_CMP_BEFORE), c(_CMP_NHU), c(_CMP_BEFORE_NOT), c(_REQ), c(_CMP_AFTER)


_GENERIC_FORMS = (_forms(str), _forms(fold))
_NAMED_RES = (re.compile(_NAMED), re.compile(fold(_NAMED)))
_DEVICE_PHRASE_RES = tuple(re.compile(p) for p in _DEVICE_PHRASES) + tuple(re.compile(fold(p)) for p in _DEVICE_PHRASES)
_DEVICE_NAMED_RES = (re.compile(_DEVICE_NAMED), re.compile(fold(_DEVICE_NAMED)))
_BARE_NAMED_RES = (re.compile(_BARE_NAMED), re.compile(fold(_BARE_NAMED)))
_DEVICE_BARE_RES = (re.compile(_DEVICE_BARE), re.compile(fold(_DEVICE_BARE)))
_ROLE_RES = (re.compile(_ROLE_BENEFIT), re.compile(fold(_ROLE_BENEFIT)))


def _looks_like_name(word: str) -> bool:
    """V5: một từ dáng TÊN NGƯỜI — chữ cái, hoa chữ đầu, còn lại thường, ≥ 2 ký tự, không thuộc `_NOT_NAMES` (so bản bỏ dấu, chữ thường)."""
    return (len(word) >= 2 and word.isalpha() and word[0].isupper() and word[1:].islower()
            and fold(word).casefold() not in _NOT_NAMES)  # fmt: skip


def _ignored_values(values: Iterable[str]) -> frozenset[str]:
    """A1 (chốt ĐP): CHỈ token TRÙNG ĐÚNG (casefold) giá trị slot — không tách đoạn `/`, không khớp một phần."""
    return frozenset(v.strip().casefold() for v in values)


def _sibling_ignorable(value: str, own_span: str | None) -> bool:
    """Q4: giá trị slot tài nguyên của Ý BÊN CẠNH được bỏ qua không — không, nếu dáng mã người (có số hoặc `_`) hoặc có trong span ý này."""
    v = value.strip().casefold()
    if _USER_LIKE.fullmatch(v) and any(c.isdigit() or c == "_" for c in v):
        return False
    return own_span is None or not phrase_in_text(value, own_span)


def _is_identifier(token: str, requester: str, ignore: frozenset[str], prefixes: frozenset[str] | None) -> bool:
    if not token.isascii() or _TOKEN.fullmatch(token) is None:
        return False
    if not any(c.isalpha() for c in token) or not any(c.isdigit() or c in "._-" for c in token):
        return False
    if token == requester or token in ignore or token in STOPLIST:
        return False
    if is_device_code(token, prefixes):  # Q4: mã máy theo danh sách tiền tố (slots.py)
        return False
    return not any(r.fullmatch(token) for r in (_HEX, _VERSION, _FILE_EXT, _DOMAIN))


def _has_identifier(text: str, requester_id: str, ignore: frozenset[str], prefixes: frozenset[str] | None = None) -> bool:
    if _PII_MASK.search(text):  # mặt nạ PII = định danh lạ (thận trọng)
        return True
    requester = requester_id.strip().casefold()
    for piece in text.replace(_SECRET_MASK, " ").split():
        token = piece.strip(_EDGE_PUNCT).casefold()
        if token and _is_identifier(token, requester, ignore, prefixes):
            return True
    return False


def _generic_outside_comparison(lowered: str, folded: str) -> bool:
    """Q4: có cụm chung nào KHÔNG nằm trong ngữ cảnh so sánh (mỗi bản dấu/bỏ dấu so với mẫu cùng bản; một bản bật là bật)."""
    for target, (generics, benefit, before, nhu, before_not, req, after) in zip((lowered, folded), _GENERIC_FORMS, strict=True):
        for r in generics:
            for m in r.finditer(target):
                lo, end = max(0, m.start() - _LOOKBACK), m.start()
                if benefit.search(target, lo, end) is not None:  # "cho/giúp/hộ/… <cụm>" — không bao giờ miễn
                    return True
                compared = before.search(target, lo, end) is not None or (
                    nhu.search(target, lo, end) is not None and before_not.search(target, lo, end) is None
                    and req.search(target, max(0, end - _REQ_LOOKBACK), end) is None
                )  # fmt: skip
                if not compared and after.match(target, m.end()) is None:
                    return True
    return False


def _has_phrase(text: str, *, device: bool = False) -> bool:
    lowered = text.casefold()
    folded = fold(lowered)
    phrases = (_SPECIFIC_RES + _DEVICE_PHRASE_RES) if device else _PHRASE_RES  # Q4: vpn/software — cụm chung xét riêng dưới
    if any(r.search(lowered) or r.search(folded) for r in phrases):
        return True
    if device and _generic_outside_comparison(lowered, folded):
        return True
    for r in _NAMED_RES + (_DEVICE_NAMED_RES if device else ()):
        for target in (text, fold(text)):
            if any(m.group(1).isupper() for m in r.finditer(target)):
                return True
    if any(r.search(lowered) or r.search(folded) for r in _ROLE_RES):  # V5: "cho sếp", "của trưởng phòng"
        return True
    for r in _BARE_NAMED_RES + (_DEVICE_BARE_RES if device else ()):  # V5: tên trần
        for target in (text, fold(text)):
            if any(_looks_like_name(m.group(1)) for m in r.finditer(target)):
                return True
    return False


def _has_employee_id(text: str, requester_id: str) -> bool:
    requester = requester_id.strip().casefold()
    for piece in text.split():
        token = piece.strip(_EDGE_PUNCT).casefold()
        if _EMPLOYEE.fullmatch(token) and token != requester:
            return True
    return False


def device_mention_reason(
    text: str, requester_id: str, slots: Mapping[str, str], prefixes: frozenset[str] | None = None
) -> FlagReason | None:
    """vpn/software (không xét khoá bị bỏ): `identifier` (mã nhân viên khác người gửi) | `phrase` | `device_text` | None. Mã máy trong câu:
    `slots.device_ids_in_text(cued=True)` — tiền tố ∈ `prefixes`, hoặc tiền tố lạ ngay sau "máy/laptop/pc/thiết bị" (Q4)."""
    if _has_employee_id(text, requester_id):
        return "identifier"
    if _has_phrase(text, device=True):
        return "phrase"
    software = str(slots.get("software_name") or "")
    known = {str(slots.get("device_id") or "").upper()} | device_ids_in_text(software, prefixes, cued=True)
    if device_ids_in_text(text, prefixes, cued=True) - known:
        return "device_text"
    return None


def mention_reason(
    text: str, requester_id: str, *, ignore: Iterable[str] = (), device_prefixes: frozenset[str] | None = None
) -> MentionReason | None:
    """Câu có nêu người KHÁC người gửi không — `identifier` | `phrase` | None. `ignore`: giá trị slot tài nguyên đã sạch (A1)."""
    if _has_identifier(text, requester_id, _ignored_values(ignore), device_prefixes):
        return "identifier"
    if _has_phrase(text):
        return "phrase"
    return None


def mentions_other_target(
    text: str, requester_id: str, *, ignore: Iterable[str] = (), device_prefixes: frozenset[str] | None = None
) -> bool:
    return mention_reason(text, requester_id, ignore=ignore, device_prefixes=device_prefixes) is not None


def requester_id_of(state: Mapping[str, Any]) -> str:
    """user_id người gửi (B1) từ state — thiếu (test node trần) → "" (mọi định danh đều là "người khác": thận trọng)."""
    rc = state.get("requester_context")
    return "" if rc is None else RequesterContext.model_validate(rc).user_id


def target_check(
    intent: str | None,
    slots: Mapping[str, str],
    dropped: Mapping[str, str],
    spec_keys: frozenset[str],
    text: str,
    requester_id: str,
    *,
    device_prefixes: frozenset[str] | None = None,
    sibling_slots: Iterable[Mapping[str, str]] = (),
    own_span: str | None = None,
) -> tuple[bool, FlagReason | None]:
    """(câu nêu người khác?, lý do bật cờ hoặc None). `slots` = slot SẠCH hiện có (clarify: đã gộp); `dropped` = khoá bị bỏ ở lượt
    này. vpn/software → `device_mention_reason` + khoá máy/người bị bỏ (be-target-guard-2); intent khác → (False, None).
    Q4: `device_prefixes` = `SlotsFile.device_prefixes`; `sibling_slots` = slot SẠCH của các ý chạy được khác cùng câu (B5); `own_span` =
    span của chính ý (B5) — chỉ dùng cho account/access."""
    if intent in DEVICE_INTENTS:  # be-target-guard-2
        dev_reason = device_mention_reason(text, requester_id, slots, device_prefixes)
        dev_mention = dev_reason in ("identifier", "phrase")
        if "device_id" in dropped or "target_user" in dropped:
            return dev_mention, "dropped"
        return dev_mention, dev_reason
    if intent not in TARGET_USER_INTENTS:
        return False, None
    ignore = [v for k, v in slots.items() if k in RESOURCE_SLOTS]
    ignore += [v for sib in sibling_slots for k, v in sib.items() if k in RESOURCE_SLOTS and _sibling_ignorable(v, own_span)]
    mention = mention_reason(text, requester_id, ignore=ignore, device_prefixes=device_prefixes)
    if "target_user" in dropped:
        return mention is not None, "dropped"
    if slots.get("target_user"):
        return mention is not None, None
    if mention is not None:
        return True, mention
    if any(r == "unknown_key" and k not in spec_keys for k, r in dropped.items()):
        return False, "unknown_key"
    return False, None
