"""ml — client của ml-service (P4, thiết kế Phase 3 mục 4.5). Chỉ phụ thuộc `core` + `tools.retry`
(hợp đồng `ml-only-core` trong `.importlinter`). `rag`, `guard`, `graph` import module này."""

from app.ml.client import MlClient
from app.ml.ports import MlContractError, MlError, MlPort, MlResult

__all__ = ["MlClient", "MlContractError", "MlError", "MlPort", "MlResult"]
