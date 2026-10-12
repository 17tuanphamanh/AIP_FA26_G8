"""Hiệu chỉnh xác suất của M5 (phase6 mục 4.3) — hàm thuần, NGUỒN DUY NHẤT cho M5 lúc vận hành và cho T27 (fit trên dữ liệu
thật ở T37, Phase 10 — Phase 6 KHÔNG fit dữ liệu thật).

- Bất biến 10 [Chốt]: chỉ fit trên split calibration — `require_calibration_split` chạy TRƯỚC mọi tính toán; một mẫu sai
  split → `LeakageError` (thông điệp chỉ nêu SỐ mẫu sai, không in dữ liệu).
- Platt (P8): `z = logit(clip(raw, eps, 1−eps))`, hồi quy logistic KHÔNG phạt trên z: `LogisticRegression(C=np.inf,
  tol=1e-10, max_iter=1000)` (`penalty=None` sinh FutureWarning trên sklearn 1.9.1; `tol` mặc định lệch nghiệm ~1e-4).
  Temperature: `T = argmin NLL(sigmoid(z/T))`, `minimize_scalar` bounded (0,05; 20), `xatol = 1e-6`.
- Tất định (4.3): sắp mẫu theo `(family, raw_prob, y)` TRƯỚC khi fit (cộng số thực không giao hoán — không sắp thì cùng dữ
  liệu đảo thứ tự cho tham số lệch bit cuối → `version` khác). `data_sha256` tự sắp riêng (không phụ thuộc bước trên).
  `version = f"{method}-{now:%Y%m%d}-{sha256(json(params_số) + data_sha256)[:8]}"`; `now` truyền vào (không đọc đồng hồ).
- Lưu/nạp JSON `<directory>/<version>.json` chỉ trong thư mục được truyền; `load_calibrator` khớp regex `version` TRƯỚC khi
  ghép đường dẫn (không có dấu đường dẫn nào lọt qua), rồi tính lại đuôi băm của `version` từ tham số + `data_sha256`.
  Đuôi băm 8 hex chỉ chống SỬA NHẦM/sửa tay — không phải chữ ký (ai ghi được thư mục tự tính lại được); rào thật là quyền
  ghi thư mục calibrator.
- Q-6A-4 = A (chặn FN do hiệu chỉnh đảo chiều/suy biến): `CalibratorParams` đòi platt a > 0, temperature ∈ T_BOUNDS, eps = EPS
  (cả lúc dựng tay lẫn lúc nạp); `fit_platt` từ chối a ≤ 0, `fit_temperature` từ chối T cách biên < T_EDGE.
"""

import hashlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from numbers import Real
from pathlib import Path
from typing import Literal, Self

import numpy as np
import scipy.special
from pydantic import BaseModel, Field, ValidationError, model_validator
from scipy.optimize import minimize_scalar
from sklearn.linear_model import LogisticRegression

VERSION_PATTERN = r"(platt|temperature)-[0-9]{8}-[0-9a-f]{8}"  # `[0-9]` (không `\d` — khớp cả chữ số Unicode); dùng fullmatch
_VERSION_RE = re.compile(VERSION_PATTERN)
MIN_SAMPLES = 10
EPS = 1e-6  # P8
T_BOUNDS = (0.05, 20.0)
T_EDGE = 1e-3  # T cách biên T_BOUNDS dưới ngưỡng này → fit_temperature từ chối


class LeakageError(Exception):
    """Fit calibrator/chọn ngưỡng trên dữ liệu không thuộc split calibration [Chốt bất biến 10]."""


class LabeledSample(BaseModel, frozen=True, extra="forbid", hide_input_in_errors=True):
    split: Literal["calibration", "test"]
    family: str  # họ kịch bản (đơn vị chia tập)
    raw_prob: float = Field(ge=0.0, le=1.0, allow_inf_nan=False)
    y: bool  # True = gold ≠ AUTO ("cần người")


class FitInfo(BaseModel, frozen=True, extra="forbid", hide_input_in_errors=True):
    split: Literal["calibration"]
    n: int = Field(ge=1)
    n_pos: int = Field(ge=0)
    n_families: int = Field(ge=1)
    data_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CalibratorParams(BaseModel, frozen=True, extra="forbid", hide_input_in_errors=True):
    version: str
    method: Literal["platt", "temperature"]
    a: float | None = Field(default=None, allow_inf_nan=False)  # platt: a, b bắt buộc
    b: float | None = Field(default=None, allow_inf_nan=False)
    temperature: float | None = Field(default=None, allow_inf_nan=False)  # temperature: bắt buộc, ∈ T_BOUNDS
    eps: float = EPS
    fitted_on: FitInfo
    created_at: datetime

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not _VERSION_RE.fullmatch(self.version) or not self.version.startswith(f"{self.method}-"):
            raise ValueError("version: sai định dạng hoặc tiền tố khác method")
        if self.method == "platt" and (self.a is None or self.b is None or self.temperature is not None):
            raise ValueError("platt: cần đủ a, b và không có temperature")
        if self.method == "temperature" and (self.temperature is None or self.a is not None or self.b is not None):
            raise ValueError("temperature: cần temperature và không có a, b")
        # Q-6A-4 = A: a ≤ 0 đảo chiều hiệu chỉnh → ca rủi ro cao thành AUTO (FN); T ngoài miền tối ưu / eps lạ ép mọi p về ~0,5
        if self.method == "platt" and not (self.a is not None and self.a > 0):
            raise ValueError("a: phải dương")
        if self.method == "temperature" and not (
            self.temperature is not None and T_BOUNDS[0] <= self.temperature <= T_BOUNDS[1]
        ):
            raise ValueError("temperature: ngoài miền T_BOUNDS")
        if self.eps != EPS:
            raise ValueError("eps: phải bằng EPS")
        if self.created_at.utcoffset() is None:
            raise ValueError("created_at: phải có múi giờ")
        return self


