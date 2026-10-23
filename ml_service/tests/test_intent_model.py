"""Gói 2 (D-53; `dac-ta-bat-2-model.md` 6.2 mục 3–4) — phần torch của `intent-clf`: `B3Model`, nạp safetensors strict trên `meta`.

Marker `ml_torch`: cần torch + transformers (nhóm uv `ml`), dùng gói GIẢ NHỎ cùng kiến trúc (`intent_torch.py`), không mạng,
không file thật. Thiếu torch (CI) → bỏ qua. Chạy: `make test-ml` (hoặc `uv run --group ml pytest ml_service/tests
-o pythonpath=ml_service -m ml_torch`).

Đối chiếu điểm: `reference_probs` viết LẠI độc lập từ mô tả `intent_inference.py` (MẪU A duyệt) bằng phép tính tensor trần trên
`model.safetensors` — không dùng `B3Model` hay `intent.py` — nên lệch đầu nào (`att`, `req_pool`, GELU, `_anchor`, trọng số
trộn) cũng đỏ.
"""

import json
from pathlib import Path
from typing import Any

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("safetensors")

from app.intent import IntentLoadError, check_intent, classify_intent_sync
from app.intent_model import B3Model, build_b3, load_intent
from app.main import create_app
from app.settings import MlSettings
from fastapi.testclient import TestClient
from tests.conftest import INTENT_LABELS, FakeLoader
from tests.intent_dirs import intent_settings
from tests.intent_torch import HIDDEN, MAX_LEN, write_tiny_package

pytestmark = pytest.mark.ml_torch

SENTENCES = ("vpn không vào được", "VPN công ty dùng cổng nào ?", "gia hạn VPN cho máy LAP - 0501", "xin chào",
             "mật khẩu  phần mềm   quyền thư mục")  # fmt: skip
HEAD_SHAPES = {
    "tok_head.1.weight": (23, HIDDEN), "tok_head.1.bias": (23,), "att.weight": (1, HIDDEN), "att.bias": (1,),
    "seq_head.1.weight": (HIDDEN, 3 * HIDDEN), "seq_head.1.bias": (HIDDEN,), "seq_head.4.weight": (5, HIDDEN),
    "seq_head.4.bias": (5,),
}  # fmt: skip


@pytest.fixture(autouse=True)
def _offline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")  # có lỡ tải gì từ mạng thì lỗi ngay
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "ml_models"
    r.mkdir()
    return r


def _spec(settings: MlSettings, root: Path, **kw: Any) -> Any:
    d, wsha, msha = write_tiny_package(root, **kw)
    spec = check_intent(intent_settings(settings, root, d, wsha, msha))
    assert spec is not None
    return spec


def reference_probs(d: Path, text: str) -> dict[str, float]:
    """Điểm trộn của gói, tính tay theo mô tả `intent_inference.py` (CPU, fp32)."""
    from safetensors.torch import load_file
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    sd = load_file(str(d / "model.safetensors"))
    cfg = json.loads((d / "inference_config.json").read_text(encoding="utf-8"))
    tok = AutoTokenizer.from_pretrained(str(d / "tokenizer"), local_files_only=True)
    enc = AutoModel.from_config(AutoConfig.from_pretrained(str(d / "encoder_config"), local_files_only=True),
                                add_pooling_layer=False)  # fmt: skip
    enc.load_state_dict({k[4:]: v for k, v in sd.items() if k.startswith("enc.")}, strict=True)
    enc.eval()
    e = tok(text, truncation=True, max_length=cfg["max_len"], return_offsets_mapping=True)
    ids = torch.tensor([e["input_ids"]])
    with torch.no_grad():
        h = enc(input_ids=ids, attention_mask=torch.ones_like(ids)).last_hidden_state[0]
        p_tok = torch.softmax(h @ sd["tok_head.1.weight"].T + sd["tok_head.1.bias"], -1)
        w = torch.softmax((h @ sd["att.weight"].T).squeeze(-1) + sd["att.bias"], 0)
        p_req = (p_tok * torch.tensor(cfg["req_mask"])).sum(-1)
        p_req[0] = 0.0
        req_pool = (p_req / p_req.sum().clamp_min(1e-6)) @ h
        x = torch.cat([h[0], w @ h, req_pool])
        x = torch.nn.functional.gelu(x @ sd["seq_head.1.weight"].T + sd["seq_head.1.bias"])
        p_seq = torch.sigmoid(x @ sd["seq_head.4.weight"].T + sd["seq_head.4.bias"])
    tags, out = cfg["tags"], {}
    keep = [t for t, (a, b) in enumerate(e["offset_mapping"]) if b > a and text[a:b].strip()]
    w_seq, w_span, _ = cfg["mix_weights"]
    for i, label in enumerate(cfg["labels"]):
        bi, ii = tags.index(f"B-REQ:{label}"), tags.index(f"I-REQ:{label}")
        span = max((float(p_tok[t, bi] + p_tok[t, ii]) for t in keep), default=0.0)
        out[label] = w_seq * float(p_seq[i]) + w_span * span
    return out


