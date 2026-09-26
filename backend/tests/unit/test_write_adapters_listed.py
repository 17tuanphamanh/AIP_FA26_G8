"""Hợp đồng import-linter số 3 liệt kê tường minh adapter ghi (import-linter không nhận
wildcard `*_write`). Test này bắt trường hợp thêm file tools/adapters/*_write.py mà quên thêm
tên vào .importlinter (01 mục 4.3)."""

import configparser
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CONTRACT = "importlinter:contract:write-adapters-only-executor"


def missing_write_adapters(adapters_dir: Path, config_path: Path, package: str) -> list[str]:
    cfg = configparser.ConfigParser()
    cfg.read(config_path, encoding="utf-8")
    listed = set(cfg[CONTRACT]["forbidden_modules"].split())
    found = {f"{package}.{p.stem}" for p in adapters_dir.glob("*_write.py")}
    return sorted(found - listed)


def test_every_write_adapter_listed_in_importlinter() -> None:
    adapters = REPO / "backend" / "app" / "tools" / "adapters"
    assert (REPO / ".importlinter").is_file()
    assert missing_write_adapters(adapters, REPO / ".importlinter", "app.tools.adapters") == []


def test_checker_catches_unlisted_adapter(tmp_path: Path) -> None:
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    for name in ("vpn_write.py", "hr_write.py", "vpn_read.py"):
        (adapters / name).touch()
    config = tmp_path / ".importlinter"
    config.write_text(
        f"[{CONTRACT}]\nforbidden_modules =\n    app.tools.adapters.vpn_write\n", encoding="utf-8"
    )
    assert missing_write_adapters(adapters, config, "app.tools.adapters") == [
        "app.tools.adapters.hr_write"
    ]
