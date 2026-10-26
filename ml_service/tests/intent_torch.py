"""Gói `intent-clf` GIẢ NHỎ cùng kiến trúc (gói 2, D-53) cho test marker `ml_torch` — cần torch + transformers, KHÔNG mạng.

Tokenizer fast dựng bằng `tokenizers` (WordLevel, tách khoảng trắng, `<s> … </s>`), encoder XLM-R 1 lớp ẩn 16 chiều dựng từ
config; trọng số ngẫu nhiên có seed, đầu ra phóng to để điểm không dồn về 0,5. Chỉ import trong test đã `importorskip("torch")`.
"""

import json
from pathlib import Path
from typing import Any

import torch
from safetensors.torch import save_file
from tests.conftest import INTENT_LABELS
from tests.intent_dirs import CONFIG, REQ_MASK, THRESHOLDS, sha, write_manifest

WORDS = (
    "vpn", "VPN", "không", "vào", "được", "công", "ty", "dùng", "cổng", "nào", "?", "gia", "hạn", "cho", "máy", "LAP", "-",
    "0501", "mật", "khẩu", "phần", "mềm", "quyền", "thư", "mục", "xin", "chào",
)  # fmt: skip
HIDDEN = 16
MAX_LEN = 12  # nhỏ để test cờ truncated; config thật 160


def build_tokenizer(out: Path) -> None:
    from tokenizers import Tokenizer, models, pre_tokenizers, processors
    from transformers import PreTrainedTokenizerFast

    vocab = {"<s>": 0, "<pad>": 1, "</s>": 2, "<unk>": 3, **{w: i + 4 for i, w in enumerate(dict.fromkeys(WORDS))}}
    tok = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.Whitespace()
    tok.post_processor = processors.TemplateProcessing(single="<s> $A </s>", special_tokens=[("<s>", 0), ("</s>", 2)])
    fast = PreTrainedTokenizerFast(
        tokenizer_object=tok, bos_token="<s>", eos_token="</s>", unk_token="<unk>", pad_token="<pad>",
        cls_token="<s>", sep_token="</s>",
    )  # fmt: skip
    fast.save_pretrained(str(out))


def build_encoder_config(out: Path, vocab_size: int) -> None:
    from transformers import XLMRobertaConfig

    cfg = XLMRobertaConfig(
        vocab_size=vocab_size, hidden_size=HIDDEN, num_hidden_layers=1, num_attention_heads=2, intermediate_size=32,
        max_position_embeddings=40, pad_token_id=1, bos_token_id=0, eos_token_id=2, type_vocab_size=1,
    )  # fmt: skip
    cfg.save_pretrained(str(out))


def make_state(model_dir: Path, seed: int = 0) -> dict[str, Any]:
    """state_dict của B3Model nhỏ (dựng trên CPU thường, không meta) — khoá `enc.*`, `tok_head.1`, `att`, `seq_head.1/.4`."""
    from app.intent_model import B3Model
    from transformers import AutoConfig, AutoModel

    torch.manual_seed(seed)
    cfg = AutoConfig.from_pretrained(str(model_dir / "encoder_config"), local_files_only=True)
    model = B3Model(AutoModel.from_config(cfg, add_pooling_layer=False), 5, 23, REQ_MASK, 0.1)
    with torch.no_grad():
        for name, p in model.named_parameters():
            if not name.startswith("enc."):
                p.normal_(0.0, 1.5)  # đầu ra đủ lớn để softmax/sigmoid phân biệt rõ
    return {k: v.detach().clone().contiguous() for k, v in model.state_dict().items()}


def write_tiny_package(root: Path, *, name: str = "v3.1-seed42-st", seed: int = 0,
                       state_over: dict[str, Any] | None = None, drop: tuple[str, ...] = (),
                       dtype: Any = torch.float32) -> tuple[Path, str, str]:  # fmt: skip
    """Thư mục nạp được (bản safetensors) dưới `root/intent-clf/<name>` → (thư mục, SHA trọng số, SHA manifest)."""
    d = root / "intent-clf" / name
    d.mkdir(parents=True)
    build_tokenizer(d / "tokenizer")
    from transformers import AutoTokenizer

    vocab_size = len(AutoTokenizer.from_pretrained(str(d / "tokenizer"), local_files_only=True))
    build_encoder_config(d / "encoder_config", vocab_size)
    state = make_state(d, seed)
    state.update(state_over or {})
    for key in drop:
        state.pop(key)
    save_file({k: v.to(dtype) for k, v in state.items()}, str(d / "model.safetensors"))
    (d / "inference_config.json").write_text(json.dumps({**CONFIG, "max_len": MAX_LEN}), encoding="utf-8")
    (d / "thresholds.json").write_text(json.dumps(THRESHOLDS), encoding="utf-8")
    return d, sha((d / "model.safetensors").read_bytes()), write_manifest(d)


def write_source_package(src: Path, *, seed: int = 0) -> dict[str, Any]:
    """Gói GỐC như Duy Anh giao: `seed_42.pt` (state_dict phẳng FP16) + inference_config (`model_files = ["seed_42.pt"]`)."""
    tmp_root = src.parent / f".{src.name}-dung"
    d, _, _ = write_tiny_package(tmp_root, seed=seed)
    src.mkdir(parents=True)
    for sub in ("tokenizer", "encoder_config"):
        (d / sub).rename(src / sub)
    from safetensors.torch import load_file

    state = load_file(str(d / "model.safetensors"))
    torch.save({k: v.half() for k, v in state.items()}, src / "seed_42.pt")
    cfg = {**CONFIG, "max_len": MAX_LEN, "model_files": ["seed_42.pt"], "thresholds": [0.75] * len(INTENT_LABELS)}
    (src / "inference_config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return state
