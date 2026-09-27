"""`make models` — tải model của ml-service về máy, ghim revision HF (3-Q19, 3-Q21).

Chạy: `uv run --with huggingface_hub python scripts/download_models.py [MODELS_DIR]` (mặc định `./models`).
`--tokenizer-only DIR` (`make tokenizer`, Q-3b-11): chỉ 3 file tokenizer của bge-m3 đúng revision trong lock, vào
`DIR/<repo>@<rev>/` — cho test chunker `tokenizer_real`; đã có `tokenizer.json` thì bỏ qua, không cần mạng.
Chỉ cần `huggingface_hub`, không kéo torch. Cần mạng tới huggingface.co.

- Chưa có `ml_service/models.lock.json` → lấy SHA commit HIỆN TẠI của từng repo, tải đúng SHA đó, rồi GHI
  lock (commit file này — test tĩnh đòi revision 40 hex).
- Đã có lock → tải đúng SHA đã ghim. Repo trong lock khác `REPOS` hoặc revision không phải 40 hex → dừng,
  không tự sửa lock (đổi model/revision là quyết định có chủ đích: xoá lock rồi chạy lại).

Thư mục: `MODELS_DIR/<repo>@<sha>` — khớp `ml_service/app/lock.py`. Container mount read-only, image đặt
`HF_HUB_OFFLINE=1`: không tải gì lúc chạy. Bỏ file không dùng: ONNX, trọng số colbert/sparse của bge-m3,
và `pytorch_model.bin` khi repo đã có `model.safetensors` (khỏi tải trùng ~2 GB).
"""

import json
import re
import sys
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

LOCK = Path(__file__).resolve().parents[1] / "ml_service" / "models.lock.json"
REPOS = {"embed": "BAAI/bge-m3", "rerank": "BAAI/bge-reranker-v2-m3"}
REVISION = re.compile(r"^[0-9a-f]{40}$")
ALWAYS_IGNORE = ["onnx/*", "*.onnx", "colbert_linear.pt", "sparse_linear.pt", "imgs/*"]
TOKENIZER_FILES = ["tokenizer.json", "tokenizer_config.json", "special_tokens_map.json"]


class LockMismatch(Exception):
    """Lock không khớp danh sách model của script — dừng, không ghi đè."""


def plan(lock: Mapping[str, Any] | None, resolve: Callable[[str], str]) -> dict[str, dict[str, str]]:
    """Model cần tải: theo lock nếu có, không thì SHA hiện tại (`resolve(repo)`)."""
    if lock is None:
        entries = {key: {"repo": repo, "revision": resolve(repo)} for key, repo in REPOS.items()}
    else:
        if set(lock) != set(REPOS):
            raise LockMismatch(f"lock có mục {sorted(lock)}, script cần {sorted(REPOS)}")
        entries = {}
        for key, repo in REPOS.items():
            entry = lock[key]
            if entry.get("repo") != repo:
                raise LockMismatch(f"{key}: lock ghi repo {entry.get('repo')!r}, script cần {repo!r}")
            entries[key] = {"repo": repo, "revision": entry.get("revision")}
    for key, entry in entries.items():
        if not isinstance(entry["revision"], str) or not REVISION.match(entry["revision"]):
            raise LockMismatch(f"{key}: revision {entry['revision']!r} không phải SHA 40 hex")
    return entries


def ignore_patterns(files: Iterable[str]) -> list[str]:
    names = set(files)
    extra = ["pytorch_model.bin"] if "model.safetensors" in names else []
    return ALWAYS_IGNORE + extra


def tokenizer_target(lock: Mapping[str, Any], out_dir: Path) -> tuple[str, str, Path]:
    """(repo, revision, thư mục đích) của tokenizer bge-m3 — lock phải hợp lệ (40 hex), không tự resolve."""
    entry = plan(lock, lambda repo: "")["embed"]
    return entry["repo"], entry["revision"], out_dir / f"{entry['repo']}@{entry['revision']}"


def tokenizer_only(out_dir: Path, *, lock_path: Path = LOCK, download: Callable[..., Any] | None = None) -> int:
    if not lock_path.exists():
        print(f"make tokenizer: thiếu {lock_path} — chạy make models trước (không tự tạo lock)", file=sys.stderr)
        return 1
    try:
        repo, rev, target = tokenizer_target(json.loads(lock_path.read_text(encoding="utf-8")), out_dir)
    except LockMismatch as e:
        print(f"make tokenizer: {e}", file=sys.stderr)
        return 1
    if (target / "tokenizer.json").is_file():
        print(f"tokenizer: đã có {target / 'tokenizer.json'} — bỏ qua")
        return 0
    if download is None:
        from huggingface_hub import snapshot_download

        download = snapshot_download
    print(f"tokenizer: {repo}@{rev} → {target}")
    download(repo, revision=rev, local_dir=target, allow_patterns=TOKENIZER_FILES)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "--tokenizer-only":
        if len(argv) != 3:
            print("dùng: download_models.py --tokenizer-only DIR", file=sys.stderr)
            return 2
        return tokenizer_only(Path(argv[2]))
    from huggingface_hub import HfApi, snapshot_download

    models_dir = Path(argv[1]) if len(argv) > 1 else Path("models")
    api = HfApi()
    existing = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else None
    try:
        entries = plan(existing, lambda repo: str(api.model_info(repo).sha))
    except LockMismatch as e:
        print(f"make models: {e}", file=sys.stderr)
        return 1
    for key, entry in entries.items():
        repo, rev = entry["repo"], entry["revision"]
        target = models_dir / f"{repo}@{rev}"
        files = api.list_repo_files(repo, revision=rev)
        print(f"{key}: {repo}@{rev} → {target}")
        snapshot_download(repo, revision=rev, local_dir=target, ignore_patterns=ignore_patterns(files))
    if existing is None:
        LOCK.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"đã ghi {LOCK} — commit file này")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
