"""Đếm "ca không luật nào khớp → lớp LLM" trên kịch bản (phase5 mục 4.6, P9, Q-5-5) — chỉ đọc, không mạng, không stack.

  uv run python scripts/rule_coverage.py eval/scenarios [--seed mock_services/seed.json] [--csv out.csv]

Mỗi kịch bản (P8 §4.1 + `gold.action {type, target, requested_for?, params}` + `gold.facts`): dựng `RequesterContext` từ seed (như B1
dựng từ AD, `captured_at = at`), `Action` (metadata theo `type`; `params` kiểm `PARAM_TYPES`; `facts` qua `check_facts`), ctx qua
`build_ctx` (cờ B6 = False, P5), rồi `evaluate_rules` trên `config/policy.json` → allow | approval_required | deny | none (→ LLM).
Fact suy được từ seed mà kịch bản ghi khác → `CẢNH BÁO` (không lỗi). Lỗi kịch bản (sai key/kiểu/tập, người gửi không có trong seed…)
→ in id, các kịch bản khác vẫn chạy, mã thoát 1; chỉ cảnh báo → 0.

PLAN-T22a TQ-9: thư mục → quét đệ quy `*.yaml`/`*.yml`, BỎ thư mục con tên bắt đầu `_` (vd `eval/scenarios/_mau`) trừ khi chính thư
mục đó được truyền. Không gọi `get_settings()` (không chạm `.env`) — cấu hình nạp theo đường dẫn từ `config/`. Không import `app.eval`.
Không ghi file nào ngoài `--csv`. Bảng tổng KHÔNG in `expected_route` (người gán nhãn có thể chạy script — P8 §4.1); nhãn chỉ ra CSV.
"""

import argparse
import csv
import json
import sys
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
if str(BACKEND) not in sys.path:  # lệnh đúng chữ spec 4.6 (`uv run python scripts/rule_coverage.py …`) không cần PYTHONPATH
    sys.path.insert(0, str(BACKEND))

from app.core.errors import DomainError
from app.domain.action import PARAM_TYPES, Action, param_ok
from app.domain.context import RequesterContext
from app.domain.facts import FactKeyViolation, check_facts
from app.risk.context import build_ctx
from app.risk.policy_engine import evaluate_rules
from app.settings import (
    intents_of_actions,
    load_action_metadata,
    load_policy,
)

CONFIG = REPO / "config"
DEFAULT_SEED = REPO / "mock_services" / "seed.json"
DECISIONS = ("allow", "approval_required", "deny", "none")
COLUMNS = ("số kịch bản", *DECISIONS[:3], "none (→ LLM)", "lỗi")
CSV_COLUMNS = ("id", "family", "rule_decision", "matched_rule_id", "all_matched", "expected_route")


class ScenarioError(Exception):
    """Lỗi kịch bản — in id + lý do, không dừng cả lượt."""


@dataclass
class Result:
    id: str
    family: str
    decision: str  # allow | approval_required | deny | none | error | no_action
    rule_id: str = ""
    all_matched: list[str] = field(default_factory=list)
    expected_route: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)


# ---- nạp kịch bản ------------------------------------------------------------------------------------------------------


def scenario_files(paths: list[Path]) -> Iterator[Path]:
    """File truyền thẳng → nhận; thư mục → đệ quy, bỏ thư mục con tên bắt đầu `_` (TQ-9) — thư mục truyền thẳng thì nhận dù tên `_…`."""
    for root in paths:
        if root.is_file():
            yield root
            continue
        for path in sorted(root.rglob("*")):
            skipped = any(part.startswith("_") for part in path.relative_to(root).parts[:-1])
            if path.suffix in {".yaml", ".yml"} and path.is_file() and not skipped:
                yield path


def _fmt(value: object) -> str:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, bool) or value is None else str(value)


def _at(raw: object) -> datetime:
    at = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
    if at.tzinfo is None:
        raise ScenarioError("`at` thiếu múi giờ")
    return at


# ---- seed (JSON thô — không import mock: cùng tên gói `app`) ------------------------------------------------------------


