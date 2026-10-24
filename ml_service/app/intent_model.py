"""Phần torch của `intent-clf` (gói 2, D-53; `dac-ta-bat-2-model.md` 6.2 mục 3–4): `B3Model` + nạp safetensors.

Chỉ `loader.load_models` import file này, SAU `intent.check_intent` (thư mục, SHA, manifest, config đã kiểm) — test không torch
không chạm tới. Không import/chạy mã ngoài repo: `B3Model` viết lại theo `intent_inference.py` của gói (encoder XLM-R, đầu gắn
thẻ `tok_head`, chú ý `att`, đầu câu `seq_head` trên [CLS ‖ att_pool ‖ req_pool]).

Nạp: tokenizer từ `tokenizer/`, encoder dựng từ `encoder_config/` (`local_files_only`, `trust_remote_code=False`, không tải
gì). Dựng model trên thiết bị `meta` rồi `load_state_dict(strict=True, assign=True)` từ `model.safetensors` (fp32, không
pickle) — đỉnh bộ nhớ ≈ một bản trọng số thay vì hai. Buffer không lưu (`req_mask`, `position_ids`, `token_type_ids`) khởi
tạo lại sau khi nạp; còn tham số/buffer nào trên `meta`, khác float32 → `IntentLoadError`. CPU, `eval()`, `inference_mode`,
không autocast.
"""

import logging
import time
from typing import Any

import torch
from torch import nn

from app.intent import (
    ENCODER_DIR,
    TOKENIZER_DIR,
    WEIGHTS_FILE,
    IntentLoadError,
    IntentSpec,
)
from app.models import Intent, IntentRaw

log = logging.getLogger(__name__)


