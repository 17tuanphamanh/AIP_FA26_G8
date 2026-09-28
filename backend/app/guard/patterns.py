"""Nạp + biên dịch mẫu của guard (phase3 mục 8.2–8.4): `config/privacy_patterns.json` (L1),
`config/injection_patterns.json` (L2).

File sai (JSON hỏng, thiếu/thừa trường, regex không biên dịch được, sai thứ tự luật) → `PatternFileError` → backend
và worker **không khởi động** (`check_guard`, gọi trước khi đụng DB — cùng khuôn `check_llm`). Không có mẫu mặc
định trong code: file là nguồn duy nhất.

Thứ tự 10 luật L1 là hợp đồng (mục 8.3: bí mật trước, rồi entropy, rồi PII) — `PRIVACY_RULE_ORDER`. L2: ≥ 11 mẫu,
id không trùng, đủ 4 nhóm [Chốt B02 mục 0.3]; regex viết trên bản không dấu, chữ thường (không cờ).
"""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.settings import Settings

PRIVACY_FILE = "privacy_patterns.json"
INJECTION_FILE = "injection_patterns.json"
INJECTION_GROUPS = ("override", "impersonation", "system_spoof", "prompt_leak")
MIN_INJECTION_PATTERNS = 11
PRIVACY_RULE_ORDER = (
    "pem", "jwt", "api_key", "password", "otp", "entropy", "email", "phone", "cccd", "bank_account",
)  # fmt: skip
VALUE_GROUP = "v"  # nhóm tên: chỉ thay phần giá trị (mật khẩu, OTP, STK), giữ phần từ khoá

type Canonical = Literal["none", "lower", "phone", "digits"]


class PatternFileError(RuntimeError):
    """File mẫu của guard không dùng được — từ chối khởi động."""


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PrivacyRuleIn(_In):
    id: str
    kind: Literal["secret", "entropy", "pii"]
    description: str | None = None
    regex: str | None = None
    label: str | None = None  # PII: tên nhãn trong `<LABEL_n>`
    canonical: Canonical = "none"  # PII: chuẩn hoá giá trị trước khi đánh số (cùng giá trị → cùng nhãn)
    min_len: int | None = Field(default=None, ge=1)  # entropy
    min_bits: float | None = Field(default=None, gt=0)  # entropy, bit/ký tự

    @model_validator(mode="after")
    def _fields_by_kind(self) -> "PrivacyRuleIn":
        if self.kind == "entropy":
            if self.regex is not None or self.min_len is None or self.min_bits is None:
                raise ValueError(f"luật {self.id}: entropy cần min_len + min_bits, không có regex")
        elif self.regex is None or self.min_len is not None or self.min_bits is not None:
            raise ValueError(f"luật {self.id}: {self.kind} cần regex, không có min_len/min_bits")
        if (self.kind == "pii") != (self.label is not None):
            raise ValueError(f"luật {self.id}: chỉ luật pii có label (và luật pii bắt buộc có)")
        return self


class ExcludeIn(_In):
    id: str
    description: str | None = None
    regex: str


class PrivacyFileIn(_In):
    version: int
    description: str | None = None
    secret_mask: str = Field(min_length=1)
    rules: list[PrivacyRuleIn]
    entropy_exclude: list[ExcludeIn] = Field(min_length=1)


class InjectionPatternIn(_In):
    id: str = Field(pattern=r"^[A-Z]+-\d{2}$")
    group: Literal["override", "impersonation", "system_spoof", "prompt_leak"]
    description: str | None = None
    regex: str


class InjectionFileIn(_In):
    version: int
    description: str | None = None
    patterns: list[InjectionPatternIn] = Field(min_length=MIN_INJECTION_PATTERNS)


@dataclass(frozen=True)
class InjectionPattern:
    id: str
    group: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class PrivacyRule:
    id: str
    kind: Literal["secret", "entropy", "pii"]
    pattern: re.Pattern[str] | None
    label: str | None
    canonical: Canonical
    min_len: int
    min_bits: float


@dataclass(frozen=True)
class PrivacyPatterns:
    secret_mask: str
    rules: tuple[PrivacyRule, ...]
    entropy_exclude: tuple[tuple[str, re.Pattern[str]], ...]


def _compile(where: str, regex: str) -> re.Pattern[str]:
    try:
        return re.compile(regex)
    except re.error as exc:
        raise PatternFileError(f"{where}: regex không biên dịch được ({exc.msg})") from None


def _read(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PatternFileError(f"{path.name}: không đọc được ({type(exc).__name__})") from None


def _invalid(path: Path, exc: ValidationError) -> PatternFileError:
    fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
    return PatternFileError(f"{path.name}: sai cấu trúc ở {fields}")


def load_privacy_patterns(path: Path) -> PrivacyPatterns:
    try:
        spec = PrivacyFileIn.model_validate(_read(path))
    except ValidationError as exc:
        raise _invalid(path, exc) from None
    ids = tuple(r.id for r in spec.rules)
    if ids != PRIVACY_RULE_ORDER:
        raise PatternFileError(f"{path.name}: luật phải đúng thứ tự {list(PRIVACY_RULE_ORDER)}, đang là {list(ids)}")
    rules = []
    for r in spec.rules:
        pattern = _compile(f"{path.name}:{r.id}", r.regex) if r.regex is not None else None
        rules.append(PrivacyRule(r.id, r.kind, pattern, r.label, r.canonical, r.min_len or 0, r.min_bits or 0.0))
    excludes = tuple((e.id, _compile(f"{path.name}:entropy_exclude.{e.id}", e.regex)) for e in spec.entropy_exclude)
    return PrivacyPatterns(spec.secret_mask, tuple(rules), excludes)


def load_injection_patterns(path: Path) -> tuple[InjectionPattern, ...]:
    try:
        spec = InjectionFileIn.model_validate(_read(path))
    except ValidationError as exc:
        raise _invalid(path, exc) from None
    ids = [p.id for p in spec.patterns]
    if len(set(ids)) != len(ids):
        raise PatternFileError(f"{path.name}: id mẫu trùng {sorted({i for i in ids if ids.count(i) > 1})}")
    missing = set(INJECTION_GROUPS) - {p.group for p in spec.patterns}
    if missing:
        raise PatternFileError(f"{path.name}: thiếu nhóm mẫu {sorted(missing)}")
    return tuple(InjectionPattern(p.id, p.group, _compile(f"{path.name}:{p.id}", p.regex)) for p in spec.patterns)


@lru_cache
def privacy_patterns(config_dir: Path) -> PrivacyPatterns:
    return load_privacy_patterns(config_dir / PRIVACY_FILE)


@lru_cache
def injection_patterns(config_dir: Path) -> tuple[InjectionPattern, ...]:
    return load_injection_patterns(config_dir / INJECTION_FILE)


def check_guard(settings: Settings) -> None:
    """Gọi ở `create_app` và `graph/wiring.open_runtime` TRƯỚC khi đụng DB: file mẫu hỏng → không khởi động."""
    privacy_patterns(settings.config_dir)
    injection_patterns(settings.config_dir)
