"""Mock hệ thống ngoài (P5) — Phase 1a chỉ có /health để compose dựng được.

AD, VPN, phần mềm, file server, /_admin/faults và seed.json làm ở task mock (P5).
"""

from fastapi import FastAPI

app = FastAPI(title="servicedesk-mock")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
