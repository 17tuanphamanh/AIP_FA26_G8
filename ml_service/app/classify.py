"""POST /classify (injection-clf, B2 L3) — Phase 3 chưa có model của nhóm (P11, Phase 5).

Luôn trả 503 `{"error": "model_missing"}` (Q-3a-13), kể cả khi thư mục model có mặt: chưa có loader ONNX
thì không giả vờ đã nạp. Backend thấy `model_missing` thì đi đường LLM ngay, không retry (3-Q7).
Thứ tự: token (401) → body (422) → 503.
"""

from fastapi.responses import JSONResponse

MODEL_MISSING = {"error": "model_missing"}


def model_missing() -> JSONResponse:
    return JSONResponse(MODEL_MISSING, status_code=503)
