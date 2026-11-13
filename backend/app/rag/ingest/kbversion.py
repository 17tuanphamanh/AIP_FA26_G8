"""Định danh phiên bản KB (thiết kế Phase 3 mục 5.7; PLAN-3b mục 4.6; Q-3b-2, Q-3b-8).

- `kb_version`: sha256 của danh sách `doc_id:version` ĐÃ SẮP của tài liệu enabled — không phụ thuộc thứ tự file,
  tài liệu disabled không ảnh hưởng. Collection = `kb_<kb_version>`.
- `content_sha256`: front matter chuẩn (MỌI trường, kể cả mặc định và `enabled`) + thân bài đã normalize — sửa bất kỳ
  chữ nào mà không tăng `version` thì bước 4 dừng (3-Q4).
- `pipeline_sha`: cấu hình tách từ + chia đoạn. Ghi vào metadata collection; lệch với collection đang chạy → ingest
  dừng (Q-3b-8), 3c `retrieve` so cùng hàm này.
"""

import importlib.metadata
import json
from collections.abc import Iterable
from hashlib import sha256
from pathlib import Path

from app.rag.bm25 import CODE_RE, HASH_NAME, TOKENIZER_VERSION
from app.rag.ingest.config import CHUNK_TEXT_MAX, CHUNK_TOKENS_MAX, CHUNK_TOKENS_MIN
from app.rag.models import Doc, FrontMatter


def kb_version(docs: Iterable[Doc]) -> str:
    return sha256("\n".join(sorted(f"{d.fm.doc_id}:{d.fm.version}" for d in docs if d.fm.enabled)).encode()).hexdigest()


def canonical_front_matter(fm: FrontMatter) -> str:
    return json.dumps(fm.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def content_sha256(doc: Doc) -> str:
    return sha256((canonical_front_matter(doc.fm) + "\n" + doc.body).encode()).hexdigest()


def pipeline_sha(config_dir: Path) -> str:
    parts = {
        "abbrev": sha256((config_dir / "vi_abbrev.yaml").read_bytes()).hexdigest(),
        "stopwords": sha256((config_dir / "vi_stopwords.txt").read_bytes()).hexdigest(),
        "chunk": [CHUNK_TOKENS_MIN, CHUNK_TOKENS_MAX, CHUNK_TEXT_MAX],
        "code_re": CODE_RE.pattern,
        "hash": HASH_NAME,
        "pyvi": importlib.metadata.version("pyvi"),
        "tokenizer": TOKENIZER_VERSION,  # R3 (13/11): phiên bản logic `tokenize_vi` — đổi thì ingest lại
    }
    return sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()
