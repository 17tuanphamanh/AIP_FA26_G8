"""6A — `app.risk.calibrator` (phase6 4.3, 4.5, 4.6): cb1–cb8.

Dữ liệu tổng hợp = "đoạn sinh dữ liệu tổng hợp chuẩn" spec 4.5, chép nguyên (thứ tự lời gọi `rng` quyết định con số); mỗi
test tạo rng MỚI cùng seed. Khoảng ở cb2 và ngưỡng 1e-3 ở cb3 chép từ spec — không nới. Không ghi cứng `version` hay
`data_sha256` (bit cuối của a, b có thể khác giữa máy arm và CI x86 → hash khác): cb5 chỉ so tương đối + regex định dạng.
Cảnh báo = lỗi (P8: `LogisticRegression` cảnh báo hội tụ/FutureWarning phải làm đỏ).
"""

import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import scipy.optimize
import scipy.special
from app.risk import calibrator as cal_mod
from app.risk.calibrator import (
    Calibrator,
    CalibratorParams,
    FitInfo,
    LabeledSample,
    LeakageError,
    fit_platt,
    fit_temperature,
    load_calibrator,
    require_calibration_split,
    save_calibrator,
)
from app.risk.decision_math import ece
from tests.unit.test_risk_no_eval_import import REPO, hits, imported_modules

pytestmark = pytest.mark.filterwarnings("error")

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
VERSION_RE = re.compile(r"^(platt|temperature)-[0-9]{8}-[0-9a-f]{8}$")
FITS = {"platt": fit_platt, "temperature": fit_temperature}


def make_samples(n: int) -> tuple[list[LabeledSample], np.ndarray, np.ndarray]:
    """Đoạn sinh chuẩn spec 4.5 (cb2, cb3, cb5) — chép nguyên. Trả (samples, raw, y)."""
    rng = np.random.default_rng(20260925)
    p_true = rng.uniform(0.02, 0.98, n)
    y = rng.uniform(0, 1, n) < p_true
    raw = scipy.special.expit(2 * scipy.special.logit(p_true))
    samples = [LabeledSample(split="calibration", family=f"f{i % 50}", raw_prob=float(r), y=bool(v))
               for i, (r, v) in enumerate(zip(raw, y, strict=True))]  # fmt: skip
    return samples, raw, y


def fit_info() -> FitInfo:
    return FitInfo(split="calibration", n=100, n_pos=50, n_families=10, data_sha256="0" * 64)


def platt_params(a: float, b: float, version: str = "platt-20261009-0123abcd") -> CalibratorParams:
    return CalibratorParams(version=version, method="platt", a=a, b=b, fitted_on=fit_info(), created_at=NOW)


def temp_params(t: float, version: str = "temperature-20261009-0123abcd") -> CalibratorParams:
    return CalibratorParams(version=version, method="temperature", temperature=t, fitted_on=fit_info(), created_at=NOW)


# ---- cb1 LeakageError --------------------------------------------------------------------------------------------

SECRET_P = 0.123456789
SECRET_FAMILY = "fam-bimat-7731"


def leaky(position: int) -> list[LabeledSample]:
    samples = make_samples(99)[0]
    bad = LabeledSample(split="test", family=SECRET_FAMILY, raw_prob=SECRET_P, y=True)
    return [*samples[:position], bad, *samples[position:]]


@pytest.mark.parametrize("position", [0, 50, 99], ids=["dau", "giua", "cuoi"])
@pytest.mark.parametrize("fn", [require_calibration_split, fit_platt, fit_temperature],
                         ids=["require", "platt", "temperature"])  # fmt: skip
def test_cb1_leakage(fn: Any, position: int) -> None:
    samples = leaky(position)
    with pytest.raises(LeakageError) as info:
        fn(samples) if fn is require_calibration_split else fn(samples, now=NOW)
    msg = str(info.value)
    assert "1" in msg  # số mẫu sai split
    assert str(SECRET_P) not in msg and "0.1234" not in msg and SECRET_FAMILY not in msg


