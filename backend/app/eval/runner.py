"""Harness G2 — chạy kịch bản M8 trên stack compose đang chạy (P8 §2, §5; plan G2). Chạy trên host, như gate2:

    EVAL_MODE=true EVAL_PASSWORD=… PYTHONPATH=backend uv run python -m app.eval.runner \
        --scenarios <dir> --strategy hybrid --split test --timeout-s <số giây> --out <dir ngoài repo>

Luồng: nạp kịch bản (lỗi → mã 2) → kiểm `--out` → chốt an toàn (`APP_ENV=dev`, URL 127.0.0.1) → cấu hình hiệu lực của container
backend (STRATEGY khớp cờ, `EVAL_MODE=true`, `LLM_CACHE_MODE=eval`, `APPROVAL_SLA_MINUTES_DEV` có đặt (G2-Q6), `APP_GIT_SHA` khớp
HEAD nếu có đặt; chỉ SO, không in giá trị) →
`/api/health` → `run_id` → làm nóng rerank (trong container) → từng kịch bản TUẦN TỰ với hạn `--timeout-s` → `predictions.jsonl`
(hợp đồng v1, đọc lại bằng `load_predictions` trước khi đổi tên) + `outcomes.jsonl` + `manifest.json`.

In: mặc định ĐÚNG 7 dòng tổng hợp (+ `ignored_fields=<n>` khi `--allow-extra-fields`) — không câu, id kịch bản, họ, gold, ticket_id,
route từng ca, detail, SQL, thông điệp exception. `--per-case`: thêm mỗi ca `<scenario_id> <kết cục> <giây>[ <tên lớp lỗi>]` và tên
file trong lỗi nạp. `--check-only`: chỉ nạp + tính sha, không gọi stack, không cần `EVAL_PASSWORD` (Tuấn Anh chạy trên dữ liệu thật).

Mã thoát: 0 xong · 1 có ca `timeout`/`error` (file vẫn ghi) · 2 tham số / kịch bản / chốt an toàn / preflight / log 4 sai khoá hoặc
strategy (KHÔNG ghi `predictions.jsonl`).

Không gọi `/api/policy` hay endpoint chính sách nào (Rev 27). `p_method` thuộc hằng chính sách → không đọc: lấy `--prob-method`
(mặc định `self_report`) và đếm bản ghi có `p_method` khác (`p_method_mismatch`). `policy_sha256` = `policy_sha256()` trong container
(chỉ băm, G2-Q11).
"""

import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, get_args

import httpx

from app.eval.actors import ScriptedUser, SimApprover
from app.eval.collect import AbortRun, MultiLeaf, RunMeta, collect
from app.eval.config import (
    ProbMethod,
    RunConfig,
    RunIdMismatch,
    StackStrategy,
    check_run_id,
    make_run_id,
)
from app.eval.dataset import (
    Dataset,
    DatasetError,
    Scenario,
    load_scenarios,
    load_seed_users,
)
from app.eval.predictions import PredictionRecord, Split, load_predictions
from app.eval.stack import (
    DEFAULT_URL,
    Api,
    Clock,
    Deadline,
    ScenarioTimeout,
    Shell,
    Sql,
    StackError,
    Unsafe,
    check_url,
    turns_state,
    wait_for,
    wait_turn_closed,
)

POLL_S = 0.5
DEFAULT_SEED = Path(__file__).resolve().parents[3] / "mock_services" / "seed.json"  # seed của mock: user_id → username
OUT_FILES = ("predictions.jsonl", "outcomes.jsonl", "manifest.json")
LATER = ("b2_tau", "b2_judge_model", "injection_clf_sha", "intent_clf_sha", "rate_limits")  # chừa cho 21/10
INFO_KEYS = ("app_env", "strategy", "eval_mode", "llm_cache_mode", "enable_proactive_diagnosis", "b2_classifier_mode",
             "approval_sla_minutes_dev", "llm_backend", "fast_model", "strong_model", "app_git_sha", "rag_rerank_k")  # fmt: skip
