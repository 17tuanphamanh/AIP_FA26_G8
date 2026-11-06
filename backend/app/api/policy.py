"""`GET /api/policy`, `GET /api/policy/versions`, `POST /api/policy/validate` — API chính sách CHỈ ĐỌC cho Trưởng BP IT (F7).

Hình dạng bám `frontend/src/api/contracts-tam.ts` (`PolicyView`, `PolicyVersionItem`) và mock `mocks/handlers/policy.ts`; P10 §3.3.

**Nguồn** = policy ĐANG CHẠY (`settings._policy_bytes`, nạp một lần mỗi tiến trình) — KHÔNG đọc bảng `policy_versions` (chưa dùng,
không có migration ở chặng này). Vì chưa có phiên bản DB nên phiên bản "hiện hành" là bản file:
`version_id = 0`, `version = "file-" + sha256(byte file)[:8]` (cùng sha ghi ở audit, `policy_sha256()`), `updated_by = null`,
`updated_at` = mtime `<config_dir>/policy.json` đọc ở lần gọi đầu cho mỗi (đường dẫn, sha) và GIỮ NGUYÊN sau đó (`loaded_at`) —
sửa file mà tiến trình chưa nạp lại thì mốc không nhảy; `is_current = true`. `/versions` trả MẢNG TRẦN đúng một mục (bản đang chạy).

**validate** chỉ KIỂM — không lưu, không đổi cache, không ghi file/DB/audit. Đúng schema `PolicyFile` + `check_policy_config`
như lúc khởi động. `check_policy_config` chỉ ném một `RuntimeError` cho cả file, nên chạy TỪNG luật một để có `loc`
`["rules", i, "action"]` (kết quả hợp: lỗi ⇔ bản gốc chạy cả file ném — test T21 ghim).
- `version_preview` = `"file-" + sha256(JSON chuẩn hoá)[:8]`; chuẩn hoá = `sort_keys=True`, `separators=(",", ":")`,
  `ensure_ascii=False`, UTF-8. KHÔNG so được với `version` của GET (cái đó băm BYTE THÔ của file, gồm thụt dòng và thứ tự khoá):
  cùng nội dung cũng cho hai giá trị khác nhau.
- `loc` tính TỪ GỐC `content` (không có tiền tố "content"), `errors(include_url=False, include_input=False)`. `ctx` CHỈ đọc để
  dựng câu (`expected` của `literal_error`), không bao giờ trả ra: `ctx` của lỗi `value_error` chứa object `ValueError` — tuần tự
  hoá thì 500. Tên khoá thừa giữ nguyên trong `loc` (khác `api.errors`, vốn đổi thành `<extra>`): thân này là policy của chính
  Trưởng BP, FE cần chỉ đúng khoá sai.
- `msg` tiếng Việt theo `type` của lỗi pydantic (`schema_msg`): `literal_error` → "Phải là một trong: <ctx.expected>"; `missing`,
  `extra_forbidden`, lỗi kiểu số nguyên / chuỗi / bool → câu cố định; `value_error` / `assertion_error` (câu tiếng Việt do validator
  của schema tự viết) → giữ nguyên `msg` gốc; loại khác → "Giá trị không hợp lệ".
- NaN/Infinity (JSON không chuẩn) bị chặn ngay lúc đọc thân (`parse_constant`, như `parse_policy`) → 422 `invalid_policy` với đúng
  một lỗi `loc == []`. Thân sai hình dạng (thiếu `content`, không phải object, khoá lạ, JSON hỏng) → 422 `invalid_request`.
- KHÔNG log nội dung policy hay `msg`: chỉ log số lỗi.

Thứ tự kiểm: 401 → 403 (`require`) → 413 (middleware, chạy trước cả auth) → 422 (đọc thân TRONG handler, sau quyền như `desk.parse_body`).
PUT `/api/policy` → 405 (path có GET); `/api/policy/versions/{id}/restore`, `/api/policy/simulate` → 404 (chưa có route).
"""

import hashlib
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from app.api.alerts import ErrorDetail, InvalidRequestBody
from app.api.errors import InvalidRequest, error_fields
from app.auth.deps import require
from app.auth.models import Principal
from app.settings import (
    PolicyFile,
    _policy_bytes,
    action_intents,
    check_policy_config,
    get_action_metadata,
    get_settings,
    get_slots,
    policy_sha256,
)