def _z(raw: np.ndarray, eps: float) -> np.ndarray:
    return np.asarray(scipy.special.logit(np.clip(raw, eps, 1.0 - eps)), dtype=float)


@dataclass(frozen=True, slots=True)
class Calibrator:
    """Bất biến sau khi tạo; `Calibrator(params)`."""

    params: CalibratorParams

    def transform(self, raw: float) -> float:
        """raw ∉ [0, 1] / NaN / inf → ValueError; kết quả ∈ [0, 1]."""
        if isinstance(raw, bool) or not isinstance(raw, Real) or not 0.0 <= float(raw) <= 1.0:  # NaN: so sánh luôn False
            raise ValueError("raw: phải là số thực trong đoạn [0, 1]")
        prm = self.params
        z = float(_z(np.array([float(raw)]), prm.eps)[0])
        if prm.method == "platt":
            assert prm.a is not None and prm.b is not None  # validator bảo đảm
            s = prm.a * z + prm.b
        else:
            assert prm.temperature is not None
            s = z / prm.temperature
        return float(scipy.special.expit(s))


def require_calibration_split(samples: Sequence[LabeledSample]) -> None:
    """Rỗng → ValueError; có mẫu split ≠ "calibration" → LeakageError (thông điệp: số mẫu sai split, KHÔNG in dữ liệu)."""
    if len(samples) == 0:
        raise ValueError("samples: rỗng")
    if any(not isinstance(s, LabeledSample) for s in samples):
        raise ValueError("samples: phần tử phải là LabeledSample")
    wrong = sum(1 for s in samples if s.split != "calibration")
    if wrong:
        raise LeakageError(f"{wrong} mẫu không thuộc split calibration — chỉ được fit trên calibration")


def _sort_key(s: LabeledSample) -> tuple[str, float, bool]:
    return (s.family, s.raw_prob, s.y)


def _data_sha256(samples: Sequence[LabeledSample]) -> str:
    """sha256 của JSON chuẩn hoá danh sách `[family, raw_prob, y]` đã sắp theo `(family, raw_prob, y)`."""
    rows = [[s.family, s.raw_prob, s.y] for s in sorted(samples, key=_sort_key)]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _prepare(samples: Sequence[LabeledSample], now: datetime) -> tuple[list[LabeledSample], np.ndarray, np.ndarray]:
    """Kiểm (sau `require_calibration_split`) rồi trả mẫu ĐÃ SẮP + (raw, y) theo thứ tự đó."""
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now: phải là datetime có múi giờ")
    if len(samples) < MIN_SAMPLES:
        raise ValueError("samples: cần ít nhất 10 mẫu")
    rows = sorted(samples, key=_sort_key)
    y = np.array([s.y for s in rows], dtype=bool)
    if y.all() or not y.any():
        raise ValueError("samples: cần cả hai lớp y")
    return rows, np.array([s.raw_prob for s in rows], dtype=float), y


def _numbers(params: CalibratorParams) -> dict[str, float]:
    """Tham số số của method + eps — đầu vào băm đuôi `version` (lúc fit: `_build`; lúc nạp: `load_calibrator`)."""
    if params.method == "platt":
        assert params.a is not None and params.b is not None  # validator bảo đảm
        return {"a": params.a, "b": params.b, "eps": params.eps}
    assert params.temperature is not None
    return {"eps": params.eps, "temperature": params.temperature}


