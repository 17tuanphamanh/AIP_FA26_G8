"""Tên miền công ty của stack compose (soát 12/11, câu hỏi tên miền — TA 13/11 "xử lý hết"): `settings.company_email_domains` mặc định
`congty-abc.vn` (giá trị mẫu), còn người dùng seed của mock AD dùng `@demo-corp.local` → email công ty bị che như email ngoài.

Sửa ở compose (không đổi mặc định `settings.py`, test/eval PII offline giữ nguyên): truyền `COMPANY_EMAIL_DOMAINS` cho backend + worker,
mặc định = tên miền email của seed mock. `.env` đặt giá trị khác thì thắng.
"""

import json
import re
from pathlib import Path

import yaml
from pydantic import TypeAdapter

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
SEED = json.loads((ROOT / "mock_services" / "seed.json").read_text(encoding="utf-8"))


def _default(service: str) -> str:
    raw = COMPOSE["services"][service]["environment"]["COMPANY_EMAIL_DOMAINS"]
    m = re.fullmatch(r"\$\{COMPANY_EMAIL_DOMAINS:-(.*)\}", raw)
    assert m, raw
    return m.group(1)


def test_backend_va_worker_nhan_ten_mien_cua_seed() -> None:
    seed_domains = {u["email"].rsplit("@", 1)[1] for u in SEED["users"] if u.get("email")}
    assert seed_domains == {"demo-corp.local"}
    for service in ("backend", "worker"):
        assert TypeAdapter(list[str]).validate_json(_default(service)) == sorted(seed_domains)