log = logging.getLogger(__name__)

router = APIRouter()

POLICY_FILE = "policy.json"
VERSION_PREFIX = "file-"
VERSION_SHA_CHARS = 8  # "file-" + 8 = 13 ký tự ≤ 16 (cột `policy_versions.version`)
FILE_VERSION_ID = 0  # chưa có phiên bản DB
STARTUP_SUFFIX = " — từ chối khởi động"  # đuôi của `check_policy_config`; vô nghĩa với người sửa policy
NON_FINITE_MSG = "NaN/Infinity không hợp lệ trong JSON policy"

# Câu lỗi schema theo `type` của pydantic — msg gốc tiếng Anh ("Input should be …") không trả cho Trưởng BP.
LITERAL_MSG = "Phải là một trong: "
FIXED_MSGS: dict[str, str] = {
    "missing": "Thiếu trường bắt buộc",
    "extra_forbidden": "Trường không được phép",
    "int_type": "Phải là số nguyên",
    "int_parsing": "Phải là số nguyên",
    "int_from_float": "Phải là số nguyên",
    "string_type": "Phải là chuỗi",
    "bool_type": "Phải là đúng/sai",
    "bool_parsing": "Phải là đúng/sai",
}
OWN_MSG_TYPES = frozenset({"value_error", "assertion_error"})  # validator của schema tự viết câu (tiếng Việt) → giữ nguyên
FALLBACK_MSG = "Giá trị không hợp lệ"


class PolicyView(BaseModel):
    """Policy đang chạy — ĐÚNG 6 khoá."""

    version_id: int
    version: str
    content: dict[str, Any]
    updated_by: str | None
    updated_at: datetime
    is_current: bool


class PolicyVersionItem(BaseModel):
    version_id: int
    version: str
    updated_by: str | None
    updated_at: datetime
    is_current: bool
    restored_from: str | None  # luôn có mặt (null) — bản file không sinh từ quay lui


class ValidateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]


class ValidateOk(BaseModel):
    valid: Literal[True]
    version_preview: str


class PolicyIssue(BaseModel):
    """Một lỗi policy: vị trí từ gốc `content` + câu lỗi. Không `input`, `url`, `ctx`."""

    loc: list[str | int]
    msg: str


class InvalidPolicy(BaseModel):
    error: Literal["invalid_policy"]
    errors: list[PolicyIssue]


READ_ERRORS: dict[int | str, dict[str, Any]] = {401: {"model": ErrorDetail}, 403: {"model": ErrorDetail}}
VALIDATE_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorDetail},
    403: {"model": ErrorDetail},
    413: {"model": ErrorDetail},
    422: {"model": InvalidPolicy | InvalidRequestBody},
}


@lru_cache
def loaded_at(path: str, sha: str) -> datetime:
    """Mốc nạp file = mtime lúc gọi đầu cho khoá (đường dẫn, sha). `sha` chỉ để làm khoá cache."""
    try:
        return datetime.fromtimestamp(Path(path).stat().st_mtime, UTC)
    except OSError:  # file biến mất sau khi nạp: policy vẫn chạy được từ bộ nhớ
        return datetime.now(UTC)


def _file_version() -> tuple[str, str]:
    sha = policy_sha256()
    return VERSION_PREFIX + sha[:VERSION_SHA_CHARS], sha


def _updated_at(sha: str) -> datetime:
    return loaded_at(str(get_settings().config_dir / POLICY_FILE), sha)


@router.get("/api/policy", response_model=PolicyView, responses=READ_ERRORS)
async def current_policy(_: Annotated[Principal, Depends(require("policy:read"))]) -> PolicyView:
    version, sha = _file_version()
    return PolicyView(
        version_id=FILE_VERSION_ID, version=version, content=json.loads(_policy_bytes().decode("utf-8")),
        updated_by=None, updated_at=_updated_at(sha), is_current=True,
    )  # fmt: skip


