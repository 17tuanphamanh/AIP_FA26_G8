"""Gói 2 (D-53; `dac-ta-bat-2-model.md` 6.2) — `/classify_intent` và `check_intent`, phần KHÔNG cần torch (chạy trong CI).

Viết theo MẪU A g2-intent đã duyệt: thư mục bản safetensors (`convert_intent_pt.py`), SHA + manifest bắt buộc, `labels` đúng 5
nhãn đúng thứ tự, `len(tags) = len(req_mask) = 23`, `mix_weights[2] = 0`, `thresholds.json` đủ nhãn trong [0, 1] với
`tau_lo ≤ tau_hi`; điểm = 0,4·sigmoid(seq) + 0,6·p_span (token có offset `b > a` và `_anchor` hợp lệ); NaN → `classify_failed`;
cùng hàng chờ với `/classify`. Phần torch (B3Model, strict, safetensors) ở `test_intent_model.py`.
"""

import ast
import json
import logging
import math
import sys
import threading
from pathlib import Path
from typing import Any

import pytest
from app.guard import GuardLoadError
from app.intent import (
    IntentLoadError,
    anchor,
    check_intent,
    classify_intent_sync,
    sigmoid,
    span_probs,
)
from app.loader import load_models
from app.lock import read_lock
from app.main import create_app
from app.schemas import IntentOut
from app.settings import MlSettings
from fastapi.testclient import TestClient
from tests.conftest import (
    INTENT_LABELS,
    INTENT_TAGS,
    FakeIntentScorer,
    FakeLoader,
    fake_intent,
    raw_for,
)
from tests.intent_dirs import (
    THRESHOLDS,
    config,
    intent_settings,
    sha,
    write_intent_dir,
    write_manifest,
)
from tests.test_classify_queue import WAIT_S, BlockingReranker

REPO = Path(__file__).resolve().parents[2]
CANARY = "CANARY-intent-9f3e"
TEXT = "vpn không vào được"  # tách giả: <s>=0, vpn=1, không=2, vào=3, được=4, </s>=5


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path / "ml_models"
    r.mkdir()
    return r


def _client(loader: FakeLoader, settings: MlSettings) -> TestClient:
    return TestClient(create_app(settings, loader=loader))


def _intent_loader(scorer: FakeIntentScorer | None = None, **kw: Any) -> tuple[FakeLoader, FakeIntentScorer]:
    scorer = scorer or FakeIntentScorer()
    return FakeLoader(intent=fake_intent(scorer, **kw)), scorer


# ---- không đặt INTENT_MODEL_DIR → 503 như cũ --------------------------------------------------------------------------


def test_no_intent_dir_check_returns_none(settings: MlSettings) -> None:
    assert settings.intent_model_dir is None and check_intent(settings) is None


def test_no_intent_model_503_and_health_missing(client: TestClient, auth: dict[str, str]) -> None:
    r = client.post("/classify_intent", json={"text": TEXT}, headers=auth)
    assert (r.status_code, r.json()) == (503, {"error": "model_missing"})
    assert client.get("/health").json()["models"]["intent"] == "missing"


# ---- có model: hợp đồng ------------------------------------------------------------------------------------------------


def test_classify_intent_200_contract(settings: MlSettings, auth: dict[str, str]) -> None:
    loader, scorer = _intent_loader()
    with _client(loader, settings) as c:
        r = c.post("/classify_intent", json={"text": TEXT}, headers=auth)
        health = c.get("/health").json()["models"]
    assert r.status_code == 200 and "X-Model-Version" in r.headers
    body = r.json()
    assert set(body) == {"probs", "tau_hi", "tau_lo", "truncated", "model", "version"}
    assert (body["model"], body["version"], body["truncated"]) == ("intent-clf", "v3.1-seed42-st", False)
    assert health["intent"] == {"model": "intent-clf", "version": "v3.1-seed42-st"}
    assert scorer.texts[-1] == TEXT