INFO_SCRIPT = (
    "import json\nfrom app.settings import get_settings, policy_sha256\ns = get_settings()\n"
    f"d = {{k: getattr(s, k) for k in {INFO_KEYS!r}}}\nd['policy_sha256'] = policy_sha256()\n"
    "print(json.dumps(d, default=str))\n"
)
ABORT_TEXT = {
    "strategy_mismatch": "detail.strategy ở điểm log 4 khác --strategy",
    "log4_missing_strategy": "điểm log 4 thiếu khoá strategy (container chạy EVAL_MODE=true chưa? G2-Q16)",
    "log4_missing_route": "điểm log 4 thiếu khoá route",
}

type Outcome = Literal["done", "timeout", "multi_leaf", "error"]
OUTCOMES: tuple[Outcome, ...] = ("done", "timeout", "multi_leaf", "error")


class Backend(Protocol):
    def app_env(self) -> str | None: ...
    def info(self) -> dict[str, Any]: ...
    def warmup(self, rounds: int) -> dict[str, Any]: ...
    def sql(self, query: str) -> Any: ...


class ComposeBackend:
    """Container backend + postgres của compose (qua `Shell`, không echo, không đọc `.env`)."""

    def __init__(self, shell: Shell) -> None:
        self.shell = shell

    def app_env(self) -> str | None:
        return self.shell.env("backend", ["APP_ENV"])["APP_ENV"]

    def _json_line(self, *args: str) -> dict[str, Any]:
        lines = self.shell.compose("exec", "-T", "backend", *args).strip().splitlines()
        try:
            data = json.loads(lines[-1]) if lines else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise StackError("container backend không trả một dòng JSON")
        return data

    def info(self) -> dict[str, Any]:
        return self._json_line("python", "-c", INFO_SCRIPT)

    def warmup(self, rounds: int) -> dict[str, Any]:
        return self._json_line("python", "-m", "app.eval.warmup", "--rounds", str(rounds))

    def sql(self, query: str) -> Any:
        return self.shell.sql(query)


@dataclass
class Deps:
    backend: Backend
    http: httpx.Client
    clock: Clock
    git_commit: str
    now: Callable[[], datetime]
    git_dirty: bool = False  # `git status --porcelain` có dòng (gồm file untracked) — chỉ cờ, không tên file


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=False).stdout


def real_deps(url: str) -> Deps:
    shell = Shell(shlex.split(os.environ.get("COMPOSE", "docker compose")))
    return Deps(backend=ComposeBackend(shell), http=httpx.Client(base_url=url, timeout=30), clock=Clock(),
                git_commit=_git("rev-parse", "HEAD").strip(), now=lambda: datetime.now(UTC),
                git_dirty=bool(_git("status", "--porcelain").strip()))  # fmt: skip


class Stop(Exception):
    """Dừng cả lượt, mã 2 — thông điệp là chữ cố định của runner (không dữ liệu)."""


class _ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # không in usage ra stderr rồi SystemExit — runner tự in, tự trả mã 2
        raise _ArgError(message)


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("phải là số nguyên > 0") from None
    if n <= 0:
        raise argparse.ArgumentTypeError("phải là số nguyên > 0")
    return n


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = _Parser(prog="python -m app.eval.runner", add_help=False)
    p.add_argument("--scenarios", type=Path, required=True)
    p.add_argument("--out", type=Path)
    p.add_argument("--strategy", choices=get_args(StackStrategy))  # TODO(G2-Q15): S3 = hybrid tắt chẩn đoán — chưa làm
    p.add_argument("--split", choices=get_args(Split))  # TODO(G2-Q3): lượt stack ghi "test"
    p.add_argument("--timeout-s", type=_positive_int)  # BẮT BUỘC khi chạy (không mặc định) — số Tuấn Anh gửi
    p.add_argument("--run-id")  # TODO(G2-Q4): chỉ để đối chiếu
    p.add_argument("--prob-method", choices=get_args(ProbMethod), default="self_report")
    p.add_argument("--per-case", action="store_true")
    p.add_argument("--warmup-rounds", type=_positive_int, default=3)
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--allow-extra-fields", action="store_true")
    p.add_argument("--check-only", action="store_true")
    p.add_argument("--seed", type=Path, default=DEFAULT_SEED)
    return p.parse_args(list(argv))


