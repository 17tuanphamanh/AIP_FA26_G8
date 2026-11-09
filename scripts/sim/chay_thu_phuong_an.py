"""Chạy dữ liệu thử 3 cách xử lý M5 (P6 gói tuần 8, D-67) trên stack DEV — sinh ticket `source='sim'` cho `GET /api/dashboard/strategies`.

  APP_ENV=dev uv run python scripts/sim/chay_thu_phuong_an.py [--tagged] [--url http://127.0.0.1:8000] [--no-mock-reset] [--song-song]

Lần lượt `PUT /api/admin/strategy` rule_only → hybrid → hybrid_guarded (reason "chạy dữ liệu thử"); mỗi cách gửi CÙNG 8 yêu cầu bằng
tài khoản nhân viên kèm header `X-Sim-Run` (backend chỉ nhận header khi APP_ENV ∈ {dev, test}); L1 duyệt/từ chối phiếu chờ duyệt theo
danh sách cố định; nhân viên xác nhận "Đã ổn"/"Chưa ổn" theo danh sách cố định.

- Từ chối chạy khi APP_ENV ∉ {dev, test} hoặc URL không phải localhost (trước MỌI lời gọi HTTP). Sau khi đăng nhập quản lý, đọc
  `GET /api/admin/strategy`: server đang EVAL_MODE → dừng (mã 3) TRƯỚC mọi PUT/POST, không đổi gì.
- Khôi phục: lúc bắt đầu lưu chiến lược hiện hành (`ban_dau`); `finally` (kể cả lỗi giữa chừng) đọc lại — khác `ban_dau` thì PUT
  `ban_dau` (reason "khôi phục sau chạy thử dữ liệu thử"), đã bằng thì KHÔNG PUT. Khôi phục lỗi → cảnh báo stderr + mã ≠ 0.
- `source = 'sim'` của ticket script tạo KHÔNG đọc được qua API (TicketView không có `source`) — chỉ kiểm được ở PG.
- 8 câu lấy từ fixture gate sẵn có: `backend/tests/stack/gate3.py` (TC04, TC05 — câu hỏi KB), `gate5.py` (TC01, TC03 — luật cho tự làm;
  TC07, TC17 — cần duyệt) + 2 câu TC37 của `backend/tests/unit/test_chain_m5.py` (không luật nào khớp, preset dev-only
  `config/scripted/sim_khongluat.yaml`). `--tagged` thêm thẻ `[fake:<preset>]` cuối câu — BẮT BUỘC khi stack chạy LLM_BACKEND=scripted.
- Mật khẩu: `SIM_PASSWORD`, không đặt thì mật khẩu demo công khai của seed mock (`backend/tests/fakes/demo.py`). Manager bắt buộc MFA:
  OTP tính từ `SIM_MANAGER_TOTP_SECRET` (không có giá trị mặc định); thiếu biến → hỏi OTP tương tác. Đăng nhập lại TRƯỚC MỖI PUT
  (PUT cần đăng nhập ≤ REAUTH_MINUTES).
- Reset mock giữa 3 vòng (như gate: `docker compose exec -T mock python -m app.seed reset`) để ca "cài Zoom"/"đặt lại mật khẩu" lặp lại
  được; `--no-mock-reset` để bỏ.
- Mặc định TUẦN TỰ (`--tuan-tu`): gửi từng ticket, chờ tới trạng thái dừng (kết thúc / chờ duyệt / chờ hỏi lại / chờ xác nhận, tối đa
  SETTLE_S giây) rồi mới gửi ticket kế — gửi 8 ticket cùng lúc làm ml-service quá tải (E2 rag_system_error). `--song-song` giữ đường
  cũ (gửi hết 8 rồi mới chờ) — chỉ khi máy đủ mạnh. Backend phải chạy `make up RATE=loose`.
- Cuối lượt (SAU khi khôi phục chiến lược, stderr): cách nào có 0 ticket tới chờ duyệt → mã 4; cách nào có E2 > 20% số lá → mã 5
  (E2 ưu tiên khi có cả hai). Lỗi chung (mã 1) vẫn là mã 1.
- CHỈ in số ticket theo từng cách + mã HTTP khi lỗi; KHÔNG in câu chữ, token, mật khẩu, OTP. Không đọc `.env`.
"""

import argparse
import getpass
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

