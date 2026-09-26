"""Mock hệ thống ngoài (P5 mục 7): AD, VPN, phần mềm, file server, `/_admin/faults`, seed.json.

Chạy: `uvicorn app.main:app --port 8100` (PYTHONPATH=mock_services). Token dịch vụ đọc từ env
`SVC_AGENT_TOKEN`, `SVC_EXECUTOR_TOKEN`, `SVC_WORKER_TOKEN`; thiếu thì endpoint cần token trả 503.
"""

from pathlib import Path

from fastapi import FastAPI

from app import ad, admin_faults, fileserver, software, vpn
from app.admin_faults import FaultTable, fault_middleware
from app.security import ServiceTokens
from app.state import SEED_PATH, Now, build_state, load_seed, system_now


def create_app(
    tokens: ServiceTokens | None = None, seed_path: Path = SEED_PATH, now: Now = system_now
) -> FastAPI:
    app = FastAPI(title="servicedesk-mock")
    app.state.tokens = tokens if tokens is not None else ServiceTokens.from_env()
    app.state.faults = FaultTable()
    app.state.dummy_hash = ad.dummy_hash()

    def reload() -> dict[str, int]:
        # Đọc lại file mỗi lần reset: sửa seed.json rồi `make seed` là thấy ngay, không cần restart.
        seed = load_seed(seed_path)
        app.state.mock = build_state(seed, now)
        return {"users": len(seed.users), "devices": len(seed.devices)}

    reload()  # seed sai schema → không khởi động
    app.state.reload = reload
    app.middleware("http")(fault_middleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for module in (ad, vpn, software, fileserver, admin_faults):
        app.include_router(module.router)
    return app


app = create_app()
