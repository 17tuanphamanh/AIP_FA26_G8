"""Lái stack compose đang chạy cho harness G2 — CHÉP tối thiểu từ `backend/tests/stack/gate2.py` (check_url, check_command, Shell,
safety_gate, wait_for, Ctx.after_event, approvals) vì `app.*` không import `tests.*`.

Khác gate2:
- Không echo lệnh / SQL (chế độ mặc định chỉ in số tổng hợp). Thông điệp lỗi không chép stdout/stderr của lệnh.
- `Shell.sql` đặt `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY` trước MỌI câu — M8 chỉ đọc DB.
- Đồng hồ + sleep tiêm vào (`Clock`) để test không ngủ thật; `Deadline` = hạn của MỘT kịch bản, `elapsed >= timeout_s` là hết.
- HTTP lỗi → `StackError` chỉ nêu phương thức + mẫu đường dẫn + mã (`POST /api/auth/login → 401`, `http_status`) — không id, không
  thân trả về.

Script không đọc `.env`: compose tự đọc; psql chạy trong container postgres bằng biến của chính container (như gate2).
"""

import json
import re
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

SAFE_HOST = "127.0.0.1"
DEFAULT_URL = f"http://{SAFE_HOST}:8000"
PSQL = 'psql -X -q -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
READ_ONLY = "SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;\n"
SAFE_ID = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

type Headers = dict[str, str]
type Sql = Callable[[str], Any]
type Run = Callable[[list[str], str | None], tuple[int, str]]


class Unsafe(Exception):
    """Chốt an toàn không qua — dừng hẳn, không chạy lệnh nào nữa."""


class StackError(Exception):
    """Stack không làm được việc harness cần (lệnh lỗi, HTTP sai mã, dữ liệu lạ). `http_status` = mã HTTP khi lỗi do Api trả sai mã
    (góp ý G16: phân biệt 401 sai mật khẩu với lỗi khác mà không phải xem log backend); thông điệp chỉ có mẫu đường dẫn + mã."""

    def __init__(self, message: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.http_status = http_status


class ScenarioTimeout(Exception):
    """Hết `timeout_s` của kịch bản."""


# ---- chốt an toàn (gate2) ---------------------------------------------------------------------------------------------


def check_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname != SAFE_HOST or parts.path not in ("", "/"):
        raise Unsafe(f"URL backend: chỉ nhận http://{SAFE_HOST}:<cổng> (stack dev trên máy này)")
    return url.rstrip("/")


def check_command(cmd: Sequence[str]) -> None:
    """Cấm mọi lệnh xoá volume (gate2)."""
    args = list(cmd)
    if "down" in args:
        for arg in args[args.index("down") + 1 :]:
            short = arg.startswith("-") and not arg.startswith("--") and "v" in arg[1:]
            if arg == "--volumes" or arg.startswith("--volumes=") or short:
                raise Unsafe("từ chối lệnh xoá volume")
    if "volume" in args and ({"rm", "prune"} & set(args[args.index("volume") + 1 :])):
        raise Unsafe("từ chối lệnh xoá volume")


def quote(value: str) -> str:
    """Id do hệ thống sinh (ticket, phiếu, user) — vẫn kiểm dạng trước khi đặt vào SQL."""
    if not SAFE_ID.fullmatch(value):
        raise StackError("id lạ (không đặt vào SQL)")
    return f"'{value}'"


def subprocess_run(cmd: list[str], stdin: str | None) -> tuple[int, str]:
    done = subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=False)
    return done.returncode, done.stdout


class Shell:
    """Điểm DUY NHẤT chạy lệnh ngoài: kiểm `check_command`; không echo."""

    def __init__(self, compose: Sequence[str], run: Run = subprocess_run) -> None:
        self.compose_base = list(compose)
        self._run = run

    def run(self, cmd: Sequence[str], *, stdin: str | None = None) -> str:
        cmd = list(cmd)
        check_command(cmd)
        code, out = self._run(cmd, stdin)
        if code != 0:
            raise StackError(f"lệnh lỗi (mã {code}): {shlex.join(cmd[:4])} …")
        return out

    def compose(self, *args: str) -> str:
        return self.run([*self.compose_base, *args])

    def sql(self, query: str) -> Any:
        """Một câu SELECT trả MỘT giá trị JSON, trong transaction CHỈ ĐỌC. Chạy trong container postgres."""
        out = self.run([*self.compose_base, "exec", "-T", "postgres", "sh", "-c", PSQL], stdin=READ_ONLY + query)
        return json.loads(out.strip() or "null")

    def env(self, service: str, names: Sequence[str]) -> dict[str, str | None]:
        """Biến môi trường của container (không đặt → None). Người gọi chỉ SO, không in giá trị."""
        if not names or not all(ENV_NAME.fullmatch(n) for n in names):
            raise StackError("tên biến môi trường lạ")
        script = "".join(f'if [ -n "${{{n}+x}}" ]; then printf "1%s\\0" "${n}"; else printf "0\\0"; fi; ' for n in names)
        out = self.compose("exec", "-T", service, "sh", "-c", script)
        parts = out.split("\0")[: len(names)]
        if len(parts) != len(names):
            raise StackError("đọc biến môi trường của container: thiếu giá trị")
        return {n: (p[1:] if p.startswith("1") else None) for n, p in zip(names, parts, strict=True)}


