"""Gói 1 (D-52/D-53) — `scripts/eval/b3_offline.py`: số offline B3 (gói intent gốc) cho 45 + 10 câu lượt 17/10.

Viết TỪ ĐẶC TẢ, trước code: `docs/spec/claude/dac-ta-bat-2-model.md` mục 6.1 (chạy `intent_inference.py` gốc CHỈ sau khi
kiểm SHA ĐẦY ĐỦ của `seed_42.pt`, torch ≥ 2.6, CPU; D-43: bảng giao Duy Anh (F11) chỉ gồm id, intent đúng, intent LLM, điểm
model — không có `status`, `exit_code`, `outcome` hay gì từ B6 trở đi); `PLAN-B2REVIEW.md` mục 4 #5 (Q-B2R-12), mục 8
(chữ ký `verify_sha`, `require_torch`, `load_checkpoint(path, sha, *, loader)`, `f11_rows`).

Không torch: `loader` giả. `tables`/`mask_report` và phần "đầu file kết quả có `pt_sha256`, `code_sha256`" chưa phủ — mục 8
không định nghĩa dạng dòng vào của `tables`/`mask_report`, và đầu file chỉ sinh ở bước `score` (cần torch).
"""

import hashlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from tests.unit._b2review import load_script

F11_KEYS = ["id", "intent_dung", "intent_llm", "diem_model"]
CONTENT = b"trong-so-gia-seed-42"


@pytest.fixture
def bo(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load_script("scripts/eval/b3_offline.py", monkeypatch)


@pytest.fixture
def pt(tmp_path: Path) -> Path:
    path = tmp_path / "seed_42.pt"
    path.write_bytes(CONTENT)
    return path


SHA = hashlib.sha256(CONTENT).hexdigest()


# ---- verify_sha, require_torch ------------------------------------------------------------------------------------------


def test_verify_sha_ok(bo: ModuleType, pt: Path) -> None:
    assert bo.verify_sha(pt, SHA) == SHA


@pytest.mark.parametrize("expected", [
    "0" * 64,  # lệch
    SHA[:8] + "…" + SHA[-5:],  # bản rút gọn kiểu D-44 (`3efd3bd0…46db9`) — không nhận
    SHA[:63],  # thiếu ký tự
    SHA + "0",
    "",
])  # fmt: skip
def test_verify_sha_rejects(bo: ModuleType, pt: Path, expected: str) -> None:
    with pytest.raises(ValueError):
        bo.verify_sha(pt, expected)


@pytest.mark.parametrize("version", ["2.6.0", "2.6.0+cpu", "2.7.1", "2.10.0", "3.0.0"])
def test_require_torch_ok(bo: ModuleType, version: str) -> None:
    bo.require_torch(version)


@pytest.mark.parametrize("version", ["2.5.1", "2.5.1+cpu", "1.13.1", "2.4.0"])
def test_require_torch_too_old(bo: ModuleType, version: str) -> None:
    with pytest.raises(RuntimeError):
        bo.require_torch(version)


# ---- load_checkpoint: SHA TRƯỚC mọi torch.load --------------------------------------------------------------------------------


def test_load_checkpoint_sha_mismatch_never_calls_loader(bo: ModuleType, pt: Path) -> None:
    calls: list[tuple[Any, ...]] = []

    def loader(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return "da-nap"

    with pytest.raises(ValueError):
        bo.load_checkpoint(pt, "f" * 64, loader=loader)
    assert calls == []


def test_load_checkpoint_sha_ok_calls_loader_once(bo: ModuleType, pt: Path) -> None:
    calls: list[tuple[Any, ...]] = []

    def loader(*args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return "da-nap"

    assert bo.load_checkpoint(pt, SHA, loader=loader) == "da-nap"
    assert len(calls) == 1


# ---- f11_rows (D-43: đúng 4 cột) ----------------------------------------------------------------------------------------------


def _b3_row(id: str, gold: Any, labels: list[str], probs: dict[str, float], **extra: Any) -> dict[str, Any]:
    """Dạng dòng vào mục 8 không ghim: đưa cả trường của `ket-qua.json` (`gold`, `labels` — `cong5.evaluate`) lẫn tên cột
    F11 (`intent_dung`, `intent_llm`, `diem_model`) và điểm model (`probs`)."""
    return {"id": id, "kind": "intent" if isinstance(gold, str) else "multi", "gold": gold, "labels": labels,
            "intent_dung": gold, "intent_llm": labels, "diem_model": probs, "probs": probs, **extra}  # fmt: skip


def test_f11_rows_exactly_four_keys_in_order(bo: ModuleType) -> None:
    rows = [_b3_row("i1", "vpn", ["vpn"], {"vpn": 0.9, "account": 0.1}, status="S_RESOLVED", exit_code="E5",
                    outcome="single", text="CÂU-BÍ-MẬT", b6={"x": 1}, ticket="t-1"),
            _b3_row("m1", ["account", "vpn"], ["account"], {"vpn": 0.4, "account": 0.7}, exit_code=None)]  # fmt: skip
    out = bo.f11_rows(rows)
    assert [list(r) for r in out] == [F11_KEYS, F11_KEYS]
    assert [r["id"] for r in out] == ["i1", "m1"]
    assert all(r["intent_dung"] and r["diem_model"] is not None for r in out)  # dạng giá trị do script chọn
    for leak in ("CÂU-BÍ-MẬT", "E5", "S_RESOLVED", "single", "t-1"):  # D-43: không gì ngoài 4 cột
        assert leak not in repr(out)