def test_classify_intent_requires_token(settings: MlSettings) -> None:
    loader, scorer = _intent_loader()
    with _client(loader, settings) as c:
        warm = len(scorer.texts)
        assert c.post("/classify_intent", json={"text": TEXT}).status_code == 401
    assert len(scorer.texts) == warm


def test_intent_warmed_up_once(settings: MlSettings) -> None:
    loader, scorer = _intent_loader()
    with _client(loader, settings):
        pass
    assert len(scorer.texts) == 1


def test_contract_matches_backend_intent_out() -> None:
    tree = ast.parse((REPO / "backend/app/ml/models.py").read_text(encoding="utf-8"))
    [cls] = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "IntentOut"]
    backend = {
        n.target.id: ast.unparse(n.annotation)
        for n in cls.body
        if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
    }
    ours = {name: str(f.annotation).replace("typing.", "") if not isinstance(f.annotation, type) else f.annotation.__name__
            for name, f in IntentOut.model_fields.items()}  # fmt: skip
    assert ours == backend == {"probs": "dict[str, float]", "tau_hi": "dict[str, float]", "tau_lo": "dict[str, float]",
                               "truncated": "bool", "model": "str", "version": "str"}  # fmt: skip


# ---- điểm trộn, thứ tự nhãn, p_span -----------------------------------------------------------------------------------


def test_mixed_score_04_sigmoid_06_span() -> None:
    """vpn: p_seq = sigmoid(0) = 0,5; p_span = 0,6 + 0,2 = 0,8 → 0,4·0,5 + 0,6·0,8 = 0,68 (đảo trọng số: 0,62)."""
    raw = raw_for(TEXT, [0.0] * 5, {(1, "B-REQ:vpn"): 0.6, (1, "I-REQ:vpn"): 0.2})
    out = classify_intent_sync(fake_intent(FakeIntentScorer(raw)), TEXT)
    assert out.probs["vpn"] == pytest.approx(0.68)
    assert out.probs["account"] == pytest.approx(0.2)  # không tag nào → p_span 0


def test_probs_follow_config_label_order() -> None:
    """Khoá `probs` theo đúng thứ tự `labels` (không theo chữ cái); logit i → nhãn i."""
    logits = [-2.0, -1.0, 0.0, 1.0, 2.0]
    out = classify_intent_sync(fake_intent(FakeIntentScorer(raw_for(TEXT, logits))), TEXT)
    assert list(out.probs) == list(INTENT_LABELS) == ["account", "vpn", "software", "access", "out_of_scope"]
    for label, x in zip(INTENT_LABELS, logits, strict=True):
        assert out.probs[label] == pytest.approx(0.4 * sigmoid(x))


def test_probs_order_over_http(settings: MlSettings, auth: dict[str, str]) -> None:
    raw = raw_for(TEXT, [-2.0, -1.0, 0.0, 1.0, 2.0])
    loader, _ = _intent_loader(FakeIntentScorer(raw))
    with _client(loader, settings) as c:
        r = c.post("/classify_intent", json={"text": TEXT}, headers=auth)
    assert list(json.loads(r.text)["probs"]) == list(INTENT_LABELS)


def test_tau_from_thresholds() -> None:
    taus = {"account": (0.1, 0.8), "vpn": (0.365, 0.75), "software": (0.085, 0.905), "access": (0.2, 0.75),
            "out_of_scope": (0.372, 0.82)}  # fmt: skip
    out = classify_intent_sync(fake_intent(tau=taus), TEXT)
    assert out.tau_lo == {k: lo for k, (lo, _) in taus.items()}
    assert out.tau_hi == {k: hi for k, (_, hi) in taus.items()}


def test_special_tokens_ignored_in_span() -> None:
    """Token đặc biệt (offset (0, 0)) có P(B-REQ:account) cao nhất vẫn không tính."""
    raw = raw_for(TEXT, [0.0] * 5, {(0, "B-REQ:account"): 0.9, (5, "I-REQ:account"): 0.9, (2, "B-REQ:account"): 0.1})
    out = classify_intent_sync(fake_intent(FakeIntentScorer(raw)), TEXT)
    assert out.probs["account"] == pytest.approx(0.4 * 0.5 + 0.6 * 0.1)


