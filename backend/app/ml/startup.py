"""Cảnh báo lúc khởi động khi bật B2 `review` mà ml-service chưa nạp model chặn tấn công (gói 1, D-52; ĐT 4.7).

Khi đó `/classify` trả `model_missing` cho mọi câu → B2 chạy như `shadow` (không ai nghi gì) — không phải lỗi khởi động (đường
an toàn vẫn đủ: LLM chấm xem mọi câu không khớp regex), nhưng người vận hành phải thấy. Đọc `/health` của ml-service (không cần
token); đọc lỗi → cảnh báo "không kiểm được", KHÔNG chặn khởi động. Chỉ log trạng thái, không log URL.
"""

import logging
from typing import Literal

import httpx

log = logging.getLogger(__name__)

type GuardStatus = Literal["loaded", "missing", "unknown"]


async def guard_status(http: httpx.AsyncClient, base_url: str) -> GuardStatus:
    try:
        r = await http.get(f"{base_url.rstrip('/')}/health")
        r.raise_for_status()
        injection = r.json()["models"]["injection"]
    except (httpx.HTTPError, httpx.InvalidURL, ValueError, KeyError, TypeError):
        return "unknown"
    if injection == "missing":
        return "missing"
    return "loaded" if isinstance(injection, dict) and injection.get("version") else "unknown"


async def warn_if_guard_missing(http: httpx.AsyncClient, base_url: str) -> GuardStatus:
    status = await guard_status(http, base_url)
    if status == "missing":
        log.warning("B2_CLASSIFIER_MODE=review nhưng ml-service báo model chặn tấn công model_missing — B2 chạy như shadow")
    elif status == "unknown":
        log.warning("B2_CLASSIFIER_MODE=review: không đọc được /health của ml-service — chưa kiểm được model chặn tấn công")
    return status
