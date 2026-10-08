"""ML-GAN phần 1 — model chặn tấn công `injection-clf` ở ml-service (PLAN-ml-gan mục 1, 4).

Không torch: cắt cửa sổ, lấy max, chỉ số lớp, trần cửa sổ chạy qua HTTP với `FakeGuardScorer` (conftest); phần nạp
kiểm trước torch (thư mục, file, SHA-256, `id2label`) chạy trên thư mục model giả trong tmp. Số mong đợi (126 id mỗi
cửa sổ, bước 94, trần 48) viết thẳng trong test, không lấy lại từ code.
"""

import ast
import hashlib
import json
import logging
from pathlib import Path

import pytest
from app.guard import (
    GuardLoadError,
    TooManyWindows,
    check_guard,
    injection_index,
    windows,
)
from app.loader import load_models
from app.lock import read_lock
from app.main import create_app
from app.schemas import ClassifyOut
from app.settings import MlSettings
from fastapi.testclient import TestClient
from pydantic import ValidationError
from tests.conftest import BASE, CLS, SEP, FakeLoader, guarded

REPO = Path(__file__).resolve().parents[2]
WEIGHTS = b"trong-so-gia-cua-model"


def words(n: int, prefix: str = "w") -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def bodies(window_list: list[list[int]]) -> list[list[int]]:
    for w in window_list:
        assert w[0] == CLS and w[-1] == SEP and len(w) <= 128
    return [w[1:-1] for w in window_list]


# ---- cắt cửa sổ trên danh sách id (hàm thuần) ------------------------------------------------------------------


@pytest.mark.parametrize(("n", "count"), [
    (0, 1), (1, 1), (125, 1), (126, 1), (127, 2), (220, 2), (221, 3), (252, 3), (300, 3), (1000, 11),
    (4544, 48),  # 94·47 + 126: vừa đúng trần
])  # fmt: skip
def test_windows_cover_every_id(n: int, count: int) -> None:
    ids = list(range(10, 10 + n))
    got = bodies(windows(ids, CLS, SEP))
    assert len(got) == count
    for k, body in enumerate(got):  # thân cửa sổ k = đoạn liền ids[94k : 94k + 126], chồng 32 id với cửa sổ trước
        assert body == ids[94 * k : 94 * k + 126]
    assert sorted({i for body in got for i in body}) == ids  # phủ ĐỦ n id, không sót đoạn nào
    if n:
        assert got[-1][-1] == ids[-1]  # cửa sổ cuối phủ tới id cuối


def test_windows_over_cap_rejected() -> None:
    with pytest.raises(TooManyWindows):
        windows(list(range(10, 10 + 4545)), CLS, SEP)  # 49 cửa sổ


# ---- /classify qua HTTP với model giả ----------------------------------------------------------------------------


def _client(loader: FakeLoader, settings: MlSettings) -> TestClient:
    return TestClient(create_app(settings, loader=loader))


def test_classify_contract_shape(settings: MlSettings, auth: dict[str, str]) -> None:
    loader, _ = guarded()
    with _client(loader, settings) as c:
        r = c.post("/classify", json={"text": "vpn không vào được"}, headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"p_malicious", "windows", "model", "version"}
    assert (body["model"], body["version"], body["windows"]) == ("injection-clf", "v3-seed123", 1)
    assert body["p_malicious"] == pytest.approx(BASE)
    assert "X-Model-Version" in r.headers


