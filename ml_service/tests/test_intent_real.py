"""Gói 2 (D-53) — ca "có model" của `intent-clf`: nạp bản safetensors THẬT (`convert_intent_pt.py`), chấm 3 câu đối chiếu.

Điểm đối chiếu (MẪU A g2-intent): gói gốc chấm trên CPU — nhãn `vpn` phải cao nhất và lệch ≤ 0,01; lệch hơn → đỏ (báo lại,
chưa dùng thư mục đó). Fixture 10 câu lệch ≤ 1e-4 làm sau. Thiếu biến/torch → bỏ qua kèm lý do (máy không có model).

Chạy: `make test-ml` với `INTENT_MODEL_DIR` (đường trên máy, vd `ml_models/intent-clf/v3.1-seed42-st`), `INTENT_MODEL_SHA256`,
`INTENT_MANIFEST_SHA256` (và `ML_MODELS_ROOT` nếu gốc khác `<repo>/ml_models`) trong môi trường.
"""

import importlib.util
import os
import secrets
from pathlib import Path

import pytest
from app.intent import LABELS, check_intent, classify_intent_sync
from app.settings import MlSettings

pytestmark = pytest.mark.ml_real

REPO = Path(__file__).resolve().parents[2]
NEEDED = ("INTENT_MODEL_DIR", "INTENT_MODEL_SHA256", "INTENT_MANIFEST_SHA256")
TOLERANCE = 0.01
REFERENCE = (
    ("VPN công ty dùng cổng nào?", "vpn", 0.973),
    ("gia hạn VPN cho máy LAP-0501", "vpn", 0.986),
    ("vpn không vào được", "vpn", 0.985),
)


def test_real_intent_reference_points() -> None:
    missing = [name for name in NEEDED if not os.environ.get(name)]
    if missing:
        pytest.skip(f"thiếu biến {missing} — máy không có model intent")
    if importlib.util.find_spec("torch") is None:
        pytest.skip("thiếu torch — chạy với `uv run --group ml`")
    from app.intent_model import load_intent

    root = Path(os.environ.get("ML_MODELS_ROOT") or REPO / "ml_models")
    settings = MlSettings(ml_service_token=secrets.token_urlsafe(32), ml_models_root=root,  # type: ignore[call-arg]
                          intent_model_dir=Path(os.environ["INTENT_MODEL_DIR"]),
                          intent_model_sha256=os.environ["INTENT_MODEL_SHA256"],
                          intent_manifest_sha256=os.environ["INTENT_MANIFEST_SHA256"])  # fmt: skip
    spec = check_intent(settings)
    assert spec is not None
    intent = load_intent(spec)
    report = []
    for text, label, expected in REFERENCE:
        out = classify_intent_sync(intent, text)
        assert list(out.probs) == list(LABELS) and not out.truncated
        top = max(out.probs, key=lambda k: out.probs[k])
        print(f"{label}={out.probs[label]:.4f} (đối chiếu {expected}) cao nhất={top} ({len(text)} ký tự)")
        report.append((top == label, abs(out.probs[label] - expected), out.probs[label], expected))
    bad = [r for r in report if not r[0] or r[1] > TOLERANCE]
    assert not bad, f"lệch > {TOLERANCE} hoặc sai nhãn cao nhất: {bad}"
