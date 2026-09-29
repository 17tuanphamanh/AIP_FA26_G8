"""Quét chuỗi trong MỌI cột text/varchar/jsonb/bytea của MỌI bảng schema public (2b-3; phase3 8.7 e7, e9).

Danh sách cột lấy từ `information_schema` (không viết tay) — thêm bảng/cột mới thì phép quét tự phủ. Cột `bytea`
(blob checkpoint msgpack: chuỗi nằm nguyên dạng UTF-8) so bằng `position(convert_to(...))`.
"""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def scannable_columns(rw: AsyncEngine) -> list[Any]:
    """(bảng, cột, kiểu) của mọi cột text/jsonb/bytea ở schema public mà app_rw đọc được — liệt kê từ
    information_schema, không viết tay."""
    async with rw.connect() as conn:
        return list((await conn.execute(text(
            "SELECT c.table_name, c.column_name, c.data_type FROM information_schema.columns c "
            "JOIN information_schema.tables t USING (table_schema, table_name) "
            "WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE' "
            "AND c.data_type IN ('text', 'character varying', 'character', 'jsonb', 'json', 'bytea') "
            # tên ĐỦ schema: Postgres có thể tính hàm này trên cả dòng của information_schema trước khi
            # lọc schema — tên trần tra theo search_path → "relation collations does not exist"
            "AND has_table_privilege(current_user, format('%I.%I', c.table_schema, c.table_name), 'SELECT')"
        ))).all())  # fmt: skip


async def tables_containing(rw: AsyncEngine, needle: str) -> list[str]:
    """Bảng.cột chứa `needle` (quét toàn bộ `scannable_columns`)."""
    cols = await scannable_columns(rw)
    async with rw.connect() as conn:
        hits = []
        for table, column, dtype in cols:
            expr = (f'position(convert_to(:n, \'UTF8\') in "{column}") > 0' if dtype == "bytea"
                    else f'"{column}"::text LIKE \'%\' || :n || \'%\'')  # fmt: skip
            found = await conn.execute(text(f'SELECT 1 FROM "{table}" WHERE {expr} LIMIT 1'), {"n": needle})
            if found.first() is not None:
                hits.append(f"{table}.{column}")
        return hits
