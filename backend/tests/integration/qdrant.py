"""Qdrant thật cho test integration (thiết kế Phase 3 mục 3.8) — cùng tag image với `docker-compose.yml`
(test tĩnh `test_ingest_deploy.py` so hai chỗ)."""

import re

from qdrant_client import QdrantClient
from qdrant_client.models import DeleteAlias, DeleteAliasOperation

QDRANT_IMAGE = "qdrant/qdrant:v1.19.1"
_KB = re.compile(r"^kb_")


def wipe_kb(url: str, alias: str = "kb_current") -> None:
    """Xoá alias `kb_current` và mọi collection `kb_*` (kèm snapshot) — mỗi test bắt đầu từ Qdrant trống."""
    client = QdrantClient(url=url, timeout=60)
    try:
        if any(a.alias_name == alias for a in client.get_aliases().aliases):  # 1.19 không có delete_alias()
            client.update_collection_aliases(
                change_aliases_operations=[DeleteAliasOperation(delete_alias=DeleteAlias(alias_name=alias))]
            )
        for c in client.get_collections().collections:
            if _KB.match(c.name):
                for snap in client.list_snapshots(c.name):
                    client.delete_snapshot(c.name, snap.name, wait=True)
                client.delete_collection(c.name)
    finally:
        client.close()
