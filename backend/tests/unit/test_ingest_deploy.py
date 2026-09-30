"""b28 — `make ingest`, `make tokenizer`, CI, image backend (PLAN-3b mục 8, Q-3b-11) — đọc file cấu hình, không cần
Docker. `make ingest` thật do người chạy trên stack (`make up`)."""

import re
from pathlib import Path

import yaml
from tests.integration.qdrant import QDRANT_IMAGE
from tests.unit.test_ml_deploy import makefile_target

REPO = Path(__file__).resolve().parents[3]


def test_ingest_target_mounts_kb_read_only_without_deps() -> None:
    body = makefile_target("ingest")
    assert "$(BUILD_BACKEND)" in body  # Phase 4 P4: build backend qua biến chung (mang --build-arg GIT_SHA)
    assert "--no-deps" in body and "--rm" in body
    assert '"$(abspath $(KB_DIR)):/srv/kb:ro"' in body
    assert "python -m app.rag.ingest.cli --kb-dir /srv/kb $(ARGS)" in body
    assert "TODO" not in body
    assert re.search(r"^KB_DIR \?= kb$", (REPO / "Makefile").read_text(encoding="utf-8"), re.MULTILINE)


def test_tokenizer_target() -> None:
    body = makefile_target("tokenizer")
    assert "uv run --with huggingface_hub python scripts/download_models.py --tokenizer-only $(TOKENIZER_DIR)" in body
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    assert re.search(r"^TOKENIZER_DIR \?= \./models/_tokenizer$", text, re.MULTILINE)
    phony = next(line for line in text.splitlines() if line.startswith(".PHONY:"))
    assert {"ingest", "tokenizer"} <= set(phony.split())


def test_backend_image_has_no_kb() -> None:
    dockerfile = (REPO / "backend" / "Dockerfile").read_text(encoding="utf-8")
    assert not re.search(r"^COPY\s+kb\b", dockerfile, re.MULTILINE)


def test_ci_downloads_tokenizer_before_tests() -> None:
    steps = yaml.safe_load((REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))["jobs"][
        "lint-test"]["steps"]  # fmt: skip
    runs = [s.get("run", "") for s in steps]
    tok = runs.index("make tokenizer")
    assert tok < runs.index("make test")
    cache = [s for s in steps[:tok] if str(s.get("uses", "")).startswith("actions/cache@")]
    assert cache and cache[0]["with"]["path"] == "models/_tokenizer"


def test_cli_cannot_choose_local_tokenizer() -> None:
    source = (REPO / "backend" / "app" / "rag" / "ingest" / "cli.py").read_text(encoding="utf-8")
    assert "LocalTokenizerCounter" not in source
    assert not re.search(r"^\s*(import tokenizers|from tokenizers\b)", source, re.MULTILINE)
    assert "MlTokenCounter(ml)" in source


def test_qdrant_test_image_matches_compose() -> None:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["qdrant"]["image"] == QDRANT_IMAGE