def safety_gate(shell: Shell) -> None:
    if shell.env("backend", ["APP_ENV"])["APP_ENV"] != "dev":
        raise Unsafe("APP_ENV của container backend không phải 'dev' — dừng")


# ---- đồng hồ / hạn kịch bản -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Clock:
    monotonic: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


@dataclass
class Deadline:
    clock: Clock
    seconds: float
    start: float = field(init=False)

    def __post_init__(self) -> None:
        self.start = self.clock.monotonic()

    def elapsed(self) -> float:
        return self.clock.monotonic() - self.start

    def expired(self) -> bool:
        return self.elapsed() >= self.seconds

    def check(self) -> None:
        if self.expired():
            raise ScenarioTimeout


def wait_for[T](fn: Callable[[], T | None], deadline: Deadline, interval: float = 0.5) -> T:
    """Poll có hạn (không sleep mù): trả giá trị đầu tiên khác None; hết hạn kịch bản → `ScenarioTimeout`."""
    while True:
        deadline.check()
        value = fn()
        if value is not None:
            return value
        deadline.check()
        deadline.clock.sleep(interval)


# ---- DB: lượt, phiếu duyệt, user ---------------------------------------------------------------------------------------


def turns_state(sql: Sql, ticket_id: str) -> tuple[int, int]:
    """(số lượt, số lượt CHƯA đóng) của ticket."""
    row = sql(
        "SELECT json_build_object('n', count(*), 'open', count(*) FILTER (WHERE ended_at IS NULL)) "
        f"FROM turns WHERE ticket_id = {quote(ticket_id)}"
    )  # fmt: skip
    return int(row["n"]), int(row["open"])


def wait_turn_closed(sql: Sql, ticket_id: str, turns_before: int, deadline: Deadline, interval: float = 0.5) -> None:
    """gate2 `after_event`: request 202 chạy lượt NỀN — chờ có hơn `turns_before` lượt và mọi lượt đã đóng."""
    def done() -> bool | None:
        n, open_ = turns_state(sql, ticket_id)
        return True if n > turns_before and open_ == 0 else None
    wait_for(done, deadline, interval)


def pending_approval(sql: Sql, ticket_id: str) -> tuple[str, str] | None:
    """(approval_id, approver_id) của phiếu `pending` mới nhất."""
    row = sql(
        "SELECT json_build_object('approval_id', approval_id, 'approver_id', approver_id) FROM approvals "
        f"WHERE ticket_id = {quote(ticket_id)} AND status = 'pending' ORDER BY created_at DESC LIMIT 1"
    )  # fmt: skip
    return None if row is None else (str(row["approval_id"]), str(row["approver_id"]))


def username_of(sql: Sql, user_id: str) -> str | None:
    value = sql(f"SELECT to_json(username) FROM users WHERE user_id = {quote(user_id)}")
    return None if value is None else str(value)


# ---- HTTP API ---------------------------------------------------------------------------------------------------------


class Api:
    """Đúng các route harness dùng (app/api/tickets.py, approvals.py, auth). Không giữ token: người gọi giữ `Headers`."""

    def __init__(self, http: httpx.Client) -> None:
        self.http = http

    def _call(self, method: str, path: str, shown: str, expect: int, headers: Headers | None = None,
              body: Mapping[str, Any] | None = None) -> httpx.Response:  # fmt: skip
        r = self.http.request(method, path, headers=headers, json=None if body is None else dict(body))
        if r.status_code != expect:
            raise StackError(f"{method} {shown} → {r.status_code}", http_status=r.status_code)
        return r

    def login(self, username: str, password: str) -> Headers:
        r = self._call("POST", "/api/auth/login", "/api/auth/login", 200, body={"username": username, "password": password})
        token = r.json().get("access_token")
        if not isinstance(token, str) or not token:
            raise StackError("POST /api/auth/login: không có access_token")
        return {"Authorization": f"Bearer {token}"}

    def create(self, h: Headers, text: str) -> str:
        r = self._call("POST", "/api/tickets", "/api/tickets", 202, h, {"text": text})
        ticket_id = str(r.json()["ticket_id"])
        quote(ticket_id)
        return ticket_id

    def message(self, h: Headers, ticket_id: str, text: str) -> None:
        self._call("POST", f"/api/tickets/{ticket_id}/messages", "/api/tickets/{id}/messages", 202, h, {"text": text})

    def confirm(self, h: Headers, ticket_id: str, confirmed: bool) -> None:
        self._call("POST", f"/api/tickets/{ticket_id}/confirm", "/api/tickets/{id}/confirm", 202, h, {"confirmed": confirmed})

    def view(self, h: Headers, ticket_id: str) -> dict[str, Any]:
        return dict(self._call("GET", f"/api/tickets/{ticket_id}", "/api/tickets/{id}", 200, h).json())

    def decide(self, h: Headers, approval_id: str, decision: str, note: str | None = None) -> None:
        body: dict[str, Any] = {"decision": decision}
        if note is not None:
            body["note"] = note
        self._call("POST", f"/api/approvals/{approval_id}/decision", "/api/approvals/{id}/decision", 202, h, body)

    def health(self) -> dict[str, Any]:
        r = self.http.get("/api/health")
        try:
            return dict(r.json())
        except ValueError:
            raise StackError("GET /api/health: thân không phải JSON") from None
