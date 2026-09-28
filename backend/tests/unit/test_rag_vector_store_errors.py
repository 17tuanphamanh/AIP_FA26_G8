"""Phần `_classify` của c26 (3c, mục 3.2) — phân loại lỗi Qdrant thành `VectorStoreTransient` (retry được),
`CollectionNotFound` (404, không retry) hoặc `VectorStoreError` gốc (lỗi hợp đồng, nổi lên E9). Phần còn lại của
c26 (SpyIndex → `RetrievalSystemError`) làm ở S5 khi có `Retriever._call`."""

import httpx
import pytest
from app.rag.vector_store import (
    CollectionNotFound,
    VectorStoreError,
    VectorStoreTransient,
    _classify,
)
from qdrant_client.common.client_exceptions import ResourceExhaustedResponse
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse


def _unexpected(status: int) -> UnexpectedResponse:
    return UnexpectedResponse(status, "x", b"{}", httpx.Headers({}))


@pytest.mark.parametrize(
    "exc",
    [
        ResponseHandlingException(httpx.ConnectTimeout("timeout")),
        ResponseHandlingException(httpx.ConnectError("refused")),
        ResourceExhaustedResponse("rate limited", 1),
        _unexpected(500),
        _unexpected(503),
        _unexpected(429),
        httpx.ConnectError("refused thô, không qua qdrant-client"),
        httpx.ReadTimeout("timeout thô"),
    ],
    ids=["transport-timeout", "transport-connect", "resource-exhausted", "500", "503", "429", "raw-connect",
         "raw-timeout"],
)  # fmt: skip
def test_classify_transient_errors(exc: Exception) -> None:
    err = _classify("op", exc)
    assert type(err) is VectorStoreTransient


def test_classify_404_as_collection_not_found() -> None:
    err = _classify("op", _unexpected(404))
    assert type(err) is CollectionNotFound


@pytest.mark.parametrize(
    "exc",
    [
        _unexpected(400),
        _unexpected(401),
        _unexpected(422),
        ResponseHandlingException(ValueError("schema JSON hỏng")),
    ],
    ids=["400", "401", "422", "response-parse-error"],
)  # fmt: skip
def test_classify_other_errors_as_base_vector_store_error(exc: Exception) -> None:
    err = _classify("op", exc)
    assert type(err) is VectorStoreError


def test_all_returned_types_are_vector_store_error_subclasses() -> None:
    """3b bắt `VectorStoreError` — mọi lớp con phải vẫn khớp `except VectorStoreError`."""
    for exc in (_unexpected(500), _unexpected(404), _unexpected(400)):
        assert isinstance(_classify("op", exc), VectorStoreError)


def test_classify_message_keeps_the_operation_label() -> None:
    assert "query kb_abc" in str(_classify("query kb_abc", _unexpected(500)))