class B3Model(nn.Module):
    def __init__(self, encoder: Any, n_labels: int, n_tags: int, req_mask: list[float], dropout: float) -> None:
        super().__init__()
        self.enc = encoder
        h = encoder.config.hidden_size
        self.tok_head = nn.Sequential(nn.Dropout(dropout), nn.Linear(h, n_tags))
        self.att = nn.Linear(h, 1)
        self.seq_head = nn.Sequential(
            nn.Dropout(dropout), nn.Linear(3 * h, h), nn.GELU(), nn.Dropout(dropout), nn.Linear(h, n_labels)
        )
        self.register_buffer("req_mask", torch.tensor(req_mask, dtype=torch.float32), persistent=False)

    def forward(self, input_ids: Any, attention_mask: Any) -> tuple[Any, Any]:
        h = self.enc(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        tok_logits = self.tok_head(h)
        m = attention_mask.float()
        a = self.att(h).squeeze(-1).float().masked_fill(attention_mask == 0, -1e4)
        w = torch.softmax(a, -1)
        att_pool = torch.einsum("bt,bth->bh", w, h)
        p_req = (torch.softmax(tok_logits.detach().float(), -1) * self.req_mask).sum(-1) * m
        p_req[:, 0] = 0.0
        wr = p_req / p_req.sum(1, keepdim=True).clamp_min(1e-6)
        req_pool = torch.einsum("bt,bth->bh", wr, h)
        seq_logits = self.seq_head(torch.cat([h[:, 0], att_pool, req_pool], -1))
        return seq_logits.float(), tok_logits.float()


class _TorchIntentScorer:
    def __init__(self, model: Any, tokenizer: Any, max_len: int) -> None:
        self._model = model
        self._tok = tokenizer
        self._max_len = max_len

    def score(self, text: str) -> IntentRaw:
        full_len = len(self._tok(text)["input_ids"])  # không cắt, gồm token đặc biệt — cờ truncated
        enc = self._tok(
            text, truncation=True, max_length=self._max_len, return_offsets_mapping=True, return_tensors="pt"
        )
        with torch.inference_mode():
            seq_logits, tok_logits = self._model(enc["input_ids"], enc["attention_mask"])
            tok_probs = torch.softmax(tok_logits[0], -1)
        offsets = [(int(a), int(b)) for a, b in enc["offset_mapping"][0].tolist()]
        return IntentRaw(
            seq_logits=[float(x) for x in seq_logits[0].tolist()], tok_probs=tok_probs.tolist(), offsets=offsets,
            full_len=full_len,
        )  # fmt: skip


def _reset_unsaved_buffers(model: Any, spec: IntentSpec) -> None:
    """Buffer không nằm trong state_dict còn ở `meta` sau `assign=True` → dựng lại như khi khởi tạo; lạ → từ chối."""
    for name, buf in list(model.named_buffers()):
        if not buf.is_meta:
            continue
        owner, _, leaf = name.rpartition(".")
        module = model.get_submodule(owner) if owner else model
        if name == "req_mask":
            value = torch.tensor(spec.req_mask, dtype=torch.float32)
        elif leaf == "position_ids":
            value = torch.arange(buf.shape[-1], dtype=buf.dtype).expand(buf.shape)
        elif leaf == "token_type_ids":
            value = torch.zeros(buf.shape, dtype=buf.dtype)
        else:
            raise IntentLoadError(f"buffer {name} không có trong {WEIGHTS_FILE} và không biết cách dựng lại")
        module.register_buffer(leaf, value, persistent=False)


def build_b3(spec: IntentSpec) -> Any:
    """`B3Model` rỗng (thiết bị `meta`) theo `encoder_config/` — không tải gì từ mạng."""
    from transformers import AutoConfig, AutoModel

    cfg = AutoConfig.from_pretrained(str(spec.dir / ENCODER_DIR), local_files_only=True, trust_remote_code=False)
    with torch.device("meta"):
        try:
            encoder = AutoModel.from_config(cfg, add_pooling_layer=False, trust_remote_code=False)
        except TypeError:  # model không nhận add_pooling_layer (như bản gốc)
            encoder = AutoModel.from_config(cfg, trust_remote_code=False)
        return B3Model(encoder, len(spec.labels), len(spec.tags), list(spec.req_mask), spec.dropout)


def load_weights(model: Any, spec: IntentSpec) -> None:
    from safetensors.torch import load_file

    state = load_file(str(spec.dir / WEIGHTS_FILE), device="cpu")  # safetensors: không pickle, không chạy mã
    odd = sorted(k for k, v in state.items() if v.dtype != torch.float32)
    if odd:
        raise IntentLoadError(f"{WEIGHTS_FILE}: tensor khác float32 {odd[:5]} — chuyển lại bằng convert_intent_pt.py")
    try:
        model.load_state_dict(state, strict=True, assign=True)
    except RuntimeError as e:  # thiếu/thừa khoá, sai hình — không in trọng số
        raise IntentLoadError(f"{WEIGHTS_FILE} không khớp B3Model (strict): {str(e)[:2000]}") from None
    _reset_unsaved_buffers(model, spec)
    left = [n for n, t in [*model.named_parameters(), *model.named_buffers()] if t.is_meta]
    if left:
        raise IntentLoadError(f"còn tensor chưa nạp {left[:5]}")
    wrong = [n for n, p in model.named_parameters() if p.dtype != torch.float32]
    if wrong:
        raise IntentLoadError(f"tham số khác float32 {wrong[:5]}")
    model.eval()


def load_intent(spec: IntentSpec) -> Intent:
    from transformers import AutoTokenizer

    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(
        str(spec.dir / TOKENIZER_DIR), local_files_only=True, trust_remote_code=False
    )
    if not getattr(tokenizer, "is_fast", False):  # cần offset ký tự cho p_span
        raise IntentLoadError(f"{TOKENIZER_DIR}/: cần tokenizer fast (return_offsets_mapping)")
    model = build_b3(spec)
    load_weights(model, spec)
    log.info(
        "đã nạp intent-clf %s (%d nhãn, %d tag, max_len %d, SHA-256 đã kiểm) trong %.1f s",
        spec.version, len(spec.labels), len(spec.tags), spec.max_len, time.perf_counter() - started,
    )  # fmt: skip
    return Intent(
        scorer=_TorchIntentScorer(model, tokenizer, spec.max_len), labels=spec.labels, b_req=spec.b_req,
        i_req=spec.i_req, mix=spec.mix, max_len=spec.max_len, tau_lo=dict(spec.tau_lo), tau_hi=dict(spec.tau_hi),
        version=spec.version,
    )  # fmt: skip
