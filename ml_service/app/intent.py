"""POST /classify_intent (intent-clf đa nhãn, B3a — D-32) — Phase 3 chưa có model của nhóm.

Chưa nạp model (phần 2 ML-GAN): luôn 503 `model_missing` (Q-3a-13) → B3 đi đường LLM.
"""

from fastapi.responses import JSONResponse

from app.classify import model_missing


def intent_missing() -> JSONResponse:
    return model_missing()