# ---- kiến trúc khớp gói thật -------------------------------------------------------------------------------------------


def test_b3model_keys_match_package_xlmr_base() -> None:
    """Dựng B3Model trên `meta` với config XLM-R base: đúng 205 tensor, ~279,2 triệu tham số, khoá và hình như `seed_42.pt`."""
    from transformers import AutoModel, XLMRobertaConfig

    cfg = XLMRobertaConfig(vocab_size=250002, max_position_embeddings=514, type_vocab_size=1, pad_token_id=1,
                           bos_token_id=0, eos_token_id=2)  # fmt: skip
    with torch.device("meta"):
        model = B3Model(AutoModel.from_config(cfg, add_pooling_layer=False), 5, 23, [0.0] * 23, 0.1)
    sd = model.state_dict()
    assert len(sd) == 205
    assert sum(t.numel() for t in sd.values()) == pytest.approx(279.2e6, abs=0.05e6)
    heads = {k: tuple(v.shape) for k, v in sd.items() if not k.startswith("enc.")}
    assert heads == {k: tuple(768 if n == HIDDEN else 3 * 768 if n == 3 * HIDDEN else n for n in s)
                     for k, s in HEAD_SHAPES.items()}  # fmt: skip
    assert "req_mask" not in sd  # buffer không lưu


def test_tiny_package_head_keys_and_shapes(settings: MlSettings, root: Path) -> None:
    from safetensors.torch import load_file

    spec = _spec(settings, root)
    sd = load_file(str(spec.dir / "model.safetensors"))
    assert {k: tuple(v.shape) for k, v in sd.items() if not k.startswith("enc.")} == HEAD_SHAPES


# ---- nạp ---------------------------------------------------------------------------------------------------------------


def test_load_valid_package(settings: MlSettings, root: Path) -> None:
    spec = _spec(settings, root)
    model = build_b3(spec)
    from app.intent_model import load_weights

    load_weights(model, spec)
    assert not model.training
    assert all(p.dtype == torch.float32 and not p.is_meta for p in model.parameters())
    buffers = dict(model.named_buffers())
    assert not any(b.is_meta for b in buffers.values())
    assert buffers["req_mask"].tolist() == list(spec.req_mask)
    pos = buffers["enc.embeddings.position_ids"]
    assert pos[0].tolist() == list(range(pos.shape[-1]))
    assert buffers["enc.embeddings.token_type_ids"].abs().sum().item() == 0


@pytest.mark.parametrize("text", SENTENCES)
def test_scores_match_reference(settings: MlSettings, root: Path, text: str) -> None:
    spec = _spec(settings, root)
    out = classify_intent_sync(load_intent(spec), text)
    ref = reference_probs(spec.dir, text)
    assert list(out.probs) == list(INTENT_LABELS)
    for label in INTENT_LABELS:
        assert out.probs[label] == pytest.approx(ref[label], abs=1e-5), label
        assert 0.0 <= out.probs[label] <= 1.0