# ---- một kịch bản -----------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    scenario_id: str
    ticket_id: str | None
    outcome: Outcome
    error_type: str | None
    error_http: int | None  # mã HTTP khi lỗi là StackError của Api (góp ý G16) — chỉ vào outcomes.jsonl
    elapsed_s: float
    started_at: str
    record: PredictionRecord | None
    confirm_default: bool


@dataclass(frozen=True)
class _Ctx:
    api: Api
    sql: Sql
    clock: Clock
    password: str
    timeout_s: int
    meta: RunMeta
    now: Callable[[], datetime]
    usernames: Mapping[str, str]  # scenario_id → username (tra seed theo requester.user_id)


def run_case(s: Scenario, c: _Ctx) -> Case:
    started = c.now().isoformat()
    deadline = Deadline(c.clock, c.timeout_s)
    user = ScriptedUser(s)
    approver = SimApprover(c.api, c.sql, c.password)
    ticket_id: str | None = None
    outcome: Outcome = "done"
    error_type: str | None = None
    error_http: int | None = None
    try:
        h = c.api.login(c.usernames[s.id], c.password)
        ticket_id = tid = c.api.create(h, user.first_text)

        def closed() -> bool | None:
            return True if c.api.view(h, tid)["final_state"] is not None else None

        before = 0
        while True:
            wait_turn_closed(c.sql, tid, before, deadline, POLL_S)
            view = c.api.view(h, tid)
            if view["final_state"] is not None:
                break
            before, _ = turns_state(c.sql, tid)
            waiting = view["waiting_for"]
            if waiting == "clarify":
                answer = user.next_answer()
                if answer is None:  # hết câu: chờ tới hạn (không chờ 24 giờ) — P8 §5.2
                    wait_for(closed, deadline, POLL_S)
                    break
                c.api.message(h, tid, answer)
            elif waiting == "confirm":
                c.api.confirm(h, tid, user.next_confirm())
            elif waiting == "approval":
                if approver.act(tid, s.gold.approver_decision) == "ignored":  # worker bắn E6 khi hết SLA (TODO(G2-Q6))
                    wait_for(closed, deadline, POLL_S)
                    break
            elif waiting == "reply":
                outcome = "multi_leaf"
                break
            else:
                raise StackError("ticket chưa đóng mà không ở trạng thái chờ nào")
    except ScenarioTimeout:
        outcome = "timeout"
    except (StackError, httpx.HTTPError, KeyError, TypeError, ValueError) as e:
        outcome, error_type = "error", type(e).__name__
        error_http = e.http_status if isinstance(e, StackError) else None
    record = None
    if outcome != "multi_leaf" and ticket_id is not None:
        try:
            record = collect(c.sql, s, ticket_id, c.meta)
        except MultiLeaf:
            outcome = "multi_leaf"
        except (StackError, KeyError, TypeError, ValueError) as e:
            outcome, error_type = "error", error_type or type(e).__name__
            if error_http is None and isinstance(e, StackError):
                error_http = e.http_status
    return Case(scenario_id=s.id, ticket_id=ticket_id, outcome=outcome, error_type=error_type, error_http=error_http,
                elapsed_s=round(deadline.elapsed(), 1), started_at=started, record=record,
                confirm_default=user.confirm_default)  # fmt: skip


# ---- CLI --------------------------------------------------------------------------------------------------------------