class Seed:
    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.users: dict[str, dict[str, Any]] = {u["user_id"]: u for u in raw["users"]}
        self.resources: dict[str, dict[str, Any]] = {r["path"]: r for r in raw["resources"]}
        self.catalog: dict[str, dict[str, Any]] = {c["name"]: c for c in raw["catalog"]}
        self.devices: dict[str, dict[str, Any]] = {d["device_id"]: d for d in raw["devices"]}

    def requester(self, user_id: str, at: datetime) -> RequesterContext:
        """Như B1 (`RequesterContext.from_ad`), mốc thời gian tương đối của seed quy về `at`."""
        u = self.users.get(user_id)
        if u is None:
            raise ScenarioError(f"người gửi {user_id!r} không có trong seed")
        ad = SimpleNamespace(
            user_id=u["user_id"], department=u["department"], groups=u["groups"], manager_id=u["manager_id"],
            employment_status=u["employment_status"], is_privileged_account=u.get("is_privileged_account", False),
            hired_at=at.date() - timedelta(days=int(u["hired_days_ago"])),
        )  # fmt: skip
        try:
            return RequesterContext.from_ad(ad, at)
        except DomainError as e:
            raise ScenarioError(f"người gửi {user_id!r}: {e}") from e

    def expected_facts(self, action: Action, requester_id: str) -> dict[str, object]:
        """Fact suy TRỰC TIẾP được từ seed (4.6 bước 4). Không suy được (người/thư mục/máy không có) → không đối chiếu fact đó."""
        out: dict[str, object] = {}
        kind, _, ref = action.target.partition(":")
        rf = self.users.get(action.requested_for)
        if rf is not None:
            account = rf["accounts"].get(str(action.params.get("account_type", "ad")))
            if account is not None:
                out["target_account_privilege"] = account.get("privilege", "standard_user")  # mặc định SeedAccount
            out["target_is_service_account"] = rf.get("is_service_account")
            out["target_user_status"] = rf["employment_status"]
            out["target_disable_reason"] = rf.get("disable_reason")
        if kind == "folder" and (res := self.resources.get(ref.strip().strip("/"))) is not None:
            out["resource_sensitivity"] = res["sensitivity"]
            if rf is not None:
                out["same_department"] = res["owner_department"] == rf["department"]
        if "software_name" in action.params:
            name = "-".join(str(action.params["software_name"]).strip().lower().split())  # như mock `software.normalize`
            entry = self.catalog.get(name)
            out["in_catalog"] = entry is not None
            if entry is not None:
                out["license_paid"] = entry["license_type"] == "paid"
                out["requires_local_admin"] = entry.get("requires_local_admin")
        if kind == "device":
            device = self.devices.get(ref)  # không có → như tool (404 → false)
            out["device_registered"] = bool(device and device["registered"])
            out["device_owner_is_requester"] = bool(device and device["owner_id"] == requester_id)
        return out


# ---- một kịch bản ------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Config:
    rules: Any
    hours: Any
    metadata: Mapping[str, Mapping[str, Any]]
    intents: Mapping[str, str]


def _action(gold: Mapping[str, Any], requester: RequesterContext, cfg: Config) -> Action:
    spec = gold["action"]
    if not isinstance(spec, dict):
        raise ScenarioError("gold.action phải là mapping")
    action_type = spec.get("type")
    intent = cfg.intents.get(str(action_type))
    if intent is None:
        raise ScenarioError(f"gold.action.type {action_type!r} không có trong action_metadata.yaml")
    target, requested_for = spec.get("target"), spec.get("requested_for") or requester.user_id  # P4: bỏ trống = người gửi
    if not isinstance(target, str) or not isinstance(requested_for, str):
        raise ScenarioError("gold.action.target / requested_for phải là chuỗi")
    params = spec.get("params") or {}
    if not isinstance(params, dict):
        raise ScenarioError("gold.action.params phải là mapping")
    for key, value in params.items():
        if type(value) not in (str, int, bool):
            raise ScenarioError(f"params.{key}: kiểu {type(value).__name__} (cần str/int/bool)")
        if key in PARAM_TYPES and not param_ok(key, value):
            raise ScenarioError(f"params.{key}={_fmt(value)} sai kiểu hoặc ngoài tập (PARAM_TYPES)")
    facts = gold.get("facts") or {}
    if not isinstance(facts, dict):
        raise ScenarioError("gold.facts phải là mapping")
    try:
        check_facts(facts)
    except FactKeyViolation as e:
        raise ScenarioError(str(e)) from e
    meta = cfg.metadata[intent][str(action_type)]
    return Action(
        type=str(action_type), target=target, requested_for=requested_for, scope=meta.scope,
        privilege_level=meta.privilege_level, reversible=meta.reversible, reversibility=meta.reversibility,
        data_sensitivity=meta.data_sensitivity, params=dict(params), facts=dict(facts),
    )  # fmt: skip


