"""Lớp luật M5 (B12–B13). Bất biến [Chốt]: `evaluate` chỉ nhận `action` và `ctx` — không bao giờ đọc câu người dùng,
slot hay hội thoại (h22; import-linter `risk-no-user-text`; test AST `build_ctx` h21).

Luật đọc từ `config/policy.json` đang chạy (`settings.get_policy`, 3-Q29 — Phase 3 chưa có `policy_versions`). Intent của
hành động suy từ `config/action_metadata.yaml` (`settings.action_intents`, Q-3h-1 — `Action` không mang intent); không suy
được → không luật nào khớp (→ B14 → E5 ở Phase 3). DSL, "thiếu fact → sai", "chặt nhất thắng": `domain/policy.py`.
"""

from collections.abc import Mapping, Sequence

from app.domain.action import Action, param_ok
from app.domain.policy import FactView, Rule, rule_matches, strictest
from app.risk.models import RiskContext, RuleVerdict
from app.settings import action_intents, get_policy


def fact_view(action: Action, ctx: RiskContext) -> FactView:
    """Khung nhìn fact cho DSL — chỉ từ `Action` và `RiskContext` (không có nguồn nào chứa chữ người dùng). `action.params`: chỉ khoá
    trong danh sách trắng `PARAM_TYPES`, đúng kiểu và tập giá trị (T22a P3)."""
    return {
        "action": {
            "type": action.type, "target": action.target, "requested_for": action.requested_for,
            "scope": action.scope, "privilege_level": action.privilege_level, "reversible": action.reversible,
            "reversibility": action.reversibility, "data_sensitivity": action.data_sensitivity,
        },
        "action.facts": dict(action.facts),
        "action.params": {k: v for k, v in action.params.items() if param_ok(k, v)},  # T22a P3: sai kiểu/ngoài tập = thiếu
        "requester": ctx.requester.model_dump(
            include={"user_id", "role", "department", "employment_status", "tenure_days", "is_privileged_account"}
        ),
        "time": {"within_business_hours": ctx.within_business_hours},
        "ctx": {"target_is_other": ctx.target_is_other},
    }  # fmt: skip


def evaluate_rules(
    rules: Sequence[Rule], action: Action, ctx: RiskContext, *, intents: Mapping[str, str]
) -> RuleVerdict:
    """Thuần (test truyền luật riêng). Mọi luật khớp → chặt nhất thắng; `all_matched` theo thứ tự trong file."""
    view = fact_view(action, ctx)
    intent = intents.get(action.type)
    matched = [r for r in rules if rule_matches(r, intent=intent, action_type=action.type, view=view)]
    best = strictest(matched)
    if best is None:
        return RuleVerdict(matched=False, decision=None, rule_id=None, all_matched=[], description=None)
    return RuleVerdict(
        matched=True, decision=best.type, rule_id=best.id, all_matched=[r.id for r in matched],
        description=best.description,
    )  # fmt: skip


def evaluate(action: Action, ctx: RiskContext) -> RuleVerdict:
    return evaluate_rules(get_policy().rules, action, ctx, intents=action_intents())