def test_whitespace_only_token_ignored_by_anchor() -> None:
    text = "vpn   hỏng"
    assert anchor(text, 3, 6) == -1 and anchor(text, 2, 5) == 2 and anchor(text, 5, 8) == 6
    probs = [[0.0] * 23 for _ in range(2)]
    b, i = INTENT_TAGS.index("B-REQ:vpn"), INTENT_TAGS.index("I-REQ:vpn")
    probs[0][b] = 0.9  # token toàn khoảng trắng (3, 6)
    probs[1][i] = 0.3  # token "hỏng"
    assert span_probs(text, probs, [(3, 6), (6, 10)], [b], [i]) == [pytest.approx(0.3)]


def test_span_takes_max_over_tokens_of_b_plus_i() -> None:
    raw = raw_for(TEXT, [0.0] * 5, {(1, "B-REQ:vpn"): 0.3, (3, "B-REQ:vpn"): 0.5, (3, "I-REQ:vpn"): 0.4,
                                     (4, "I-REQ:vpn"): 0.6, (2, "B-MEN:vpn"): 0.99})  # fmt: skip
    out = classify_intent_sync(fake_intent(FakeIntentScorer(raw)), TEXT)
    assert out.probs["vpn"] == pytest.approx(0.4 * 0.5 + 0.6 * 0.9)  # tag MEN không tính


def test_no_valid_token_span_zero() -> None:
    raw = raw_for("", [0.0] * 5)
    out = classify_intent_sync(fake_intent(FakeIntentScorer(raw)), " ")
    assert all(p == pytest.approx(0.2) for p in out.probs.values())


@pytest.mark.parametrize(("full_len", "truncated"), [(160, False), (161, True)])
def test_truncated_flag_boundary(full_len: int, truncated: bool) -> None:
    raw = raw_for(TEXT, [0.0] * 5, full_len=full_len)
    assert classify_intent_sync(fake_intent(FakeIntentScorer(raw), max_len=160), TEXT).truncated is truncated


def test_sigmoid_extremes_finite() -> None:
    assert sigmoid(-1000.0) == 0.0 and sigmoid(1000.0) == 1.0 and sigmoid(0.0) == 0.5


# ---- lỗi → classify_failed -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("logit", "tag_p"), [(math.nan, 0.0), (0.0, math.inf), (0.0, math.nan)])
def test_nan_or_inf_score_classify_failed(
    settings: MlSettings, auth: dict[str, str], caplog: pytest.LogCaptureFixture, logit: float, tag_p: float
) -> None:
    """Logit NaN, hoặc xác suất tag NaN/inf → điểm không hữu hạn → 500 (logit ±inf thì sigmoid vẫn hữu hạn: hợp lệ)."""
    loader, scorer = _intent_loader()
    with _client(loader, settings) as c:
        scorer.raw = raw_for(CANARY, [0.0, logit, 0.0, 0.0, 0.0], {(1, "B-REQ:vpn"): tag_p})
        with caplog.at_level(logging.INFO):
            r = c.post("/classify_intent", json={"text": CANARY}, headers=auth)
    assert (r.status_code, r.json()) == (500, {"error": "classify_failed"})
    assert CANARY not in r.text and CANARY not in caplog.text


def test_nan_score_raises_value_error() -> None:
    raw = raw_for(TEXT, [math.nan] * 5)
    with pytest.raises(ValueError, match="không hữu hạn"):
        classify_intent_sync(fake_intent(FakeIntentScorer(raw)), TEXT)


def test_model_error_classify_failed(settings: MlSettings, auth: dict[str, str], caplog: pytest.LogCaptureFixture) -> None:
    loader, scorer = _intent_loader()
    with _client(loader, settings) as c:
        scorer.error = RuntimeError(CANARY)
        with caplog.at_level(logging.INFO):
            r = c.post("/classify_intent", json={"text": CANARY}, headers=auth)
    assert (r.status_code, r.json()) == (500, {"error": "classify_failed"})
    assert CANARY not in caplog.text and "RuntimeError" in caplog.text