def _version_digest(numbers: dict[str, float], data_sha256: str) -> str:
    """`sha256(json(params_số) + data_sha256)[:8]` — JSON chuẩn hoá (khoá sắp, không khoảng trắng)."""
    params_json = json.dumps(numbers, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((params_json + data_sha256).encode()).hexdigest()[:8]


def _build(
    method: Literal["platt", "temperature"], numbers: dict[str, float], rows: Sequence[LabeledSample], now: datetime
) -> Calibrator:
    data_sha = _data_sha256(rows)
    digest = _version_digest(numbers, data_sha)
    info = FitInfo(
        split="calibration",
        n=len(rows),
        n_pos=sum(1 for s in rows if s.y),
        n_families=len({s.family for s in rows}),
        data_sha256=data_sha,
    )
    fields = {k: v for k, v in numbers.items() if k != "eps"}
    params = CalibratorParams(
        version=f"{method}-{now:%Y%m%d}-{digest}",
        method=method,
        eps=numbers["eps"],
        fitted_on=info,
        created_at=now,
        **fields,
    )
    return Calibrator(params)


def fit_platt(samples: Sequence[LabeledSample], *, now: datetime) -> Calibrator:
    """Platt không phạt trên z (P8). `require_calibration_split` TRƯỚC mọi tính toán; n < 10 hoặc một lớp → ValueError."""
    samples = tuple(samples)  # chụp MỘT lần — Sequence tự viết không thể đổi nội dung giữa lúc kiểm split và lúc fit
    require_calibration_split(samples)
    rows, raw, y = _prepare(samples, now)
    z = _z(raw, EPS).reshape(-1, 1)
    model = LogisticRegression(C=np.inf, tol=1e-10, max_iter=1000)
    model.fit(z, y)
    a, b = float(model.coef_[0, 0]), float(model.intercept_[0])
    if not (math.isfinite(a) and math.isfinite(b)):
        raise ValueError("samples: Platt không hội tụ về tham số hữu hạn")
    if a <= 0:  # chặn TRƯỚC khi dựng params (validator là lớp thứ hai) — không lưu, không trả Calibrator
        raise ValueError("samples: Platt ra a ≤ 0 — đảo chiều hiệu chỉnh (dữ liệu suy biến)")
    return _build("platt", {"a": a, "b": b, "eps": EPS}, rows, now)


def fit_temperature(samples: Sequence[LabeledSample], *, now: datetime) -> Calibrator:
    """Temperature scaling (P8): `T = argmin NLL(sigmoid(z/T))`. Kiểm như `fit_platt`."""
    samples = tuple(samples)  # chụp MỘT lần — Sequence tự viết không thể đổi nội dung giữa lúc kiểm split và lúc fit
    require_calibration_split(samples)
    rows, raw, y = _prepare(samples, now)
    z = _z(raw, EPS)
    yf = y.astype(float)

    def nll(t: float) -> float:
        s = z / t
        return float(-np.mean(yf * scipy.special.log_expit(s) + (1.0 - yf) * scipy.special.log_expit(-s)))

    res = minimize_scalar(nll, method="bounded", bounds=T_BOUNDS, options={"xatol": 1e-6})
    t = float(res.x)
    if not res.success or not math.isfinite(t):
        raise ValueError("samples: temperature không hội tụ")
    if min(t - T_BOUNDS[0], T_BOUNDS[1] - t) < T_EDGE:  # tối ưu chạm biên = dữ liệu suy biến
        raise ValueError("samples: temperature chạm biên T_BOUNDS (dữ liệu suy biến)")
    return _build("temperature", {"eps": EPS, "temperature": t}, rows, now)


def save_calibrator(cal: Calibrator, directory: Path) -> Path:
    """Ghi `<directory>/<version>.json`; đã có → FileExistsError (mở chế độ "x" — tạo độc quyền). Không tạo thư mục."""
    version = cal.params.version
    if not _VERSION_RE.fullmatch(version):  # params đã kiểm; chặn lại lần nữa ngay trước khi ghép đường dẫn
        raise ValueError("version: sai định dạng")
    path = Path(directory) / f"{version}.json"
    with path.open("x", encoding="utf-8") as f:
        f.write(cal.params.model_dump_json())
    return path


def load_calibrator(version: str, directory: Path) -> Calibrator:
    """Nạp `<directory>/<version>.json`. version không khớp regex (kiểm TRƯỚC khi ghép đường dẫn) / tên file ≠ version /
    thiếu tham số theo method / khoá lạ / JSON hỏng / tham số ngoài miền / đuôi version không khớp băm tham số → ValueError;
    file không có → FileNotFoundError."""
    if type(version) is not str or not _VERSION_RE.fullmatch(version):  # lớp con của str có thể đổi `__format__`
        raise ValueError("version: sai định dạng")
    text = (Path(directory) / f"{version}.json").read_text(encoding="utf-8")
    try:
        params = CalibratorParams.model_validate_json(text)
    except ValidationError as exc:  # `hide_input_in_errors` chỉ giấu ở str(); errors()/json() vẫn mang `input` → chỉ giữ loc + loại
        problems = sorted({(".".join(map(str, e["loc"])), e["type"]) for e in exc.errors(include_input=False)})
        raise ValueError(f"file calibrator không hợp lệ: {problems}") from None
    if params.version != version:
        raise ValueError("version: tên file khác version trong nội dung")
    if not version.endswith("-" + _version_digest(_numbers(params), params.fitted_on.data_sha256)):
        raise ValueError("version: không khớp tham số")  # sửa tay/sửa nhầm a, b, T, eps hoặc data_sha256
    return Calibrator(params)
