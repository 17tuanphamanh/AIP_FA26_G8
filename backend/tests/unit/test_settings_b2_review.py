"""Gói 1 (D-52) DỪNG 2 — Settings B2 `review`, τ, `active` chỉ dev/test; compose + `.env.example`.

Viết TỪ ĐẶC TẢ, trước code: `docs/spec/claude/dac-ta-bat-2-model.md` mục 4.5 ("τ tới backend": `b2_tau_review` / biến
`B2_TAU_REVIEW`, khoảng [0,50; 0,9999], không mặc định; `review` thiếu τ → từ chối khởi động; thêm vào `x-backend-env` và
`.env.example` để trống), 4.7 (`active` chỉ khi `APP_ENV` là dev hoặc test), mục 8 (dòng `test_ml_deploy`: ml-service thêm
`GUARD_MANIFEST_SHA256` nhóm được rỗng; `ML_CLASSIFY_CONCURRENCY`, `ML_MODELS_ROOT` không truyền qua compose);
`PLAN-B2REVIEW.md` bảng 3.3 D, mục 8.

Field mới đọc qua `cast(Any, …)` để qua mypy ở DỪNG 1.
"""

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from app.settings import Settings, get_settings
from pydantic import ValidationError
from tests.fakes.graph import GraphHarness

pytestmark = pytest.mark.xfail(reason="gói 1 DỪNG 2 — chưa nối", strict=False)

REPO = Path(__file__).resolve().parents[3]
TAU_ERR = r"(?i)b2_tau_review"


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("B2_CLASSIFIER_MODE", raising=False)
    monkeypatch.delenv("B2_TAU_REVIEW", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _settings() -> Any:
    return cast(Any, Settings())


# ---- review + τ ----------------------------------------------------------------------------------------------------------


def test_review_with_tau_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "review")
    monkeypatch.setenv("B2_TAU_REVIEW", "0.8")
    s = _settings()
    assert (s.b2_classifier_mode, s.b2_tau_review) == ("review", 0.8)


@pytest.mark.parametrize("tau", [None, ""])  # "" = compose `${B2_TAU_REVIEW:-}` khi .env không đặt
def test_review_without_tau_refuses(monkeypatch: pytest.MonkeyPatch, tau: str | None) -> None:
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "review")
    if tau is not None:
        monkeypatch.setenv("B2_TAU_REVIEW", tau)
    with pytest.raises(ValidationError, match=TAU_ERR):
        Settings()


def test_review_without_tau_graph_refuses_to_build(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dựng graph (B2 `make`, backend VÀ worker) đọc Settings → không khởi động được."""
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "review")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match=TAU_ERR):
        GraphHarness(nodes="real")


@pytest.mark.parametrize("tau", ["0.5", "0.50", "0.8", "0.9999"])
def test_tau_in_range(monkeypatch: pytest.MonkeyPatch, tau: str) -> None:
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "review")
    monkeypatch.setenv("B2_TAU_REVIEW", tau)
    assert _settings().b2_tau_review == pytest.approx(float(tau))


@pytest.mark.parametrize("tau", ["0.49", "0.4999", "0.99995", "1.0", "1", "0", "-0.8", "nan", "inf", "abc"])
def test_tau_out_of_range_refuses(monkeypatch: pytest.MonkeyPatch, tau: str) -> None:
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "review")
    monkeypatch.setenv("B2_TAU_REVIEW", tau)
    with pytest.raises(ValidationError, match=TAU_ERR):
        Settings()


# ---- active chỉ dev/test --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("app_env", [None, "staging", "prod"])
def test_active_outside_dev_test_refuses(monkeypatch: pytest.MonkeyPatch, app_env: str | None) -> None:
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "active")
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    with pytest.raises(ValidationError, match=r"(?i)active|b2_classifier_mode|APP_ENV"):
        Settings()


@pytest.mark.parametrize("app_env", ["dev", "test"])
def test_active_in_dev_test_accepted(monkeypatch: pytest.MonkeyPatch, app_env: str) -> None:
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "active")
    monkeypatch.setenv("APP_ENV", app_env)
    assert Settings().b2_classifier_mode == "active"


@pytest.mark.parametrize("app_env", [None, "staging", "prod"])
def test_review_allowed_in_real_envs(monkeypatch: pytest.MonkeyPatch, app_env: str | None) -> None:
    """`review` là chế độ cho bản ứng viên — không bị luật "chỉ dev/test" của `active`."""
    monkeypatch.setenv("B2_CLASSIFIER_MODE", "review")
    monkeypatch.setenv("B2_TAU_REVIEW", "0.9")
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    assert _settings().b2_classifier_mode == "review"


# ---- mặc định ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("env", [None, ""])
def test_default_shadow_no_tau(monkeypatch: pytest.MonkeyPatch, env: str | None) -> None:
    if env is not None:
        monkeypatch.setenv("B2_CLASSIFIER_MODE", env)
    s = _settings()
    assert (s.b2_classifier_mode, s.b2_tau_review) == ("shadow", None)


def test_shadow_with_tau_set_is_fine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tự chọn (ĐT mục 7 "Cấu hình" không ghim): τ đặt sẵn khi vẫn chạy `shadow` → vẫn khởi động, τ không dùng."""
    monkeypatch.setenv("B2_TAU_REVIEW", "0.9")
    s = _settings()
    assert (s.b2_classifier_mode, s.b2_tau_review) == ("shadow", 0.9)


# ---- compose + .env.example -----------------------------------------------------------------------------------------------


def _compose() -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8")))


def test_compose_backend_env_has_tau() -> None:
    c = _compose()
    assert c["x-backend-env"]["B2_TAU_REVIEW"] == "${B2_TAU_REVIEW:-}"
    for name in ("backend", "worker"):
        assert c["services"][name]["environment"]["B2_TAU_REVIEW"] == "${B2_TAU_REVIEW:-}"


def test_compose_ml_service_manifest_sha_and_no_new_numeric_env() -> None:
    env = _compose()["services"]["ml-service"]["environment"]
    assert env["GUARD_MANIFEST_SHA256"] == "${GUARD_MANIFEST_SHA256:-}"
    assert "ML_CLASSIFY_CONCURRENCY" not in env and "ML_MODELS_ROOT" not in env


def test_env_example_tau_blank() -> None:
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    tau = [line for line in lines if re.match(r"^#?\s*B2_TAU_REVIEW\s*=", line)]
    assert tau, ".env.example thiếu dòng B2_TAU_REVIEW"
    assert all(re.fullmatch(r"#?\s*B2_TAU_REVIEW\s*=\s*", line) for line in tau)  # để trống tới khi chọn xong τ
