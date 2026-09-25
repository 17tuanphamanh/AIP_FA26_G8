"""Test giữ chỗ: khi chưa có logic nghiệp vụ, pytest vẫn phải thu được ít nhất
một test — không có test nào thì pytest trả mã 5 và hook pre-commit coi là đỏ.
Xoá file này khi backend/tests/unit/ đã có test thật."""

from pathlib import Path


def test_app_package_resolves_to_backend() -> None:
    # pythonpath = ["backend"] trong pyproject.toml: `import app` phải ra backend/app,
    # không phải ml_service/app hay mock_services/app.
    import app

    assert Path(app.__file__).parent.parent.name == "backend"