def test_scores_not_degenerate(settings: MlSettings, root: Path) -> None:
    """Model giả đủ "nhọn" để đối chiếu có nghĩa: điểm giữa các câu/nhãn khác nhau rõ."""
    intent = load_intent(_spec(settings, root))
    values = [p for text in SENTENCES for p in classify_intent_sync(intent, text).probs.values()]
    assert max(values) - min(values) > 0.2


def test_deterministic(settings: MlSettings, root: Path) -> None:
    intent = load_intent(_spec(settings, root))
    assert classify_intent_sync(intent, SENTENCES[0]) == classify_intent_sync(intent, SENTENCES[0])


def test_missing_key_refused(settings: MlSettings, root: Path) -> None:
    spec = _spec(settings, root, drop=("att.bias",))
    with pytest.raises(IntentLoadError, match="strict"):
        load_intent(spec)


def test_extra_key_refused(settings: MlSettings, root: Path) -> None:
    spec = _spec(settings, root, state_over={"extra.weight": torch.zeros(3)})
    with pytest.raises(IntentLoadError, match="strict"):
        load_intent(spec)


def test_wrong_shape_refused(settings: MlSettings, root: Path) -> None:
    spec = _spec(settings, root, state_over={"seq_head.4.weight": torch.zeros(4, HIDDEN)})
    with pytest.raises(IntentLoadError, match="strict"):
        load_intent(spec)


def test_fp16_weights_refused(settings: MlSettings, root: Path) -> None:
    spec = _spec(settings, root, dtype=torch.float16)
    with pytest.raises(IntentLoadError, match="float32"):
        load_intent(spec)


def test_loader_never_unpickles(settings: MlSettings, root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bộ nạp đọc safetensors — `torch.load` (pickle) không bao giờ được gọi."""
    spec = _spec(settings, root)

    def boom(*a: Any, **kw: Any) -> None:
        raise AssertionError("torch.load bị gọi")

    monkeypatch.setattr(torch, "load", boom)
    classify_intent_sync(load_intent(spec), SENTENCES[0])


@pytest.mark.parametrize(("words", "truncated"), [(MAX_LEN - 2, False), (MAX_LEN - 1, True), (3 * MAX_LEN, True)])
def test_truncated_with_real_tokenizer(settings: MlSettings, root: Path, words: int, truncated: bool) -> None:
    """max_len = 12 gồm `<s>`, `</s>`: 10 từ vừa đủ, 11 từ là bị cắt."""
    intent = load_intent(_spec(settings, root))
    text = " ".join(["vpn"] * words)
    out = classify_intent_sync(intent, text)
    assert out.truncated is truncated
    if truncated:  # model chỉ thấy max_len token đầu — điểm như câu đã cắt
        assert out.probs == pytest.approx(classify_intent_sync(intent, " ".join(["vpn"] * (MAX_LEN - 2))).probs)


def test_http_with_tiny_model(settings: MlSettings, root: Path, auth: dict[str, str]) -> None:
    spec = _spec(settings, root)
    loader = FakeLoader(intent=load_intent(spec))
    with TestClient(create_app(settings, loader=loader)) as c:
        r = c.post("/classify_intent", json={"text": SENTENCES[1]}, headers=auth)
        health = c.get("/health").json()["models"]["intent"]
    assert r.status_code == 200
    body = r.json()
    assert body["probs"] == pytest.approx(reference_probs(spec.dir, SENTENCES[1]), abs=1e-5)
    assert body["tau_hi"] == body["tau_lo"] == dict.fromkeys(INTENT_LABELS, 0.75)
    assert (body["model"], body["version"]) == ("intent-clf", "v3.1-seed42-st")
    assert health == {"model": "intent-clf", "version": "v3.1-seed42-st"}