def _load(args: argparse.Namespace, out: Callable[[str], None]) -> Dataset | None:
    try:
        users = load_seed_users(args.seed)
    except ValueError as e:  # chữ cố định của load_seed_users (có "seed", không giá trị)
        out(f"DỪNG: {e}")
        return None
    try:
        return load_scenarios(args.scenarios, users=users, allow_extra=args.allow_extra_fields)
    except DatasetError as e:
        out(f"scenarios: loaded={e.loaded} errors={len(e.issues)}")
        for line in e.render(show_name=args.per_case):
            out(line)
        return None
    except ValueError as e:  # thư mục không có / rỗng — chữ cố định của dataset.py
        out(f"DỪNG: {e}")
        return None


def _check_only(args: argparse.Namespace, out: Callable[[str], None]) -> int:
    ds = _load(args, out)
    if ds is None:
        return 2
    out(f"scenarios: loaded={len(ds.scenarios)} errors=0")
    if args.allow_extra_fields:
        out(f"ignored_fields={len(ds.ignored_fields)}")
    return 0


def _check_out(args: argparse.Namespace) -> Path:
    out_dir: Path = args.out.resolve()
    scen = args.scenarios.resolve()
    if out_dir == scen or scen in out_dir.parents:
        raise Stop("--out không được nằm trong thư mục kịch bản")
    if any((out_dir / f).exists() for f in OUT_FILES):
        raise Stop("--out đã có file kết quả của lượt trước — chọn thư mục khác")
    return out_dir


def _preflight(deps: Deps, args: argparse.Namespace, err: Callable[[str], None]) -> tuple[dict[str, Any], bool]:
    try:
        if deps.backend.app_env() != "dev":
            raise Stop("chốt an toàn: APP_ENV của container backend không phải dev")
        info = deps.backend.info()
    except (StackError, Unsafe):
        raise Stop("không đọc được cấu hình container backend (make up chưa?)") from None
    if info.get("strategy") != args.strategy:
        raise Stop("STRATEGY của container backend khác --strategy (sửa .env rồi make up lại)")
    if info.get("eval_mode") is not True:
        raise Stop("container backend không chạy EVAL_MODE=true")
    if info.get("llm_cache_mode") != "eval":
        raise Stop("LLM_CACHE_MODE của container backend không phải eval")
    sla = info.get("approval_sla_minutes_dev")
    if not isinstance(sla, int) or isinstance(sla, bool) or sla <= 0:  # G2-Q6 (Tuấn Anh 19/10): ca ignore phải ra E6 trước timeout
        raise Stop("container backend không đặt APPROVAL_SLA_MINUTES_DEV (.env cần APPROVAL_SLA_MINUTES_DEV=2, make up lại)")
    app_sha = info.get("app_git_sha") or ""
    if not app_sha:
        # backend/Dockerfile:32-33: `ARG GIT_SHA` → `ENV APP_GIT_SHA`; make up chỉ truyền khi cây sạch (bẩn → rỗng → Settings None)
        err("CẢNH BÁO: container không đặt APP_GIT_SHA (image dựng từ cây bẩn?) — không đối chiếu được commit "
            "(manifest commit_verified=false)")  # fmt: skip
        verified = False
    elif min(len(app_sha), len(deps.git_commit)) < 7 or not (app_sha.startswith(deps.git_commit)
                                                             or deps.git_commit.startswith(app_sha)):  # fmt: skip
        raise Stop("APP_GIT_SHA của container khác HEAD của repo (make up lại trên đúng nhánh)")
    else:
        verified = True
    try:
        health = Api(deps.http).health()
    except (StackError, httpx.HTTPError):
        raise Stop("không gọi được /api/health") from None
    if health.get("runtime") != "up":
        raise Stop("backend chưa sẵn sàng (/api/health runtime ≠ up)")
    if args.timeout_s < sla * 60 + 60:
        err("CẢNH BÁO: timeout_s nhỏ hơn SLA duyệt + 60 giây — ca ignore sẽ ra timeout thay vì E6 (G2-Q6)")
    return info, verified