def test_wrong_logit_count_classify_failed(settings: MlSettings, auth: dict[str, str]) -> None:
    loader, scorer = _intent_loader()
    with _client(loader, settings) as c:
        scorer.raw = raw_for(TEXT, [0.0] * 4)
        r = c.post("/classify_intent", json={"text": TEXT}, headers=auth)
    assert (r.status_code, r.json()) == (500, {"error": "classify_failed"})


def test_classify_intent_not_queued_behind_running_rerank(settings: MlSettings, auth: dict[str, str]) -> None:
    """Cùng hàng chờ riêng với /classify (D-52, ĐT 4.6): rerank đang GIỮ hàng embed/rerank thì classify_intent vẫn xong — phải
    xong TRƯỚC khi rerank được thả (khuôn `test_classify_not_queued_behind_running_rerank`)."""
    reranker = BlockingReranker()
    loader = FakeLoader(reranker=reranker, intent=fake_intent())
    results: dict[str, int] = {}
    with _client(loader, settings) as c:
        reranker.armed = True

        def rerank() -> None:
            results["rerank"] = c.post("/rerank", json={"query": "vpn", "passages": ["vpn lỗi"]}, headers=auth).status_code

        def intent() -> None:
            results["intent"] = c.post("/classify_intent", json={"text": TEXT}, headers=auth).status_code

        t_rerank = threading.Thread(target=rerank, daemon=True)
        t_intent = threading.Thread(target=intent, daemon=True)
        t_rerank.start()
        try:
            assert reranker.entered.wait(WAIT_S), "rerank giả chưa chạy"
            t_intent.start()
            t_intent.join(WAIT_S - 1)
            done_while_rerank_held = "intent" in results and not reranker.release.is_set()
        finally:
            reranker.release.set()
            t_rerank.join(WAIT_S)
            t_intent.join(WAIT_S)
    assert done_while_rerank_held, "classify_intent phải xong trong lúc rerank còn giữ hàng chờ embed/rerank"
    assert results == {"intent": 200, "rerank": 200}


# ---- check_intent: thư mục, SHA, manifest, config, ngưỡng (trước torch) ----------------------------------------------


def test_valid_intent_dir_accepted(settings: MlSettings, root: Path) -> None:
    d, wsha, msha = write_intent_dir(root)
    spec = check_intent(intent_settings(settings, root, d, wsha, msha))
    assert spec is not None
    assert (spec.labels, spec.version, spec.max_len, spec.mix) == (INTENT_LABELS, "v3.1-seed42-st", 160, (0.4, 0.6))
    assert spec.tau_lo == spec.tau_hi == dict.fromkeys(INTENT_LABELS, 0.75)
    assert spec.b_req == tuple(range(1, 11, 2)) and spec.i_req == tuple(range(2, 11, 2))


@pytest.mark.parametrize("name", ["seed_42.pt", "tokenizer/extra.bin", "encoder_config/m.py", "x.pkl"])
def test_pickle_or_code_file_refused(settings: MlSettings, root: Path, name: str) -> None:
    d, wsha, _ = write_intent_dir(root)
    (d / name).write_bytes(b"pickle")
    msha = write_manifest(d)  # manifest liệt kê cả file đó — vẫn từ chối
    with pytest.raises(IntentLoadError, match=Path(name).name):
        check_intent(intent_settings(settings, root, d, wsha, msha))


@pytest.mark.parametrize("missing", ["intent_model_sha256", "intent_manifest_sha256"])
def test_sha_vars_required(settings: MlSettings, root: Path, missing: str) -> None:
    d, wsha, msha = write_intent_dir(root)
    s = intent_settings(settings, root, d, wsha, msha, **{missing: None})
    with pytest.raises(IntentLoadError, match=missing.upper()):
        check_intent(s)