REPO = Path(__file__).resolve().parents[2]
ALLOWED_ENVS = ("dev", "test")
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
DEFAULT_URL = "http://127.0.0.1:8000"
ORDER = ("rule_only", "hybrid", "hybrid_guarded")
REASON = "chạy dữ liệu thử"
RESTORE_REASON = "khôi phục sau chạy thử dữ liệu thử"
EVAL_REFUSED = 3  # mã thoát: server đang EVAL_MODE
NO_APPROVAL = 4  # mã thoát: có cách mà 0 ticket tới bước duyệt
ML_ERROR = 5  # mã thoát: có cách mà E2 > E2_MAX_RATIO số lá (ml-service/RAG lỗi)
E2_MAX_RATIO = 0.2
SIM_HEADER = "X-Sim-Run"
MANAGER, EMPLOYEE, L1 = "quan.tm", "an.nv", "ha.lt"  # it_mgr01 (MFA), nv001, l1_01 = người duyệt chính mọi intent (approvers.yaml)
TOTP_ENV, PASSWORD_ENV = "SIM_MANAGER_TOTP_SECRET", "SIM_PASSWORD"
MOCK_RESET = ("docker", "compose", "exec", "-T", "mock", "python", "-m", "app.seed", "reset")
SETTLE_S, POLL_S = 120.0, 1.0
WAITS = frozenset({"approval", "confirm", "clarify", "reply"})


@dataclass(frozen=True)
class Req:
    group: str  # kb | allow | approval | no_rule
    preset: str
    text: str


# Thứ tự cố định (câu có "mật khẩu" kết thúc bằng dấu chấm — gate5 Q-T24-10: luật bí mật không nuốt thẻ preset).
REQUESTS: tuple[Req, ...] = (
    Req("kb", "tc04", "VPN công ty dùng cổng nào?"),  # gate3 TC04
    Req("kb", "tc05", "VPN báo lỗi 809, hướng dẫn mình khắc phục với"),  # gate3 TC05
    Req("allow", "tc01", "đặt lại mật khẩu tài khoản AD."),  # gate5 TC01 — R01
    Req("allow", "tc03", "cài Zoom"),  # gate5 TC03 — R11
    Req("approval", "tc07", "đặt lại mật khẩu AD cho svc_backup."),  # gate5 TC07 — R03
    Req("approval", "tc17", "cài photoshop"),  # gate5 TC17 — R13 (Q5: thay utorrent, nay bị cấm)
    Req("no_rule", "sim_khongluat", "Đặt lại mật khẩu tài khoản AD cho nv005 giúp mình."),  # TC37 (test_chain_m5)
    Req("no_rule", "sim_khongluat", "Bạn nv005 cần đặt lại mật khẩu AD, làm giúp mình."),  # TC37 (test_chain_m5)
)
# L1 quyết theo danh sách cố định (preset → quyết định); phiếu khác để nguyên
DECISIONS: Mapping[str, dict[str, Any]] = {
    "tc07": {"decision": "approved"},
    "tc17": {"decision": "rejected", "note": "Phần mềm ngoài danh mục chưa duyệt trong đợt chạy thử"},
}
# Nhân viên xác nhận theo danh sách cố định (thứ tự trong REQUESTS → Đã ổn / Chưa ổn); ticket khác để nguyên
CONFIRMS: Mapping[int, bool] = {0: True, 2: True, 3: False}  # tc04 Đã ổn, tc01 Đã ổn, tc03 Chưa ổn
UNRESOLVED_NOTE = "vẫn chưa dùng được"


class SimError(RuntimeError):
    """Lỗi có nhãn bước + mã HTTP — không mang thân phản hồi (có thể chứa chữ người dùng)."""


def refuse(env: Mapping[str, str], url: str) -> str | None:
    """Lý do từ chối chạy (None = được chạy)."""
    app_env = env.get("APP_ENV")
    if app_env not in ALLOWED_ENVS:
        return f"APP_ENV phải thuộc {list(ALLOWED_ENVS)} (đang là {app_env!r}) — script chỉ chạy trên stack dev/test"
    host = urlparse(url).hostname
    if host not in LOCAL_HOSTS:
        return "URL phải là localhost (127.0.0.1 / localhost) — script không chạy trên máy khác"
    return None


def password(env: Mapping[str, str]) -> str:
    if env.get(PASSWORD_ENV):
        return env[PASSWORD_ENV]
    sys.path.insert(0, str(REPO / "backend"))
    # mật khẩu demo công khai của seed mock (không hard-code ở đây)
    from tests.fakes.demo import DEMO_PASSWORD

    return DEMO_PASSWORD


