"""Trần thời gian của `MlClient` (Q-3a-16): một lời gọi ml-service xấu nhất không được làm lượt graph treo tới mức
worker coi lượt là chết rồi recover trong khi lượt còn chạy.

Với mọi endpoint: (số lần thử) × timeout + tổng backoff < `WORKER_STALE_TURN_SECONDS` / 2 — cùng biên với
`FAKE_NODE_DELAY` (2b-4). Mọi số đọc từ hằng thật: `TIMEOUT_S` của client, `TOOL_RETRY` + `BACKOFF_BASE_SECONDS` của
`config/policy.json` (mặc định retry của `call_with_retry`), mặc định `worker_stale_turn_seconds` của `Settings`.

Biên tính cho MỘT request (một lô). Trong lượt graph, B8 gọi embed 1 câu và rerank ≤ `RAG_RERANK_K` (20) ≤ 32 đoạn →
một lô; nhiều lô (ingest 3b) chạy ngoài lượt graph.
"""

import inspect

import pytest
from app.ml import MlPort
from app.ml.client import TIMEOUT_S
from app.settings import Settings, get_policy


def worst_case_seconds(timeout: float) -> float:
    constants = get_policy().constants
    attempts = constants.TOOL_RETRY + 1
    backoff = sum(constants.BACKOFF_BASE_SECONDS * 2 ** (k - 1) for k in range(1, constants.TOOL_RETRY + 1))
    return attempts * timeout + backoff


def stale_seconds() -> float:
    default = Settings.model_fields["worker_stale_turn_seconds"].default
    assert isinstance(default, int | float) and default > 0
    return float(default)


def test_every_port_method_has_a_timeout() -> None:
    methods = {name for name, _ in inspect.getmembers(MlPort, inspect.isfunction) if not name.startswith("_")}
    assert methods, "MlPort không có phương thức nào"
    assert set(TIMEOUT_S) == methods


@pytest.mark.parametrize("endpoint", sorted(TIMEOUT_S))
def test_worst_case_call_under_half_stale_turn(endpoint: str) -> None:
    worst = worst_case_seconds(TIMEOUT_S[endpoint])
    limit = stale_seconds() / 2
    assert worst < limit, (
        f"/{endpoint}: xấu nhất {worst:.0f} s ≥ {limit:.0f} s (stale/2) — worker sẽ recover lượt còn đang chạy"
    )


def test_bound_formula_matches_call_with_retry() -> None:
    """Đối chứng công thức: TOOL_RETRY=2, backoff 1 s rồi 2 s → 3 lần thử + 3 s (P5 mục 5)."""
    constants = get_policy().constants
    assert (constants.TOOL_RETRY, constants.BACKOFF_BASE_SECONDS) == (2, 1)
    assert worst_case_seconds(10) == 33