def test_cb1_all_test_split_also_leakage() -> None:
    samples = [s.model_copy(update={"split": "test"}) for s in make_samples(20)[0]]
    with pytest.raises(LeakageError):
        require_calibration_split(samples)


def test_cb1_empty_is_value_error() -> None:
    with pytest.raises(ValueError):
        require_calibration_split([])
    require_calibration_split(make_samples(20)[0])  # đủ calibration → không ném


class _Spy:
    def __init__(self, real: Any) -> None:
        self.real, self.calls = real, 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        return self.real(*args, **kwargs)


@pytest.mark.parametrize("method", ["platt", "temperature"])
def test_cb1_no_fit_before_split_check(method: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """`require_calibration_split` chạy TRƯỚC mọi tính toán: có mẫu sai split → bộ fit (sklearn/scipy) chưa được gọi lần nào."""
    lr, ms = _Spy(cal_mod.LogisticRegression), _Spy(cal_mod.minimize_scalar)
    monkeypatch.setattr(cal_mod, "LogisticRegression", lr)
    monkeypatch.setattr(cal_mod, "minimize_scalar", ms)
    with pytest.raises(LeakageError):
        FITS[method](leaky(99), now=NOW)
    assert lr.calls == 0 and ms.calls == 0
    FITS[method](make_samples(99)[0], now=NOW)  # đối chứng: spy có tác dụng
    assert lr.calls + ms.calls >= 1


# ---- cb2 dữ liệu tự tin quá mức ------------------------------------------------------------------------------------


def test_cb2_overconfident_synthetic() -> None:
    samples, raw, y = make_samples(5_000)
    platt = fit_platt(samples, now=NOW)
    temp = fit_temperature(samples, now=NOW)
    a, b, t = platt.params.a, platt.params.b, temp.params.temperature
    assert a is not None and b is not None and t is not None
    assert 0.45 <= a <= 0.53
    assert -0.05 <= b <= 0.05
    assert 1.9 <= t <= 2.2
    before = ece(raw, y)
    for c in (platt, temp):
        after = ece([c.transform(float(r)) for r in raw], y)
        assert after < 0.03
        assert after < before
    for c in (platt, temp):
        info = c.params.fitted_on
        assert (info.split, info.n, info.n_pos, info.n_families) == ("calibration", 5_000, int(y.sum()), 50)


# ---- cb3 đối chiếu tham chiếu độc lập ------------------------------------------------------------------------------


def test_cb3_platt_matches_reference() -> None:
    samples, raw, y = make_samples(40)
    assert int(y.sum()) == 21  # spec 4.6: n = 40 → 21 ca dương
    eps = 1e-6
    z = scipy.special.logit(np.clip(raw, eps, 1 - eps))
    yf = y.astype(float)

    def nll(theta: np.ndarray) -> float:
        s = theta[0] * z + theta[1]
        return float(-np.mean(yf * scipy.special.log_expit(s) + (1 - yf) * scipy.special.log_expit(-s)))

    ref = scipy.optimize.minimize(nll, x0=np.array([1.0, 0.0]), method="BFGS", options={"gtol": 1e-10})
    got = fit_platt(samples, now=NOW).params
    assert got.a is not None and got.b is not None
    assert abs(got.a - ref.x[0]) <= 1e-3
    assert abs(got.b - ref.x[1]) <= 1e-3


# ---- cb4 transform tính tay ----------------------------------------------------------------------------------------


def test_cb4_transform_hand_values() -> None:
    p = Calibrator(platt_params(0.5, 0.0))
    assert p.transform(0.9) == pytest.approx(0.75, abs=1e-12)
    assert p.transform(0.2) == pytest.approx(1 / 3, abs=1e-12)
    t = Calibrator(temp_params(2.0))
    assert t.transform(0.9) == pytest.approx(0.75, abs=1e-12)
    ident_p, ident_t = Calibrator(platt_params(1.0, 0.0)), Calibrator(temp_params(1.0))
    for raw in (1e-3, 0.01, 0.2, 0.5, 0.77, 0.99, 1 - 1e-3):
        assert ident_p.transform(raw) == pytest.approx(raw, abs=1e-12)
        assert ident_t.transform(raw) == pytest.approx(raw, abs=1e-12)
    for c in (ident_p, ident_t):
        hi, lo = c.transform(1.0), c.transform(0.0)
        assert math.isfinite(hi) and hi < 1.0
        assert math.isfinite(lo) and lo > 0.0


@pytest.mark.parametrize("raw", [math.nan, math.inf, -0.1, 1.2])
def test_cb4_transform_rejects_bad_raw(raw: float) -> None:
    with pytest.raises(ValueError) as info:
        Calibrator(platt_params(0.5, 0.0)).transform(raw)
    assert "raw" in str(info.value)
    assert "1.2" not in str(info.value)


def test_cb4_calibrator_immutable() -> None:
    c = Calibrator(platt_params(0.5, 0.0))
    with pytest.raises(AttributeError):
        c.params = platt_params(1.0, 0.0)  # type: ignore[misc]


# ---- cb5 lưu/nạp + tất định ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["platt", "temperature"])
def test_cb5_save_load_roundtrip(method: str, tmp_path: Path) -> None:
    c = FITS[method](make_samples(200)[0], now=NOW)
    assert VERSION_RE.fullmatch(c.params.version)
    assert c.params.version.startswith(f"{method}-20261009-")
    assert c.params.created_at == NOW
    path = save_calibrator(c, tmp_path)
    assert path == tmp_path / f"{c.params.version}.json"
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name]
    loaded = load_calibrator(c.params.version, tmp_path)
    assert loaded.params == c.params
    for i in range(101):
        assert loaded.transform(i / 100) == c.transform(i / 100)
    with pytest.raises(FileExistsError):
        save_calibrator(c, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(c.params.model_dump_json())


@pytest.mark.parametrize("method", ["platt", "temperature"])
def test_cb5_order_invariant(method: str) -> None:
    samples = make_samples(200)[0]
    base = FITS[method](samples, now=NOW).params
    perm = np.random.default_rng(11).permutation(len(samples))
    for shuffled in (list(reversed(samples)), [samples[int(i)] for i in perm]):
        other = FITS[method](shuffled, now=NOW).params
        assert other.fitted_on.data_sha256 == base.fitted_on.data_sha256
        assert other.version == base.version
        assert other == base


@pytest.mark.parametrize("method", ["platt", "temperature"])
def test_cb5_changed_sample_changes_hash_and_version(method: str) -> None:
    samples = make_samples(200)[0]
    base = FITS[method](samples, now=NOW).params
    changed = [samples[0].model_copy(update={"y": not samples[0].y}), *samples[1:]]
    other = FITS[method](changed, now=NOW).params
    assert other.fitted_on.data_sha256 != base.fitted_on.data_sha256
    assert other.version != base.version
    assert re.fullmatch(r"[0-9a-f]{64}", base.fitted_on.data_sha256)


# ---- cb6 kiểm đầu vào ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["platt", "temperature"])
def test_cb6_fit_input_validation(method: str) -> None:
    samples = make_samples(200)[0]
    nine = [*[s for s in samples if s.y][:5], *[s for s in samples if not s.y][:4]]
    with pytest.raises(ValueError):
        FITS[method](nine, now=NOW)
    one_class = [s for s in samples if s.y][:30]
    with pytest.raises(ValueError):
        FITS[method](one_class, now=NOW)
    with pytest.raises(ValueError):
        FITS[method](samples, now=datetime(2026, 10, 9, 12, 0))  # noqa: DTZ001 — cố ý naive (TQ-12)


@pytest.mark.parametrize(
    "fields",
    [{"raw_prob": math.nan}, {"raw_prob": math.inf}, {"raw_prob": 1.2345}, {"raw_prob": -0.5},
     {"split": "train"}, {"extra": 1}],
)  # fmt: skip
def test_cb6_labeled_sample_rejects(fields: dict[str, Any]) -> None:
    base: dict[str, Any] = {"split": "calibration", "family": "f1", "raw_prob": 0.5, "y": True}
    with pytest.raises(ValueError) as info:
        LabeledSample(**{**base, **fields})
    assert "1.2345" not in str(info.value)


# ---- cb7 file hỏng -------------------------------------------------------------------------------------------------


def _write(directory: Path, name: str, data: dict[str, Any]) -> None:
    (directory / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")


def _good(method: str = "platt") -> dict[str, Any]:
    """Nội dung file HỢP LỆ (fit thật → đuôi băm version đúng): mỗi ca cb7/cb9 chỉ có đúng một lỗi do test cài vào."""
    return json.loads(FITS[method](make_samples(40)[0], now=NOW).params.model_dump_json())


def test_cb7_good_file_loads(tmp_path: Path) -> None:
    """Đối chứng: không sửa gì → nạp được (các ca hỏng dưới không đỏ vì lỗi khác)."""
    for method in ("platt", "temperature"):
        data = _good(method)
        _write(tmp_path, data["version"], data)
        assert load_calibrator(data["version"], tmp_path).params.model_dump(mode="json") == data


@pytest.mark.parametrize(
    ("method", "mutate"),
    [("platt", lambda d: d.pop("b")),
     ("platt", lambda d: d.pop("a")),
     ("temperature", lambda d: d.pop("temperature")),
     ("temperature", lambda d: d.update(temperature=0.0)),
     ("temperature", lambda d: d.update(temperature=-1.0)),
     ("platt", lambda d: d.update(temperature=2.0)),
     ("temperature", lambda d: d.update(a=0.5, b=0.0)),
     ("platt", lambda d: d.update(extra="x")),
     ("platt", lambda d: d["fitted_on"].update(extra="x")),
     ("platt", lambda d: d.update(method="temperature", temperature=2.0, a=None, b=None)),  # tiền tố version ≠ method
     ("platt", lambda d: d.update(created_at="2026-10-09T12:00:00")),  # naive
     ("platt", lambda d: d.update(a=None))],
    ids=["platt-thieu-b", "platt-thieu-a", "temp-thieu-T", "temp-T-0", "temp-T-am", "platt-thua-T", "temp-thua-ab",
         "khoa-la", "khoa-la-fitted-on", "tien-to-lech-method", "created-naive", "platt-a-null"],
)  # fmt: skip
def test_cb7_corrupt_file(method: str, mutate: Any, tmp_path: Path) -> None:
    data = _good(method)
    mutate(data)
    _write(tmp_path, data["version"], data)
    with pytest.raises(ValueError):
        load_calibrator(_good(method)["version"], tmp_path)


def test_cb7_file_name_differs_from_version(tmp_path: Path) -> None:
    data = _good()
    assert data["version"] != "platt-20261009-ffffffff"
    _write(tmp_path, "platt-20261009-ffffffff", data)  # tên file khác version trong nội dung
    with pytest.raises(ValueError):
        load_calibrator("platt-20261009-ffffffff", tmp_path)


def test_cb7_invalid_json(tmp_path: Path) -> None:
    (tmp_path / "platt-20261009-0123abcd.json").write_text("{không phải json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_calibrator("platt-20261009-0123abcd", tmp_path)


@pytest.mark.parametrize(
    "version",
    ["../platt-20261009-0123abcd", "platt-20261009-0123abcd/../../x", "/etc/passwd", "platt-20261009-0123abcd\n",  # chuỗi version sai cố ý cho cb7, không phải bí mật  # gitleaks:allow
     "a/b", "platt-20261009-0123abcd\x00", "platt\\20261009-0123abcd",
     "platt-20261009-0123ABCD", "platt-2026109-0123abcd", "platt-٢٠٢٦١٠٠٩-0123abcd", "isotonic-20261009-0123abcd", ""],
)  # fmt: skip
def test_cb7_version_checked_before_path(version: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regex kiểm TRƯỚC khi ghép đường dẫn: không một lần đọc file nào."""
    reads: list[Path] = []

    def no_read(self: Path, *args: Any, **kwargs: Any) -> Any:
        reads.append(self)
        raise AssertionError("load_calibrator đọc file trước khi kiểm version")

    monkeypatch.setattr(Path, "read_text", no_read)
    monkeypatch.setattr(Path, "read_bytes", no_read)
    monkeypatch.setattr(Path, "open", no_read)
    with pytest.raises(ValueError):
        load_calibrator(version, tmp_path)
    assert reads == []


def test_cb7_str_subclass_version_rejected(tmp_path: Path) -> None:
    class Sneaky(str):
        def __format__(self, spec: str) -> str:
            return "../ngoai"

    with pytest.raises(ValueError):
        load_calibrator(Sneaky("platt-20261009-0123abcd"), tmp_path)


def test_cb7_error_does_not_leak_file_content(tmp_path: Path) -> None:
    """Lỗi nạp file chỉ giữ vị trí + loại lỗi; không nội dung, không chuỗi ValidationError gốc (errors() còn `input`)."""
    data = _good()
    data["extra"] = "giatri-bimat-4471"
    data["a"] = "khong-phai-so-9932"
    _write(tmp_path, data["version"], data)
    with pytest.raises(ValueError) as info:
        load_calibrator(data["version"], tmp_path)
    msg = str(info.value)
    assert "giatri-bimat-4471" not in msg and "khong-phai-so-9932" not in msg
    assert info.value.__cause__ is None and info.value.__suppress_context__


def test_cb7_save_rechecks_version(tmp_path: Path) -> None:
    bad = CalibratorParams.model_construct(**{**platt_params(0.5, 0.0).__dict__, "version": "../ngoai"})
    with pytest.raises(ValueError):
        save_calibrator(Calibrator(bad), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_cb7_params_version_regex() -> None:
    with pytest.raises(ValueError):
        platt_params(0.5, 0.0, version="platt-20261009-0123abcd/..")
    with pytest.raises(ValueError):
        platt_params(0.5, 0.0, version="temperature-20261009-0123abcd")


# ---- cb9 tham số đảo chiều / suy biến / sửa tay (Q-6A-4 = A) -------------------------------------------------------


def _saved(method: str, tmp_path: Path) -> tuple[str, Path]:
    c = FITS[method](make_samples(200)[0], now=NOW)
    return c.params.version, save_calibrator(c, tmp_path)


def _edit(path: Path, **changes: Any) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize(
    ("method", "changes"),
    [("platt", {"b": -50.0}), ("platt", "a*10"), ("temperature", "T*1.1"), ("platt", "sha"), ("temperature", "sha")],
    ids=["b-am-50", "a-duong-x10", "T-trong-mien", "sha-platt", "sha-temperature"],
)  # fmt: skip
def test_cb9a_hand_edited_digest_mismatch(method: str, changes: Any, tmp_path: Path) -> None:
    """Sửa tay một giá trị VẪN hợp lệ với validator → chỉ phép so đuôi băm version bắt được."""
    version, path = _saved(method, tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if changes == "a*10":
        changes = {"a": data["a"] * 10}
    elif changes == "T*1.1":
        changes = {"temperature": data["temperature"] * 1.1}
    elif changes == "sha":
        changes = {"fitted_on": {**data["fitted_on"], "data_sha256": "f" * 64}}
    _edit(path, **changes)
    with pytest.raises(ValueError, match="không khớp tham số"):
        load_calibrator(version, tmp_path)


@pytest.mark.parametrize(
    ("method", "changes"),
    [("platt", {"a": -1.0}), ("temperature", {"temperature": 100.0}), ("platt", {"eps": 1e-3}),
     ("temperature", {"eps": 1e-3})],
    ids=["b-a-am", "c-T-100", "d-eps-platt", "d-eps-temperature"],
)  # fmt: skip
def test_cb9bcd_hand_edited_out_of_range(method: str, changes: dict[str, Any], tmp_path: Path) -> None:
    version, path = _saved(method, tmp_path)
    _edit(path, **changes)
    with pytest.raises(ValueError) as info:
        load_calibrator(version, tmp_path)
    assert "100" not in str(info.value) and "0.001" not in str(info.value)


def _inverse_samples(n: int) -> list[LabeledSample]:
    """Cùng cách sinh cb2 nhưng nhãn nghịch: y = U > p_true → raw cao ↔ y thấp (Platt ra a < 0)."""
    rng = np.random.default_rng(20260925)
    p_true = rng.uniform(0.02, 0.98, n)
    y = rng.uniform(0, 1, n) > p_true
    raw = scipy.special.expit(2 * scipy.special.logit(p_true))
    return [LabeledSample(split="calibration", family=f"f{i % 50}", raw_prob=float(r), y=bool(v))
            for i, (r, v) in enumerate(zip(raw, y, strict=True))]  # fmt: skip


def test_cb9e_fit_platt_rejects_inverted(tmp_path: Path) -> None:
    """Chặn ở fit (không dựng params) — thông điệp riêng của fit, không phải ValidationError của validator (lớp thứ hai)."""
    with pytest.raises(ValueError, match="đảo chiều") as info:
        fit_platt(_inverse_samples(200), now=NOW)
    assert type(info.value) is ValueError
    assert list(tmp_path.iterdir()) == []


def test_cb9e_fit_temperature_rejects_edge() -> None:
    with pytest.raises(ValueError, match="chạm biên"):
        fit_temperature(_inverse_samples(200), now=NOW)


@pytest.mark.parametrize(
    "build",
    [lambda: platt_params(0.0, 0.0), lambda: platt_params(-0.5, 0.0), lambda: temp_params(0.04),
     lambda: temp_params(20.5), lambda: CalibratorParams(version="platt-20261009-0123abcd", method="platt", a=1.0, b=0.0,
                                                         eps=1e-3, fitted_on=fit_info(), created_at=NOW)],
    ids=["f-a-0", "a-am", "T-duoi-bien", "T-tren-bien", "eps-khac"],
)  # fmt: skip
def test_cb9f_params_validator(build: Any) -> None:
    with pytest.raises(ValueError):
        build()


def test_cb9_bounds_inclusive() -> None:
    """T_BOUNDS đóng: đúng biên vẫn dựng được (fit mới là nơi từ chối T sát biên)."""
    assert Calibrator(temp_params(0.05)).params.temperature == 0.05
    assert Calibrator(temp_params(20.0)).params.temperature == 20.0


# ---- cb8 AST -------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["decision_math", "calibrator"])
def test_cb8_new_modules_import_only_allowed(name: str) -> None:
    modules = imported_modules(REPO / "backend" / "app" / "risk" / f"{name}.py")
    assert modules  # quét rỗng → đỏ
    for forbidden in ("app.eval", "app.graph", "app.db", "app.llm", "app.api"):
        assert hits(modules, forbidden) == set(), forbidden
    for m in modules:
        root = m.split(".")[0]
        if root == "app":
            assert m.startswith(("app.core", "app.risk")), m
        else:
            assert root in {"numpy", "scipy", "sklearn", "pydantic"} or root in sys.stdlib_module_names, m
