"""Mock hệ thống ngoài THẬT (uvicorn, subprocess, seed.json) cho test e2e — dùng chung qua fixture
`mock_server` / `reset` ở `conftest.py`. Token dịch vụ sinh ngẫu nhiên mỗi lần, không đọc `.env`."""

import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from app.settings import Settings

REPO = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class MockServer:
    url: str
    agent: str
    executor: str

    def settings(self) -> Settings:
        return Settings(_env_file=None, mock_url=self.url, svc_agent_token=self.agent)  # type: ignore[call-arg, arg-type]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def run_mock() -> Iterator[MockServer]:
    port = _free_port()
    server = MockServer(f"http://127.0.0.1:{port}", secrets.token_urlsafe(32), secrets.token_urlsafe(32))
    env = {**os.environ, "PYTHONPATH": str(REPO / "mock_services"), "SVC_AGENT_TOKEN": server.agent,
           "SVC_EXECUTOR_TOKEN": server.executor}  # fmt: skip
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port),
         "--log-level", "warning"],
        env=env, cwd=REPO,
    )  # fmt: skip
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"{server.url}/health", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if proc.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"mock không lên được (exit={proc.poll()})")
            time.sleep(0.2)
        yield server
    finally:
        proc.terminate()
        proc.wait(timeout=10)