def _login_check(deps: Deps, username: str, password: str) -> None:
    """Góp ý G16 (Duy Anh): thử đăng nhập MỘT lần bằng requester của kịch bản đầu (username tra seed) trước khi tạo ticket nào —
    sai EVAL_PASSWORD thì dừng ngay với lý do rõ, không để mọi ca ra StackError. Không in username / mật khẩu."""
    try:
        Api(deps.http).login(username, password)
    except StackError as e:
        if e.http_status == 401:
            raise Stop("EVAL_PASSWORD sai (đăng nhập 401)") from None
        raise Stop("thử đăng nhập lỗi (HTTP khác 401 — xem /api/health, log backend)") from None
    except httpx.HTTPError:
        raise Stop("thử đăng nhập lỗi (không kết nối được backend)") from None


def _write(out_dir: Path, records: list[PredictionRecord], cases: list[Case], manifest: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / "predictions.jsonl.tmp"
    tmp.write_text("".join(r.model_dump_json() + "\n" for r in records), encoding="utf-8")
    if records:
        try:
            load_predictions(tmp)  # tự kiểm hợp đồng v1 trước khi giao
        except ValueError:
            tmp.unlink()
            raise Stop("predictions không qua hợp đồng v1 (load_predictions)") from None
    tmp.replace(out_dir / "predictions.jsonl")
    (out_dir / "outcomes.jsonl").write_text("".join(json.dumps({
        "scenario_id": c.scenario_id, "ticket_id": c.ticket_id, "outcome": c.outcome, "error_type": c.error_type,
        "elapsed_s": c.elapsed_s, "run_started_at": c.started_at,
        "in_business_hours": None,  # TODO(G7): khung giờ `at` (G2-Q10)
        **({"error_http": c.error_http} if c.error_http is not None else {}),
    }, ensure_ascii=False) + "\n" for c in cases), encoding="utf-8")  # fmt: skip
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run(args: argparse.Namespace, env: Mapping[str, str], make_deps: Callable[[str], Deps], out: Callable[[str], None],
         err: Callable[[str], None]) -> int:  # fmt: skip
    missing = [f for f, v in (("--strategy", args.strategy), ("--split", args.split), ("--timeout-s", args.timeout_s),
                              ("--out", args.out)) if v is None]  # fmt: skip
    if missing:
        raise Stop(f"thiếu tham số {' '.join(missing)}")
    password = env.get("EVAL_PASSWORD") or ""
    if not password.strip():
        raise Stop("thiếu biến môi trường EVAL_PASSWORD")
    ds = _load(args, out)
    if ds is None:
        return 2
    out_dir = _check_out(args)
    try:
        url = check_url(args.url)
    except Unsafe:
        raise Stop("chốt an toàn: --url chỉ nhận http://127.0.0.1:<cổng>") from None
    deps = make_deps(url)
    started_at, t0 = deps.now(), deps.clock.monotonic()
    info, verified = _preflight(deps, args, err)
    _login_check(deps, ds.usernames[ds.scenarios[0].id], password)
    config = RunConfig(
        strategy=args.strategy, split=args.split, timeout_s=args.timeout_s, prob_method=args.prob_method,
        llm_roles={k: str(info.get(k) or "") for k in ("llm_backend", "fast_model", "strong_model")},
        enable_proactive_diagnosis=bool(info.get("enable_proactive_diagnosis")),
    )  # fmt: skip
    run_id = make_run_id(config, ds.sha256, deps.git_commit)
    try:
        check_run_id(args.run_id, run_id)
    except RunIdMismatch:
        raise Stop("--run-id khác run_id tính từ cấu hình + dữ liệu + commit") from None
    try:
        warm = deps.backend.warmup(args.warmup_rounds)
    except (StackError, Unsafe):
        raise Stop("làm nóng rerank lỗi (image backend chưa có app.eval.warmup? make up lại)") from None
    ctx = _Ctx(api=Api(deps.http), sql=deps.backend.sql, clock=deps.clock, password=password, timeout_s=args.timeout_s,
               meta=RunMeta(run_id=run_id, strategy=config.strategy, split=config.split), now=deps.now,
               usernames=ds.usernames)  # fmt: skip
    cases: list[Case] = []
    for s in ds.scenarios:
        try:
            case = run_case(s, ctx)
        except AbortRun as e:
            raise Stop(ABORT_TEXT[e.reason]) from None
        cases.append(case)
        if args.per_case:
            out(f"{case.scenario_id} {case.outcome} {case.elapsed_s:.1f}" + (f" {case.error_type}" if case.error_type else ""))
    records = [c.record for c in cases if c.record is not None]
    tally = Counter(c.outcome for c in cases)
    counts: dict[str, int] = {
        "loaded": len(ds.scenarios), **{o: tally[o] for o in OUTCOMES}, "written": len(records),
        "route_none": sum(r.route is None for r in records),
        "calibrated_prob_nonnull": sum(r.calibrated_prob is not None for r in records),
        "unlabeled": sum(r.expected_route is None for r in records),
        "confirm_default": sum(c.confirm_default for c in cases),
        "p_method_mismatch": sum(r.p_method is not None and r.p_method != args.prob_method for r in records),
    }  # fmt: skip
    if counts["p_method_mismatch"]:
        err("CẢNH BÁO: có bản ghi p_method khác --prob-method (xem manifest counts.p_method_mismatch)")
    elapsed = deps.clock.monotonic() - t0
    manifest: dict[str, Any] = {
        "run_id": run_id, "config": config.model_dump(mode="json"), "git_commit": deps.git_commit, "git_dirty": deps.git_dirty,
        "app_git_sha": info.get("app_git_sha"), "commit_verified": verified, "dataset_sha256": ds.sha256,
        "dataset_file_count": len(ds.files), "strategy": config.strategy, "split": config.split, "timeout_s": config.timeout_s,
        "enable_proactive_diagnosis": config.enable_proactive_diagnosis, "llm_cache_mode": info.get("llm_cache_mode"),
        "clf_mode": info.get("b2_classifier_mode"), "policy_sha256": info.get("policy_sha256"),
        "llm_backend": info.get("llm_backend"), "approval_sla_minutes_dev": info.get("approval_sla_minutes_dev"),
        "started_at": started_at.isoformat(), "finished_at": deps.now().isoformat(),
        "host": platform.node(), "warmup": warm, "counts": counts,
        "ignored_fields": {"allowed": args.allow_extra_fields, "count": len(ds.ignored_fields),
                           "paths": sorted(set(ds.ignored_fields))},
        **dict.fromkeys(LATER), "unavailable": list(LATER),
    }  # fmt: skip
    _write(out_dir, records, cases, manifest)
    out(f"eval run {run_id} strategy={config.strategy} split={config.split} timeout_s={config.timeout_s}")
    out(f"scenarios: loaded={counts['loaded']}")
    out(f"warmup: rounds={warm.get('rounds')} first_ms={warm.get('first_ms')} last_ms={warm.get('last_ms')}")
    out(f"outcomes: done={counts['done']} timeout={counts['timeout']} multi_leaf={counts['multi_leaf']} error={counts['error']}")
    out(f"records: written={counts['written']} route_none={counts['route_none']} "
        f"calibrated_prob_nonnull={counts['calibrated_prob_nonnull']} unlabeled={counts['unlabeled']}")  # fmt: skip
    out(f"elapsed_s={elapsed:.1f}")
    out("files: " + " ".join(OUT_FILES))
    if args.allow_extra_fields:
        out(f"ignored_fields={len(ds.ignored_fields)}")
    return 1 if counts["timeout"] or counts["error"] else 0


def _stderr(line: str) -> None:
    print(line, file=sys.stderr)


def main(argv: Sequence[str], *, env: Mapping[str, str] = os.environ, make_deps: Callable[[str], Deps] = real_deps,
         out: Callable[[str], None] = print, err: Callable[[str], None] = _stderr) -> int:  # fmt: skip
    try:
        args = parse_args(argv)
    except _ArgError as e:
        out(f"DỪNG: tham số sai — {e}")
        return 2
    if args.check_only:
        return _check_only(args, out)
    try:
        return _run(args, env, make_deps, out, err)
    except Stop as e:
        out(f"DỪNG: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