@router.get("/api/policy/versions", response_model=list[PolicyVersionItem], responses=READ_ERRORS)
async def policy_versions(_: Annotated[Principal, Depends(require("policy:read"))]) -> list[PolicyVersionItem]:
    version, sha = _file_version()
    item = PolicyVersionItem(
        version_id=FILE_VERSION_ID, version=version, updated_by=None, updated_at=_updated_at(sha),
        is_current=True, restored_from=None,
    )  # fmt: skip
    return [item]


class _NonFinite(ValueError):
    """`parse_constant` gặp NaN/Infinity/-Infinity."""


def _no_nan(name: str) -> float:
    raise _NonFinite(name)


def preview_version(content: dict[str, Any]) -> str:
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return VERSION_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:VERSION_SHA_CHARS]


def _config_issues(policy: PolicyFile) -> list[PolicyIssue]:
    """`check_policy_config` TỪNG luật một (cùng kiểm với lúc khởi động, nhưng biết luật nào sai)."""
    action_intents()  # action_metadata.yaml hỏng = lỗi hệ thống (500), không phải lỗi của policy đang soạn
    slots, metadata = get_slots(), get_action_metadata()
    issues: list[PolicyIssue] = []
    for i, rule in enumerate(policy.rules):
        try:
            check_policy_config(policy.model_copy(update={"rules": (rule,)}), slots, metadata)
        except RuntimeError as exc:
            issues.append(PolicyIssue(loc=["rules", i, "action"], msg=str(exc).removesuffix(STARTUP_SUFFIX)))
    return issues


def schema_msg(error: Mapping[str, Any]) -> str:
    """THUẦN: một lỗi pydantic (`ErrorDetails`) → câu tiếng Việt theo `type`. `literal_error` lấy giá trị từ `ctx.expected`
    (`'a', 'b' or 'c'` → `'a', 'b', 'c'`); thiếu `ctx.expected` → câu dự phòng."""
    kind = error.get("type")
    if kind in OWN_MSG_TYPES:
        return str(error["msg"])
    if kind == "literal_error":
        expected = (error.get("ctx") or {}).get("expected")
        if not isinstance(expected, str) or not expected:
            return FALLBACK_MSG
        return LITERAL_MSG + ", ".join(expected.rsplit(" or ", 1))
    return FIXED_MSGS.get(str(kind), FALLBACK_MSG)


def policy_issues(content: dict[str, Any]) -> list[PolicyIssue]:
    """Rỗng ⇔ policy hợp lệ. Schema `PolicyFile` trước; chỉ khi schema qua mới kiểm action thuộc intent."""
    try:
        policy = PolicyFile.model_validate(content)
    except ValidationError as exc:
        return [
            PolicyIssue(loc=list(e["loc"]), msg=schema_msg(e))
            for e in exc.errors(include_url=False, include_input=False)
        ]
    return _config_issues(policy)


def _invalid_policy(issues: list[PolicyIssue]) -> JSONResponse:
    return JSONResponse(InvalidPolicy(error="invalid_policy", errors=issues).model_dump(mode="json"), status_code=422)


async def _read_body(request: Request) -> ValidateIn | list[PolicyIssue]:
    """Thân thô → `ValidateIn`; NaN/Infinity → danh sách lỗi policy; sai hình dạng/JSON hỏng → `InvalidRequest` (422)."""
    raw = await request.body()
    try:
        data: Any = json.loads(raw, parse_constant=_no_nan) if raw else None
    except _NonFinite:
        return [PolicyIssue(loc=[], msg=NON_FINITE_MSG)]
    except (ValueError, RecursionError):
        raise InvalidRequest([]) from None
    try:
        return ValidateIn.model_validate(data)
    except ValidationError as exc:
        raise InvalidRequest(error_fields(exc.errors(include_url=False, include_input=False))) from None


@router.post("/api/policy/validate", response_model=ValidateOk, responses=VALIDATE_ERRORS)
async def validate_policy(
    request: Request, _: Annotated[Principal, Depends(require("policy:edit"))]
) -> ValidateOk | JSONResponse:
    body = await _read_body(request)
    issues = policy_issues(body.content) if isinstance(body, ValidateIn) else body
    log.info("policy validate: %d lỗi", len(issues))  # chỉ đếm — không nội dung, không msg
    if isinstance(body, ValidateIn) and not issues:
        return ValidateOk(valid=True, version_preview=preview_version(body.content))
    return _invalid_policy(issues)
