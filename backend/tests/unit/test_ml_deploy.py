"""ml-service trên compose/Makefile/Dockerfile (thiết kế Phase 3 mục 4.7, 4.10, 3-Q9, 3-Q21, Q-3a-1/8) — đọc file
cấu hình, không cần Docker. `make up` + a15 (tắt ml-service → 503) do người chạy trên stack thật."""

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
REQUIRED_TOKEN = re.compile(r"^\$\{ML_SERVICE_TOKEN:\?[^}]+\}$")


def compose() -> dict[str, Any]:
    return yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))


def makefile_target(name: str) -> str:
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    found = re.search(rf"^{re.escape(name)}:.*?\n((?:\t.*\n)+)", text, re.MULTILINE)
    assert found, f"không có target {name}"
    return found.group(1)


def test_ml_service_internal_only_models_read_only() -> None:
    svc = compose()["services"]["ml-service"]
    assert "ports" not in svc  # không bind 8200 ra host (P4 mục 5)
    assert svc["build"] == {"context": ".", "dockerfile": "ml_service/Dockerfile"}
    assert svc["volumes"] == [
        "${MODELS_DIR:-./models}:/models:ro",
        "${TEAM_MODELS_DIR:-./ml_models}:/ml_models:ro",  # ML-GAN: model của nhóm, chỉ đọc
    ]
    assert svc["healthcheck"]["start_period"] == "240s"  # ML-GAN chốt 4: thêm SHA-256 + nạp model của nhóm
    assert "8200/health" in " ".join(svc["healthcheck"]["test"])


def test_ml_token_required_everywhere_without_default() -> None:
    c = compose()
    assert REQUIRED_TOKEN.match(c["services"]["ml-service"]["environment"]["ML_SERVICE_TOKEN"])
    assert REQUIRED_TOKEN.match(c["x-backend-env"]["ML_SERVICE_TOKEN"])  # backend + worker
    for name in ("backend", "worker"):
        assert REQUIRED_TOKEN.match(c["services"][name]["environment"]["ML_SERVICE_TOKEN"])
    assert "ML_SERVICE_TOKEN" not in c["services"]["mock"]["environment"]


def test_no_empty_numeric_env_passed_to_ml_service() -> None:
    """Chuỗi rỗng cho trường số là lỗi cấu hình: ML_MAX_CONCURRENCY không truyền, không `:-}`.
    ML_THREADS TRUYỀN tường minh từ Q-3a-16 (S9, PLAN-3c mục 6.2) — mặc định "4" (tier ②), không rỗng.
    ML-GAN: ba biến model của nhóm (đường dẫn / chuỗi, rỗng = không nạp) là các biến DUY NHẤT được rỗng."""
    env = compose()["services"]["ml-service"]["environment"]
    optional = {"GUARD_MODEL_DIR", "GUARD_MODEL_SHA256", "INTENT_MODEL_DIR"}
    assert set(env) == {"ML_SERVICE_TOKEN", "MODELS_DIR", "ML_THREADS"} | optional
    assert env["ML_THREADS"] == "${ML_THREADS:-4}"
    assert {k for k, v in env.items() if str(v).endswith(":-}")} == optional
    assert all(env[k] == f"${{{k}:-}}" for k in optional)


def test_rag_rerank_k_passed_through_backend_env() -> None:
    """Q-3a-16 (S9): RAG_RERANK_K ghi đè được qua env, mặc định "10" (tier ②), không rỗng."""
    env = compose()["x-backend-env"]
    assert env["RAG_RERANK_K"] == "${RAG_RERANK_K:-10}"


@pytest.mark.parametrize("name", ["backend", "worker"])
def test_b2_classifier_mode_passed_to_backend_and_worker(name: str) -> None:
    """ML-GAN: rỗng = mặc định `shadow` ở settings.py (một nguồn); backend và worker cùng giá trị."""
    assert compose()["services"][name]["environment"]["B2_CLASSIFIER_MODE"] == "${B2_CLASSIFIER_MODE:-}"


@pytest.mark.parametrize("name", ["backend", "worker"])
def test_backend_and_worker_wait_for_ml_healthy(name: str) -> None:
    depends = compose()["services"][name]["depends_on"]
    assert depends["ml-service"] == {"condition": "service_healthy"}


def test_ml_dockerfile_offline_no_models_group_ml() -> None:
    text = (REPO / "ml_service/Dockerfile").read_text(encoding="utf-8")
    assert "HF_HUB_OFFLINE=1" in text and "TRANSFORMERS_OFFLINE=1" in text
    assert "uv sync --frozen --no-dev --group ml --no-install-project" in text
    copies = [line for line in text.splitlines() if line.startswith("COPY")]
    assert copies, "Dockerfile không có COPY nào"
    assert not any(re.search(r"(^|\s|/)models/?(\s|$)", line) for line in copies)  # không copy models/
    assert any("ml_service/models.lock.json" in line for line in copies)
    assert '"--workers", "1"' in text


def test_torch_cpu_index_for_linux_and_no_flagembedding() -> None:
    py = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    ml = py["dependency-groups"]["ml"]
    assert not any(d.lower().startswith("flagembedding") for d in ml)
    assert any(d.startswith("sentence-transformers") for d in ml) and "onnxruntime" in ml
    index = {i["name"]: i for i in py["tool"]["uv"]["index"]}
    assert index["pytorch-cpu"]["url"] == "https://download.pytorch.org/whl/cpu"
    assert index["pytorch-cpu"]["explicit"] is True
    assert py["tool"]["uv"]["sources"]["torch"] == [
        {"index": "pytorch-cpu", "marker": "sys_platform == 'linux'"}
    ]
    lock = (REPO / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "flagembedding"' not in lock and 'name = "nvidia-' not in lock


def test_makefile_ml_targets() -> None:
    test = makefile_target("test")
    assert 'uv run pytest ml_service/tests -o pythonpath=ml_service -m "not ml_real"' in test
    test_ml = makefile_target("test-ml")
    assert "--group ml" in test_ml and "-m ml_real" in test_ml
    models = makefile_target("models")
    assert "--with huggingface_hub" in models and "--group ml" not in models  # không kéo torch
    assert "scripts/download_models.py" in models
    assert "--cache-dir .mypy_cache/ml_service ml_service/app" in makefile_target("lint")
    bench = makefile_target("ml-bench")
    assert "exec -T ml-service python -m app.bench" in bench and "docker stats --no-stream" in bench
    up = makefile_target("up")
    assert "python -m app.lock" in up and "make models" in up
    assert "build ml-service" in up and "logs --tail 50 ml-service" in up


def test_env_example_token_blank_and_no_empty_numbers() -> None:
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    assert "ML_SERVICE_TOKEN=" in lines  # tên, không giá trị
    assert not any(re.match(r"^(ML_THREADS|ML_MAX_CONCURRENCY|MODELS_DIR)=", line) for line in lines)


def test_models_dir_ignored_lock_tracked() -> None:
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/models/" in ignore
    assert "/ml_models/*/*/" in ignore  # ML-GAN: thư mục phiên bản model của nhóm; ml_models/README.md vẫn tracked
    assert not any("models.lock" in line for line in ignore if not line.startswith("#"))
