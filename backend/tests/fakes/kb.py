"""Tiện ích KB cho test ingest (PLAN-3b mục 6, 9.1): đường dẫn fixture, đồng hồ cố định, bản sao tạm, file mẫu."""

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FIXTURE_KB = REPO / "backend" / "tests" / "fixtures" / "kb"
CONFIG_DIR = REPO / "config"
# Fixture ghi updated_at 2026-09-27; luật "ngày ở tương lai" so với ngày này (giờ VN).
KB_TEST_NOW = datetime(2026, 9, 28, tzinfo=UTC)

FRONT = {
    "doc_id": "KB-VPN-901", "version": "1", "request_type": "vpn", "doc_type": "faq", "owner": "it_mgr01",
    "updated_at": "2026-09-27", "sensitivity": "internal", "enabled": "true", "title": "Tài liệu thử nghiệm",
}  # fmt: skip
_VERSION = re.compile(r"^version: \d+$", re.MULTILINE)
_ENABLED = re.compile(r"^enabled: \w+$", re.MULTILINE)
BODY = "## Mục một\n\nNội dung ngắn về VPN của công ty.\n"


def copy_kb(tmp_path: Path, *, with_eval: bool = True) -> Path:
    """Bản sao fixture KB trong `tmp_path/kb` — test được sửa tự do."""
    dst = tmp_path / "kb"
    shutil.copytree(FIXTURE_KB, dst)
    if not with_eval:
        shutil.rmtree(dst / "eval")
    return dst


def doc_text(body: str = BODY, *, drop: tuple[str, ...] = (), **over: str) -> str:
    """Nội dung một file KB: front matter theo thứ tự FRONT (+ `over`, bỏ khoá trong `drop`) rồi thân bài."""
    fields = {**FRONT, **over}
    lines = [f"{k}: {v}" for k, v in fields.items() if k not in drop]
    return "---\n" + "\n".join(lines) + "\n---\n\n" + body


def write_doc(kb_dir: Path, rel: str, body: str = BODY, *, drop: tuple[str, ...] = (), **over: str) -> Path:
    path = kb_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc_text(body, drop=drop, **over), encoding="utf-8")
    return path


def set_version(kb_dir: Path, doc_id: str, version: int, *, enabled: bool | None = None) -> None:
    """Sửa `version` (và `enabled` nếu truyền) của một tài liệu trong bản sao KB. Đổi `enabled` mà KHÔNG tăng version
    là bị bước 4 chặn (Q-3b-2) — nên luôn đi cùng version mới."""
    path = kb_dir / "vpn" / f"{doc_id}.md"
    text = _VERSION.sub(f"version: {version}", path.read_text(encoding="utf-8"), count=1)
    if enabled is not None:
        text = _ENABLED.sub(f"enabled: {'true' if enabled else 'false'}", text, count=1)
    path.write_text(text, encoding="utf-8")
