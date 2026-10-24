"""POST /classify (injection-clf, B2 L3) — trả lời lỗi của endpoint; tính điểm ở `guard.py`.

- `GUARD_MODEL_DIR` không đặt → 503 `{"error": "model_missing"}` như Phase 3 (Q-3a-13): backend thấy `model_missing` thì
  đi đường LLM ngay, không retry (3-Q7). `/classify_intent` dùng chung `model_missing`, `classify_failed` (gói 2, `intent.py`).
- Có model → `{p_malicious, windows, model, version}`. Văn bản cần > `MAX_WINDOWS` cửa sổ → 422 `too_many_windows`
  (không chấm một phần, không cắt âm thầm; không vọng lại văn bản).
Thứ tự: token (401) → body (422) → 503 / điểm.
"""

from fastapi.responses import JSONResponse

from app.guard import MAX_WINDOWS

MODEL_MISSING = {"error": "model_missing"}
CLASSIFY_FAILED = {"error": "classify_failed"}  # gói 1 (phase5 §6.5 #10): lỗi suy luận — mã chung, không chữ đầu vào


def model_missing() -> JSONResponse:
    return JSONResponse(MODEL_MISSING, status_code=503)


def classify_failed() -> JSONResponse:
    return JSONResponse(CLASSIFY_FAILED, status_code=500)


def too_many_windows(count: int) -> JSONResponse:
    body = {"error": "too_many_windows", "windows": count, "max_windows": MAX_WINDOWS}
    return JSONResponse(body, status_code=422)