def test_weights_sha_mismatch_refused(settings: MlSettings, root: Path) -> None:
    d, _, msha = write_intent_dir(root)
    with pytest.raises(IntentLoadError, match="INTENT_MODEL_SHA256"):
        check_intent(intent_settings(settings, root, d, sha(b"khac"), msha))


def test_manifest_sha_mismatch_refused(settings: MlSettings, root: Path) -> None:
    d, wsha, _ = write_intent_dir(root)
    with pytest.raises(IntentLoadError, match="INTENT_MANIFEST_SHA256"):
        check_intent(intent_settings(settings, root, d, wsha, sha(b"khac")))


def test_extra_file_not_in_manifest_refused(settings: MlSettings, root: Path) -> None:
    d, wsha, msha = write_intent_dir(root)
    (d / "tokenizer" / "them.json").write_text("{}")
    with pytest.raises(IntentLoadError, match="them.json"):
        check_intent(intent_settings(settings, root, d, wsha, msha))


def test_file_changed_after_manifest_refused(settings: MlSettings, root: Path) -> None:
    d, wsha, msha = write_intent_dir(root)
    (d / "thresholds.json").write_text(json.dumps(THRESHOLDS) + " ")
    with pytest.raises(IntentLoadError, match="thresholds.json"):
        check_intent(intent_settings(settings, root, d, wsha, msha))


@pytest.mark.parametrize("missing", ["model.safetensors", "inference_config.json", "thresholds.json"])
def test_required_file_missing_refused(settings: MlSettings, root: Path, missing: str) -> None:
    d, wsha, _ = write_intent_dir(root)
    (d / missing).unlink()
    msha = write_manifest(d)
    with pytest.raises(IntentLoadError, match=missing):
        check_intent(intent_settings(settings, root, d, wsha, msha))


def test_dir_outside_root_refused(settings: MlSettings, root: Path, tmp_path: Path) -> None:
    d, wsha, msha = write_intent_dir(tmp_path / "ngoai")
    with pytest.raises(GuardLoadError, match="ML_MODELS_ROOT"):
        check_intent(intent_settings(settings, root, d, wsha, msha))


def _cfg_refused(settings: MlSettings, root: Path, cfg: dict[str, Any], match: str) -> None:
    d, wsha, msha = write_intent_dir(root, cfg=cfg)
    with pytest.raises(IntentLoadError, match=match):
        check_intent(intent_settings(settings, root, d, wsha, msha))


@pytest.mark.parametrize("w2", [0.1, 1e-9, -0.5])
def test_mix_weights_2_nonzero_refused(settings: MlSettings, root: Path, w2: float) -> None:
    _cfg_refused(settings, root, config(mix_weights=[0.4, 0.6, w2]), r"mix_weights\[2\]")


@pytest.mark.parametrize("labels", [
    ["vpn", "account", "software", "access", "out_of_scope"],  # sai thứ tự
    sorted(INTENT_LABELS),  # theo chữ cái
    ["account", "vpn", "software", "access"],  # thiếu
    [*INTENT_LABELS, "other"],  # thừa
])  # fmt: skip
def test_labels_wrong_refused(settings: MlSettings, root: Path, labels: list[str]) -> None:
    _cfg_refused(settings, root, config(labels=labels), "labels")


def test_tags_wrong_length_refused(settings: MlSettings, root: Path) -> None:
    _cfg_refused(settings, root, config(tags=list(INTENT_TAGS)[:22]), "tags")


def test_req_mask_wrong_length_refused(settings: MlSettings, root: Path) -> None:
    _cfg_refused(settings, root, config(req_mask=[0.0] * 22), "req_mask")


def test_req_mask_not_on_req_tags_refused(settings: MlSettings, root: Path) -> None:
    mask = [0.0] * 23
    mask[11] = 1.0  # B-MEN:account
    _cfg_refused(settings, root, config(req_mask=mask), "req_mask")