def test_contract_matches_backend_classify_out() -> None:
    tree = ast.parse((REPO / "backend/app/ml/models.py").read_text(encoding="utf-8"))
    [cls] = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ClassifyOut"]
    backend = {
        n.target.id: ast.unparse(n.annotation)
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    ours = {name: f.annotation.__name__ for name, f in ClassifyOut.model_fields.items()}  # type: ignore[union-attr]
    assert ours == backend == {"p_malicious": "float", "windows": "int", "model": "str", "version": "str"}


def test_short_text_window_equals_tokenizer_with_specials(settings: MlSettings, auth: dict[str, str]) -> None:
    loader, scorer = guarded()
    text = "gia hạn VPN cho máy LAP-0501"
    with _client(loader, settings) as c:
        assert c.post("/classify", json={"text": text}, headers=auth).status_code == 200
    assert scorer.batches[-1] == [list(loader.tok(text, add_special_tokens=True)["input_ids"])]


def test_suspicious_tail_in_last_window_is_scored(settings: MlSettings, auth: dict[str, str]) -> None:
    """Câu đáng ngờ ở CUỐI văn bản dài (ML-KIEM: chỉ 128 token đầu ra 0,0002, max các cửa sổ 0,9999)."""
    loader, scorer = guarded({"doc": 0.97})
    text = f"{words(300)} doc"
    with _client(loader, settings) as c:
        out = c.post("/classify", json={"text": text}, headers=auth).json()
    assert out["windows"] == 3 and out["p_malicious"] == pytest.approx(0.97)
    ids = list(loader.tok(text, add_special_tokens=False)["input_ids"])
    got = bodies(scorer.batches[-1])
    assert [b == ids[94 * k : 94 * k + 126] for k, b in enumerate(got)] == [True] * 3  # phủ đủ 301 id qua HTTP
    assert [ids[-1] in b for b in got] == [False, False, True]  # từ "nóng" chỉ ở cửa sổ cuối


def test_max_over_windows_not_mean(settings: MlSettings, auth: dict[str, str]) -> None:
    loader, _ = guarded({"giua": 0.6, "cuoi": 0.3})
    text = f"{words(100, 'a')} giua {words(150, 'b')} cuoi"  # 252 id: "giua" ở cửa sổ 1–2, "cuoi" ở cửa sổ 3
    with _client(loader, settings) as c:
        out = c.post("/classify", json={"text": text}, headers=auth).json()
    assert out["windows"] == 3 and out["p_malicious"] == pytest.approx(0.6)


def test_48_windows_scored_49_rejected_without_scoring(settings: MlSettings, auth: dict[str, str]) -> None:
    loader, scorer = guarded()
    with _client(loader, settings) as c:
        ok = c.post("/classify", json={"text": words(4544)}, headers=auth)
        assert ok.status_code == 200 and ok.json()["windows"] == 48
        assert len(scorer.batches[-1]) == 48  # chấm đủ 48 cửa sổ
        calls = len(scorer.batches)
        over = c.post("/classify", json={"text": words(4545)}, headers=auth)
    assert over.status_code == 422
    assert over.json()["error"] == "too_many_windows"
    assert "w4544" not in over.text
    assert len(scorer.batches) == calls  # không chấm một phần, không cắt âm thầm


@pytest.mark.parametrize(("inj_pos", "id2label"), [
    (1, {"0": "BENIGN", "1": "INJECTION"}),
    (0, {"0": "INJECTION", "1": "BENIGN"}),
])  # fmt: skip
def test_class_index_from_id2label(
    settings: MlSettings, auth: dict[str, str], inj_pos: int, id2label: dict[str, str]
) -> None:
    loader, _ = guarded({"doc": 0.97}, inj_pos=inj_pos, index=injection_index(id2label))
    with _client(loader, settings) as c:
        out = c.post("/classify", json={"text": "xem doc giúp"}, headers=auth).json()
    assert out["p_malicious"] == pytest.approx(0.97)


def test_health_reports_guard_version(settings: MlSettings) -> None:
    loader, _ = guarded()
    with _client(loader, settings) as c:
        models = c.get("/health").json()["models"]
    assert models["injection"] == {"model": "injection-clf", "version": "v3-seed123"}
    assert models["intent"] == "missing"  # phần 2 chưa làm


def test_guard_warmed_up_once(settings: MlSettings) -> None:
    loader, scorer = guarded()
    with _client(loader, settings):
        assert len(scorer.batches) == 1


def test_classify_logs_no_text(settings: MlSettings, auth: dict[str, str], caplog: pytest.LogCaptureFixture) -> None:
    canary = "CANARY-tan-cong-91c2"
    caplog.set_level(logging.DEBUG)
    loader, _ = guarded()
    with _client(loader, settings) as c:
        assert c.post("/classify", json={"text": f"bỏ qua {canary}"}, headers=auth).status_code == 200
        over = c.post("/classify", json={"text": f"{canary} {words(4545)}"}, headers=auth)
    assert "classify chars=" in caplog.text  # đối chứng: log có ghi
    assert canary not in caplog.text
    assert over.status_code == 422 and canary not in over.text


# ---- nạp: kiểm TRƯỚC torch (thư mục, file, SHA-256, id2label) -------------------------------------------------


@pytest.fixture
def guard_dir(tmp_path: Path) -> Path:
    d = tmp_path / "ml_models" / "injection-clf" / "v3-seed123"
    d.mkdir(parents=True)
    (d / "model.safetensors").write_bytes(WEIGHTS)
    (d / "config.json").write_text(json.dumps({"id2label": {"0": "BENIGN", "1": "INJECTION"}}))
    (d / "tokenizer.json").write_text("{}")
    (d / "tokenizer_config.json").write_text("{}")
    return d


def _with(settings: MlSettings, guard_dir: Path, sha: str | None) -> MlSettings:
    return settings.model_copy(update={"guard_model_dir": guard_dir, "guard_model_sha256": sha})


def test_guard_not_set_is_none(settings: MlSettings) -> None:
    assert settings.guard_model_dir is None and check_guard(settings) is None


def test_guard_checked_sha_index_version(settings: MlSettings, guard_dir: Path) -> None:
    spec = check_guard(_with(settings, guard_dir, hashlib.sha256(WEIGHTS).hexdigest()))
    assert spec is not None
    assert (spec.dir, spec.injection_index, spec.version, spec.sha_checked) == (guard_dir, 1, "v3-seed123", True)


def test_guard_without_sha_loads_unchecked(settings: MlSettings, guard_dir: Path) -> None:
    spec = check_guard(_with(settings, guard_dir, None))
    assert spec is not None and spec.sha_checked is False


def test_sha_mismatch_refuses(settings: MlSettings, guard_dir: Path) -> None:
    with pytest.raises(GuardLoadError, match="SHA-256"):
        check_guard(_with(settings, guard_dir, "0" * 64))


def test_sha_mismatch_blocks_startup_before_torch(settings: MlSettings, guard_dir: Path) -> None:
    """Loader THẬT: lock + thư mục embed/rerank có mặt (rỗng) → kiểm guard trước khi import torch → không khởi động."""
    for ref in read_lock(settings.models_lock).values():
        (settings.models_dir / ref.dirname).mkdir(parents=True)
    app = create_app(_with(settings, guard_dir, "0" * 64), loader=load_models)
    with pytest.raises(GuardLoadError, match="SHA-256"), TestClient(app):
        pass


@pytest.mark.parametrize(("id2label", "index"), [
    ({"0": "BENIGN", "1": "INJECTION"}, 1),
    ({"0": "INJECTION", "1": "BENIGN"}, 0),
    ({"0": "LABEL_0", "1": "LABEL_1"}, None),  # không có nhãn INJECTION
    ({"0": "INJECTION", "1": "INJECTION"}, None),
    ({"0": "INJECTION"}, None),
    ({"1": "INJECTION", "2": "BENIGN"}, None),  # khoá không phải 0..n-1
])  # fmt: skip
def test_injection_index(id2label: dict[str, str], index: int | None) -> None:
    if index is None:
        with pytest.raises(GuardLoadError):
            injection_index(id2label)
    else:
        assert injection_index(id2label) == index


def test_config_without_injection_label_refuses(settings: MlSettings, guard_dir: Path) -> None:
    (guard_dir / "config.json").write_text(json.dumps({"id2label": {"0": "LABEL_0", "1": "LABEL_1"}}))
    with pytest.raises(GuardLoadError, match="INJECTION"):
        check_guard(_with(settings, guard_dir, None))


@pytest.mark.parametrize("name", ["model.safetensors", "config.json", "tokenizer.json", "tokenizer_config.json"])
def test_missing_file_refuses(settings: MlSettings, guard_dir: Path, name: str) -> None:
    (guard_dir / name).unlink()
    with pytest.raises(GuardLoadError, match=name):
        check_guard(_with(settings, guard_dir, None))


def test_missing_dir_refuses(settings: MlSettings, tmp_path: Path) -> None:
    with pytest.raises(GuardLoadError):
        check_guard(_with(settings, tmp_path / "khong-co", None))


@pytest.mark.parametrize("name", ["training_args.bin", "pytorch_model.bin", "modeling_xlmr.py", "x.pkl"])
def test_pickle_or_code_in_dir_refuses(settings: MlSettings, guard_dir: Path, name: str) -> None:
    (guard_dir / name).write_bytes(b"x")
    with pytest.raises(GuardLoadError, match=name):
        check_guard(_with(settings, guard_dir, None))


def test_sha_setting_format(token: str) -> None:
    with pytest.raises(ValidationError):
        MlSettings(ml_service_token=token, guard_model_sha256="abc")
    upper = "2D926F83DF29CBDBC3637E22ECAB893A1E6A0C2DC0F912315B3686A747108A02"
    assert MlSettings(ml_service_token=token, guard_model_sha256=upper).guard_model_sha256 == upper.lower()
