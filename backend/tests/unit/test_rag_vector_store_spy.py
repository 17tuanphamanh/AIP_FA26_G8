"""b27 — `QdrantIndex.switch_alias` là ĐÚNG MỘT lệnh `update_collection_aliases` (Q-3b-17). Client giả ghi mọi lời gọi;
không được gọi phương thức alias nào khác (xoá rồi tạo bằng hai lệnh để lộ khe không có KB — M-3b-5)."""

from typing import Any

import pytest
from app.rag.vector_store import QdrantIndex
from qdrant_client.models import CreateAliasOperation, DeleteAliasOperation

TARGET = "kb_" + "a" * 64


class SpyClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    @property
    def alias_calls(self) -> list[tuple[str, Any]]:
        return [c for c in self.calls if "alias" in c[0]]

    def __getattr__(self, name: str) -> Any:
        async def record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, kwargs.get("change_aliases_operations", args)))

        return record


@pytest.mark.asyncio
@pytest.mark.parametrize(("had_alias", "kinds"), [
    (True, [DeleteAliasOperation, CreateAliasOperation]),
    (False, [CreateAliasOperation]),
])  # fmt: skip
async def test_switch_alias_single_atomic_call(had_alias: bool, kinds: list[type]) -> None:
    client = SpyClient()
    await QdrantIndex(client).switch_alias("kb_current", TARGET, had_alias=had_alias)  # type: ignore[arg-type]
    assert len(client.alias_calls) == 1
    name, ops = client.alias_calls[0]
    assert name == "update_collection_aliases"
    assert [type(op) for op in ops] == kinds
    create = ops[-1].create_alias
    assert (create.alias_name, create.collection_name) == ("kb_current", TARGET)
    if had_alias:
        assert ops[0].delete_alias.alias_name == "kb_current"
    assert client.calls == client.alias_calls  # không gọi gì khác