def test_tags_missing_req_tag_refused(settings: MlSettings, root: Path) -> None:
    tags = list(INTENT_TAGS)
    tags[1] = "B-XXX:account"
    _cfg_refused(settings, root, config(tags=tags), "B-REQ:account")


@pytest.mark.parametrize("files", [["seed_42.pt"], ["model.safetensors", "x.safetensors"], []])
def test_model_files_must_be_safetensors(settings: MlSettings, root: Path, files: list[str]) -> None:
    _cfg_refused(settings, root, config(model_files=files), "model_files")


@pytest.mark.parametrize("max_len", [0, 1, "160", True, 160.0])
def test_max_len_invalid_refused(settings: MlSettings, root: Path, max_len: Any) -> None:
    _cfg_refused(settings, root, config(max_len=max_len), "max_len")


def test_config_not_json_refused(settings: MlSettings, root: Path) -> None:
    d, wsha, _ = write_intent_dir(root)
    (d / "inference_config.json").write_text("{không phải json")
    msha = write_manifest(d)
    with pytest.raises(IntentLoadError, match="inference_config.json"):
        check_intent(intent_settings(settings, root, d, wsha, msha))


def _thr_refused(settings: MlSettings, root: Path, thresholds: dict[str, Any], match: str) -> None:
    d, wsha, msha = write_intent_dir(root, thresholds=thresholds)
    with pytest.raises(IntentLoadError, match=match):
        check_intent(intent_settings(settings, root, d, wsha, msha))


def test_thresholds_missing_label_refused(settings: MlSettings, root: Path) -> None:
    thr = {k: v for k, v in THRESHOLDS.items() if k != "vpn"}
    _thr_refused(settings, root, thr, "vpn")


def test_thresholds_extra_label_refused(settings: MlSettings, root: Path) -> None:
    _thr_refused(settings, root, {**THRESHOLDS, "printer": {"tau_lo": 0.5, "tau_hi": 0.5}}, "printer")


@pytest.mark.parametrize("row", [{"tau_lo": -0.1, "tau_hi": 0.5}, {"tau_lo": 0.5, "tau_hi": 1.1},
                                 {"tau_lo": float("nan"), "tau_hi": 0.5}, {"tau_lo": "0.5", "tau_hi": 0.5},
                                 {"tau_hi": 0.5}])  # fmt: skip
def test_thresholds_out_of_range_refused(settings: MlSettings, root: Path, row: dict[str, Any]) -> None:
    _thr_refused(settings, root, {**THRESHOLDS, "access": row}, "access")


def test_thresholds_lo_above_hi_refused(settings: MlSettings, root: Path) -> None:
    _thr_refused(settings, root, {**THRESHOLDS, "vpn": {"tau_lo": 0.679, "tau_hi": 0.365}}, "tau_lo > tau_hi")


def test_thresholds_lo_equal_hi_accepted(settings: MlSettings, root: Path) -> None:
    d, wsha, msha = write_intent_dir(root, thresholds={**THRESHOLDS, "vpn": {"tau_lo": 0.5, "tau_hi": 0.5}})
    spec = check_intent(intent_settings(settings, root, d, wsha, msha))
    assert spec is not None and spec.tau_lo["vpn"] == spec.tau_hi["vpn"] == 0.5


def test_intent_dir_blocks_startup_before_torch(
    settings: MlSettings, root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Loader THẬT: config sai → từ chối khởi động TRƯỚC khi import torch (torch giả ném nếu bị import)."""
    for ref in read_lock(settings.models_lock).values():
        (settings.models_dir / ref.dirname).mkdir(parents=True)
    d, wsha, msha = write_intent_dir(root, cfg=config(mix_weights=[0.4, 0.6, 0.2]))
    monkeypatch.setitem(sys.modules, "torch", None)  # import torch → ImportError
    s = intent_settings(settings, root, d, wsha, msha)
    with pytest.raises(IntentLoadError, match="mix_weights"), TestClient(create_app(s, loader=load_models)):
        pass
