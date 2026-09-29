"""Ngân sách thời gian MỘT lượt — hạn cho cả lượt (phase3 mục 9.0, chốt Q-3e-12; PLAN-3f S0; thay test xfail của 3e).

1. Tĩnh: trần RIÊNG từng lời gọi của lượt đầu cuối 3f (cộng từ hằng số thật, không viết tay) — tổng vượt xa
   `WORKER_STALE_TURN_SECONDS`, nên cái giữ lượt dưới ngưỡng stale là `TURN_BUDGET_S` (mọi lời gọi ra ngoài bị cắt theo
   phần còn lại − biên an toàn). Ước tính trần trên, chưa đo.
2. Khởi động: `SAFETY_MARGIN_S < TURN_BUDGET_S < WORKER_STALE_TURN_SECONDS`, sai → Settings từ chối.
3. AST: từng điểm gọi ra ngoài (registry tool, retry, MlClient, LLM gateway, RAG) có gọi helper của `core.turn_budget` —
   danh sách này là mục (6) của soát bảo mật 3f. Hành vi thật: `test_turn_deadline.py`, f19 `test_turn_worst_case.py`.
"""

import ast
from pathlib import Path

import pytest
from app.llm.config import load_llm_config
from app.ml.client import TIMEOUT_S as ML_TIMEOUT_S
from app.settings import Settings, get_policy
from app.tools.specs import READ_TIMEOUT_S
from pydantic import ValidationError

CONFIG = Path(__file__).resolve().parents[3] / "config"
APP = Path(__file__).resolve().parents[2] / "app"


def _settings(**over: object) -> Settings:
    return Settings(_env_file=None, **over)  # type: ignore[call-arg, arg-type]


def _retry_worst(timeout_s: float) -> float:
    """`tools/retry.call_with_retry` (dùng cho tool đọc và ml-service): (TOOL_RETRY+1)·timeout + Σ backoff."""
    c = get_policy().constants
    return (c.TOOL_RETRY + 1) * timeout_s + sum(c.BACKOFF_BASE_SECONDS * 2**k for k in range(c.TOOL_RETRY))


def first_turn_ceilings() -> dict[str, float]:
    """Lượt `submit` cuối 3f: B1 (AD) → B2 (ml classify → L4 fast) → B3 (ml classify_intent → LLM fast) → B6 (3 tool
    VPN SONG SONG = một trần) → B8 (RAG) → … (B10/B11 thêm ở 3g). Trần riêng, CHƯA tính hạn lượt."""
    settings = _settings()
    fast = load_llm_config(CONFIG / "llm.yaml").roles["fast"]
    return {
        "B1 ad_get_user": _retry_worst(READ_TIMEOUT_S),
        "B2 L3 ml classify": _retry_worst(ML_TIMEOUT_S["classify"]),
        "B2 L4 b02_injection_judge (fast deadline_s)": fast.deadline_s,
        "B3 ml classify_intent": _retry_worst(ML_TIMEOUT_S["classify_intent"]),
        "B3 b03_classify (fast deadline_s)": fast.deadline_s,
        "B6 3 tool VPN song song": _retry_worst(READ_TIMEOUT_S),
        "B8 rag_deadline_s": settings.rag_deadline_s,
    }


def test_budget_items_come_from_constants() -> None:
    budget = first_turn_ceilings()
    assert budget["B1 ad_get_user"] == 18.0 and budget["B2 L3 ml classify"] == 9.0  # 3·5+1+2, 3·2+1+2
    assert len(budget) == 7


def test_turn_budget_is_what_keeps_first_turn_below_stale() -> None:
    s = _settings()
    total = sum(first_turn_ceilings().values())
    assert total >= s.worker_stale_turn_seconds  # 194 s: trần riêng từng lời gọi KHÔNG đủ (lý do của 9.0)
    bound = min(total, s.turn_budget_s)  # mọi lời gọi bị cắt tới hạn lượt − biên (hành vi: test_turn_deadline, f19)
    assert bound < s.worker_stale_turn_seconds
    # sau khi hết hạn còn goto E2 + B20 (DB, không gọi ra ngoài) — phải xong trước khi worker coi là dở dang
    assert s.worker_stale_turn_seconds - s.turn_budget_s >= 10