class Sim:
    def __init__(self, client: httpx.Client, env: Mapping[str, str], *, tagged: bool, prompt: Callable[[str], str],
                 sleep: Callable[[float], None], run: Callable[..., Any], mock_reset: bool, run_id: str,
                 sequential: bool = True) -> None:  # fmt: skip
        self.client, self.env, self.tagged, self.prompt, self.sleep = client, env, tagged, prompt, sleep
        self.run, self.mock_reset, self.run_id, self.sequential = run, mock_reset, run_id, sequential
        self.stats: dict[str, tuple[int, int, int]] = {}  # cách → (số lá, số tới chờ duyệt, số E2) — chỉ vòng chạy xong
        self.pw = password(env)

    # ---- HTTP --------------------------------------------------------------------------------------------------------
    def _call(self, step: str, method: str, path: str, ok: Sequence[int], **kw: Any) -> httpx.Response:
        r = self.client.request(method, path, **kw)
        if r.status_code not in ok:
            raise SimError(f"{step}: HTTP {r.status_code}")
        return r

    def _otp(self) -> str:
        secret = self.env.get(TOTP_ENV)
        if secret:
            import pyotp

            return str(pyotp.TOTP(secret).now())
        return self.prompt("OTP của tài khoản quản lý (6 số): ").strip()

    def login(self, username: str, *, manager: bool = False) -> dict[str, str]:
        body: dict[str, Any] = {"username": username, "password": self.pw}
        if manager:
            body["otp"] = self._otp()
        token = self._call(f"đăng nhập {username}", "POST", "/api/auth/login", (200,), json=body).json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    def current(self) -> dict[str, Any]:
        """`GET /api/admin/strategy` bằng phiên quản lý mới: `{strategy, eval_mode, …}`."""
        headers = self.login(MANAGER, manager=True)
        return dict(self._call("đọc cách xử lý", "GET", "/api/admin/strategy", (200,), headers=headers).json())

    def set_strategy(self, strategy: str, reason: str = REASON) -> None:
        """Đăng nhập lại manager rồi PUT (PUT cần đăng nhập gần đây). 409 `same_as_current` = đã đúng chiến lược → coi là xong."""
        headers = self.login(MANAGER, manager=True)
        self._call(f"đổi cách xử lý → {strategy}", "PUT", "/api/admin/strategy", (200, 409), headers=headers,
                   json={"strategy": strategy, "reason": reason})  # fmt: skip

    def view(self, ticket: str, headers: dict[str, str]) -> dict[str, Any]:
        return dict(self._call("xem ticket", "GET", f"/api/tickets/{ticket}", (200,), headers=headers).json())

    def settle(self, ticket: str, headers: dict[str, str]) -> dict[str, Any]:
        """Chờ tới khi ticket dừng ở một chỗ chờ người hoặc đã kết thúc (tối đa SETTLE_S giây)."""
        deadline = time.monotonic() + SETTLE_S
        while True:
            v = self.view(ticket, headers)
            if v.get("final_state") is not None or v.get("waiting_for") in WAITS or time.monotonic() >= deadline:
                return v
            self.sleep(POLL_S)

    # ---- một vòng ----------------------------------------------------------------------------------------------------
    def round(self, strategy: str) -> int:
        self.set_strategy(strategy)
        if self.mock_reset:
            self.run(list(MOCK_RESET), cwd=REPO, check=True, capture_output=True)
        emp = self.login(EMPLOYEE)
        sim = {**emp, SIM_HEADER: self.run_id}
        tickets: list[str] = []
        views: list[dict[str, Any]] = []
        for req in REQUESTS:
            text = f"{req.text} [fake:{req.preset}]" if self.tagged else req.text
            r = self._call("tạo ticket", "POST", "/api/tickets", (202,), headers=sim, json={"text": text})
            tickets.append(str(r.json()["ticket_id"]))
            if self.sequential:  # ticket kế chỉ được gửi sau khi ticket này dừng
                views.append(self.settle(tickets[-1], emp))
        if not self.sequential:
            views = [self.settle(t, emp) for t in tickets]
        self.stats[strategy] = (
            len(tickets),
            sum(1 for v in views if v.get("waiting_for") == "approval"),
            sum(1 for v in views if v.get("exit_code") == "E2"),
        )
        l1 = self.login(L1)
        pending = self._call("hộp duyệt L1", "GET", "/api/approvals", (200,), headers=l1,
                             params={"mine": "1", "status": "pending"}).json()["items"]  # fmt: skip
        by_ticket = {str(i["ticket_id"]): str(i["approval_id"]) for i in pending}
        for req, ticket, v in zip(REQUESTS, tickets, views, strict=True):
            decision = DECISIONS.get(req.preset)
            if decision is None or v.get("waiting_for") != "approval" or ticket not in by_ticket:
                continue
            aid = by_ticket[ticket]
            self._call("xem phiếu", "GET", f"/api/approvals/{aid}", (200,), headers=l1)
            self._call("quyết định phiếu", "POST", f"/api/approvals/{aid}/decision", (202,), headers=l1, json=decision)
        for i, ok in CONFIRMS.items():
            v = self.settle(tickets[i], emp)
            if v.get("waiting_for") != "confirm":
                continue
            body: dict[str, Any] = {"confirmed": ok} if ok else {"confirmed": False, "note": UNRESOLVED_NOTE}
            self._call("xác nhận", "POST", f"/api/tickets/{tickets[i]}/confirm", (202,), headers=sim, json=body)
        return len(tickets)