def evaluate_scenario(path: Path, seed: Seed, cfg: Config) -> Result:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as e:
        return Result(id=path.name, family="?", decision="error", error=f"không đọc được YAML ({type(e).__name__})")
    if not isinstance(data, dict):
        return Result(id=path.name, family="?", decision="error", error="kịch bản không phải mapping")
    sid, family = str(data.get("id") or path.name), str(data.get("family") or "?")
    raw_gold = data.get("gold")
    gold: dict[str, Any] = raw_gold if isinstance(raw_gold, dict) else {}
    result = Result(id=sid, family=family, decision="error", expected_route=str(gold.get("expected_route") or ""))
    try:
        if not data.get("id") or not data.get("family"):
            raise ScenarioError("thiếu id hoặc family")
        if gold.get("need_type") == "info" or "action" not in gold:
            result.decision = "no_action"
            return result
        req = data.get("requester")
        if not isinstance(req, dict) or not req.get("user_id") or "at" not in data:
            raise ScenarioError("thiếu requester.user_id hoặc at")
        at = _at(data["at"])
        requester = seed.requester(str(req["user_id"]), at)
        action = _action(gold, requester, cfg)
        for fact, want in seed.expected_facts(action, requester.user_id).items():
            if fact in action.facts and action.facts[fact] != want:
                result.warnings.append(f"CẢNH BÁO {sid}: {fact} kịch bản={_fmt(action.facts[fact])} seed={_fmt(want)}")
        state = {"intended_action": action.model_dump(), "requester_context": requester.model_dump(),
                 "ctx_flags": {"target_is_other": False}}  # fmt: skip  # cờ B6 = False (4.6 bước 5)
        verdict = evaluate_rules(cfg.rules, action, build_ctx(state, at, cfg.hours), intents=cfg.intents)
    except (ScenarioError, ValueError, KeyError, TypeError) as e:  # ValidationError là ValueError
        result.error = str(e) if isinstance(e, ScenarioError) else f"{type(e).__name__}: dữ liệu kịch bản không hợp lệ"
        return result
    result.decision = verdict.decision or "none"
    result.rule_id = verdict.rule_id or ""
    result.all_matched = list(verdict.all_matched)
    return result


# ---- in ----------------------------------------------------------------------------------------------------------------


def print_report(results: list[Result]) -> None:
    by_family: dict[str, Counter[str]] = {}
    for r in results:
        if r.decision != "no_action":
            by_family.setdefault(r.family, Counter())[r.decision] += 1
    print("| họ | " + " | ".join(COLUMNS) + " |")
    print("|---" * (len(COLUMNS) + 1) + "|")
    total: Counter[str] = Counter()
    for family in sorted(by_family):
        counts = by_family[family]
        total.update(counts)
        cells = [sum(counts.values()), *(counts[d] for d in DECISIONS), counts["error"]]
        print(f"| {family} | " + " | ".join(str(c) for c in cells) + " |")
    cells = [sum(total.values()), *(total[d] for d in DECISIONS), total["error"]]
    print("| Tổng | " + " | ".join(str(c) for c in cells) + " |")
    skipped = [r.id for r in results if r.decision == "no_action"]
    if skipped:
        print(f"\nkhông có hành động (bỏ qua): {len(skipped)}")
    errors = [r for r in results if r.decision == "error"]
    if errors:
        print(f"\nLỗi kịch bản ({len(errors)}):")
        for r in errors:
            print(f"  LỖI {r.id}: {r.error}")
    warnings = [w for r in results for w in r.warnings]
    if warnings:
        print(f"\nCảnh báo đối chiếu seed ({len(warnings)}):")
        for w in warnings:
            print(f"  {w}")


def write_csv(path: Path, results: list[Result]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(CSV_COLUMNS)
        for r in results:
            writer.writerow([r.id, r.family, r.decision, r.rule_id, " ".join(r.all_matched), r.expected_route])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Đếm ca không luật nào khớp (→ lớp LLM) trên kịch bản — phase5 4.6")
    parser.add_argument("paths", nargs="+", type=Path, help="thư mục hoặc file kịch bản YAML")
    parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    parser.add_argument("--csv", type=Path, default=None)
    args = parser.parse_args(argv)
    missing = [str(p) for p in args.paths if not p.exists()]
    if missing:
        print(f"không thấy đường dẫn: {missing}")
        return 1
    policy = load_policy(CONFIG / "policy.json")
    metadata = load_action_metadata(CONFIG / "action_metadata.yaml")
    cfg = Config(rules=policy.rules, hours=policy.business_hours, metadata=metadata.root,
                 intents=intents_of_actions(metadata))  # fmt: skip
    seed = Seed(args.seed)
    results = [evaluate_scenario(path, seed, cfg) for path in scenario_files(args.paths)]
    if not results:
        print("không có kịch bản nào")
        return 1
    print_report(results)
    if args.csv is not None:
        write_csv(args.csv, results)
    return 1 if any(r.decision == "error" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