def test_every_single_call_fits_a_fresh_turn() -> None:
    """Lượt mới (kể cả recover) luôn chạy trọn MỘT lời gọi với timeout riêng — hạn lượt chỉ cắt khi đã tiêu vào lời gọi
    trước, không cắt sẵn lời gọi đầu."""
    s = _settings()
    for name, ceiling in first_turn_ceilings().items():
        assert ceiling <= s.turn_budget_s - s.safety_margin_s, name


def test_defaults_match_plan() -> None:
    s = _settings()
    assert (s.turn_budget_s, s.safety_margin_s, s.worker_stale_turn_seconds) == (100.0, 2.0, 120.0)  # P4


@pytest.mark.parametrize(
    "over",
    [
        {"turn_budget_s": 120},  # = stale
        {"turn_budget_s": 150},  # > stale
        {"worker_stale_turn_seconds": 90, "rag_deadline_s": 40},  # stale hạ dưới hạn lượt mặc định 100
        {"safety_margin_s": 100},  # biên ≥ hạn
    ],
)
def test_settings_rejects_turn_budget_not_below_stale(over: dict[str, float]) -> None:
    with pytest.raises(ValidationError, match="TURN_BUDGET_S"):
        _settings(**over)


# ---- AST: điểm gọi ra ngoài phải qua core.turn_budget ---------------------------------------------------------------

# (file, hàm — kể cả hàm lồng) → helper phải được gọi trong thân hàm đó
CALL_SITES: dict[tuple[str, str], str] = {
    ("tools/registry.py", "call"): "cap_timeout",  # kiểm trước breaker
    ("tools/registry.py", "attempt"): "cap_timeout",  # tool đọc: timeout mỗi lần thử
    ("tools/registry.py", "_invoke"): "cap_timeout",  # tool ghi: full=True
    ("tools/retry.py", "call_with_retry"): "check_sleep",  # backoff (tool đọc, ml, Qdrant)
    ("ml/client.py", "once"): "cap_timeout",  # mọi endpoint ml-service
    ("llm/client.py", "_run"): "window",  # deadline gateway = min(vai trò, hạn lượt)
    ("rag/retriever.py", "retrieve"): "window",
    ("rag/expand.py", "expand"): "window",
}


def _functions(tree: ast.AST) -> dict[str, list[ast.AST]]:
    out: dict[str, list[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            out.setdefault(node.name, []).append(node)
    return out


def _calls(fn: ast.AST, name: str) -> int:
    return sum(
        1 for c in ast.walk(fn)
        if isinstance(c, ast.Call) and (
            (isinstance(c.func, ast.Name) and c.func.id == name)
            or (isinstance(c.func, ast.Attribute) and c.func.attr == name)
        )
    )  # fmt: skip


def test_external_call_sites_use_turn_budget() -> None:
    assert len(CALL_SITES) >= 8  # quy ước 3.9: danh sách quét không rỗng
    for (path, func), helper in CALL_SITES.items():
        fns = _functions(ast.parse((APP / path).read_text(encoding="utf-8"))).get(func)
        assert fns, f"{path}: không thấy hàm {func}"
        assert any(_calls(fn, helper) for fn in fns), f"{path}::{func} không gọi {helper} (hạn cả lượt 9.0)"


def test_ml_client_never_passes_raw_timeout_constant() -> None:
    """`timeout=` gửi tới ml-service luôn là biến đã cắt, không phải `TIMEOUT_S[...]` trần."""
    tree = ast.parse((APP / "ml/client.py").read_text(encoding="utf-8"))
    kws = [k for c in ast.walk(tree) if isinstance(c, ast.Call) for k in c.keywords if k.arg == "timeout"]
    assert kws
    for k in kws:
        assert not (isinstance(k.value, ast.Subscript) and ast.unparse(k.value).startswith("TIMEOUT_S")), ast.unparse(k)