def run_all(sim: Sim, out: Callable[[str], None], err: Callable[[str], None]) -> int:
    counts: dict[str, int] = {}
    code = 0
    try:
        start = sim.current()  # trước MỌI PUT/POST
    except (SimError, httpx.HTTPError) as exc:
        err(f"DỪNG: không đọc được cách xử lý hiện hành ({exc if isinstance(exc, SimError) else type(exc).__name__})")
        return 1
    if start.get("eval_mode") is not False:
        err("DỪNG: server đang EVAL_MODE — không chạy dữ liệu thử, không đổi gì")
        return EVAL_REFUSED
    ban_dau = str(start["strategy"])
    try:
        for strategy in ORDER:
            counts[strategy] = sim.round(strategy)
            out(f"{strategy}: {counts[strategy]} ticket")
    except (SimError, httpx.HTTPError, subprocess.CalledProcessError, OSError) as exc:
        err(f"DỪNG giữa chừng: {exc if isinstance(exc, SimError) else type(exc).__name__}")
        code = 1
    finally:
        try:
            if sim.current()["strategy"] != ban_dau:
                sim.set_strategy(ban_dau, RESTORE_REASON)
                out(f"đã khôi phục cách xử lý ban đầu: {ban_dau}")
            else:
                out(f"cách xử lý hiện hành đã là ban đầu ({ban_dau}) — không cần khôi phục")
        except Exception as exc:  # noqa: BLE001 — không để lỗi khôi phục che lỗi chính; báo rõ để người chạy tự đặt lại
            err(f"CẢNH BÁO: chưa khôi phục được cách xử lý ban đầu {ban_dau} "
                f"({exc if isinstance(exc, SimError) else type(exc).__name__}) — đặt lại bằng tay ở màn Chính sách")  # fmt: skip
            code = 1
    out("tổng: " + ", ".join(f"{s} {n}" for s, n in counts.items()) if counts else "tổng: 0 ticket")
    return code or data_check(sim.stats, err)


def data_check(stats: Mapping[str, tuple[int, int, int]], err: Callable[[str], None]) -> int:
    """Cảnh báo dữ liệu thử không dùng được (chạy SAU khôi phục). E2 ưu tiên hơn "0 tới bước duyệt" vì E2 là nguyên nhân."""
    code = 0
    for strategy, (leaves, approvals, e2) in stats.items():
        if approvals == 0:
            err(f"không ticket nào tới bước duyệt ở cách {strategy} — dữ liệu thử không dùng được")
            code = code or NO_APPROVAL
        if leaves and e2 / leaves > E2_MAX_RATIO:
            err(f"ml-service/RAG lỗi ở cách {strategy}, dữ liệu thử không dùng được")
            code = ML_ERROR
    return code


def main(
    argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None, client: httpx.Client | None = None,
    prompt: Callable[[str], str] = getpass.getpass, sleep: Callable[[float], None] = time.sleep,
    run: Callable[..., Any] = subprocess.run, out: Callable[[str], None] = print,
    err: Callable[[str], None] = lambda s: print(s, file=sys.stderr),
) -> int:  # fmt: skip
    parser = argparse.ArgumentParser(description="Chạy dữ liệu thử 3 cách xử lý M5 (chỉ stack dev/test)")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--tagged", action="store_true", help="thêm [fake:<preset>] cuối câu — bắt buộc khi LLM_BACKEND=scripted")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--tuan-tu", action="store_true", help="(mặc định) gửi từng ticket, chờ dừng rồi mới gửi ticket kế")
    mode.add_argument("--song-song", action="store_true", help="gửi hết 8 ticket rồi mới chờ — chỉ khi máy đủ mạnh")
    parser.add_argument("--no-mock-reset", action="store_true", help="không reset mock giữa các vòng")
    args = parser.parse_args(argv)
    env = os.environ if env is None else env
    reason = refuse(env, args.url)
    if reason is not None:
        err(f"TỪ CHỐI: {reason}")
        return 2
    own = client is None
    http = client or httpx.Client(base_url=args.url, timeout=30)
    try:
        sim = Sim(http, env, tagged=args.tagged, prompt=prompt, sleep=sleep, run=run, mock_reset=not args.no_mock_reset,
                  run_id=time.strftime("%Y%m%d%H%M%S"), sequential=not args.song_song)  # fmt: skip
        return run_all(sim, out, err)
    finally:
        if own:
            http.close()


if __name__ == "__main__":
    sys.exit(main())
