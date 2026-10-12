"""M9 A0 — ghim hợp đồng import của monitor (kế hoạch M9 mục 4.1.4, 4.2).

- #2 `monitor-read-only`: monitor không import tầng ghi/nghiệp vụ.
- #10 `monitor-only-api-worker`: nguồn liệt kê tường minh mọi package/module cấp một của `app` trừ api, monitor,
  main, worker (import-linter không có "mọi thứ trừ …"). Thêm package mới mà quên khai báo → test chống quên đỏ
  (cùng kiểu `test_write_adapters_listed.py`).
"""

import configparser
from pathlib import Path

from app.monitor import views

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / ".importlinter"
APP_DIR = REPO / "backend" / "app"
READ_ONLY = "importlinter:contract:monitor-read-only"
ONLY_API_WORKER = "importlinter:contract:monitor-only-api-worker"
EXEMPT = {"api", "monitor", "main", "worker"}  # được import app.monitor (main: composition root)
READ_ONLY_FORBIDDEN = {
    "app.graph", "app.executor", "app.tools",
    "app.audit", "app.approval", "app.risk", "app.api", "app.guard", "app.llm", "app.rag",
}  # fmt: skip


def _modules(config_path: Path, contract: str, key: str) -> set[str]:
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")
    return set(cfg[contract][key].split())


def top_level_modules(app_dir: Path, package: str) -> set[str]:
    """Package (thư mục có __init__.py) và module .py cấp một, trừ EXEMPT."""
    names = {p.parent.name for p in app_dir.glob("*/__init__.py")}
    names |= {p.stem for p in app_dir.glob("*.py") if p.stem != "__init__"}
    return {f"{package}.{n}" for n in names - EXEMPT}


def unlisted_sources(app_dir: Path, config_path: Path, package: str) -> list[str]:
    listed = _modules(config_path, ONLY_API_WORKER, "source_modules")
    return sorted(top_level_modules(app_dir, package) - listed)


def test_monitor_read_only_forbids_required_modules() -> None:
    assert READ_ONLY_FORBIDDEN - _modules(CONFIG, READ_ONLY, "forbidden_modules") == set()
    # X2: nguồn phải là CẢ package — thu hẹp thành `app.monitor.views` thì phần còn lại của monitor hết bị cấm
    assert _modules(CONFIG, READ_ONLY, "source_modules") == {"app.monitor"}


def test_monitor_only_api_worker_lists_every_top_level_module() -> None:
    assert len(top_level_modules(APP_DIR, "app")) >= 18  # quét rỗng/sai thư mục thì test phải đỏ, không xanh giả
    assert unlisted_sources(APP_DIR, CONFIG, "app") == []


def test_monitor_only_api_worker_sources_equal_scan() -> None:
    assert _modules(CONFIG, ONLY_API_WORKER, "source_modules") == top_level_modules(APP_DIR, "app")
    assert _modules(CONFIG, ONLY_API_WORKER, "forbidden_modules") == {"app.monitor"}


def test_monitor_contracts_have_no_escape_hatch() -> None:
    # X2 (kiểm thử độc lập 01/10): thêm `ignore_imports` thì lint vẫn KEPT → hợp đồng hở mà không test nào đỏ.
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG, encoding="utf-8")
    for contract in (READ_ONLY, ONLY_API_WORKER):
        section = cfg[contract]
        assert "ignore_imports" not in section, contract
        assert not section.getboolean("allow_indirect_imports", fallback=False), contract


def test_checker_catches_unlisted_package(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    for pkg in ("audit", "moi", "api", "monitor", "__pycache__"):
        (app_dir / pkg).mkdir(parents=True)
        if pkg != "__pycache__":
            (app_dir / pkg / "__init__.py").touch()
    for mod in ("__init__.py", "settings.py", "main.py", "worker.py"):
        (app_dir / mod).touch()
    config = tmp_path / ".importlinter"
    config.write_text(
        f"[{ONLY_API_WORKER}]\nsource_modules =\n    app.audit\nforbidden_modules =\n    app.monitor\n",
        encoding="utf-8",
    )
    assert unlisted_sources(app_dir, config, "app") == ["app.moi", "app.settings"]


def test_views_constants() -> None:
    assert (views.V_LEAF, views.V_DECISIONS, views.V_L2_QUEUE) == ("v_leaf", "v_decisions", "v_l2_queue")
