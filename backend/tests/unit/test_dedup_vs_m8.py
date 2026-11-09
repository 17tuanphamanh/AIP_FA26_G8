"""training/common/dedup_vs_m8.py — kiểm trùng câu thẻ với dữ liệu huấn luyện (P11 mục 3.4 bước 2).

Dữ liệu giả tự dựng trong tmp_path; embedder giả thay `_embed_batch` (điểm gọi HTTP duy nhất) — không chạm mạng, không tải model.
"""

import csv
import importlib
import json
import types
from pathlib import Path

import httpx
import pytest
import respx

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def mod(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    monkeypatch.syspath_prepend(str(ROOT))
    monkeypatch.delenv("ML_SERVICE_TOKEN", raising=False)
    return importlib.import_module("training.common.dedup_vs_m8")


class FakeEmbed:
    """Tra vector theo văn bản gửi lên (đã `normalize`); ghi lại từng lô và token."""

    def __init__(self, vecs: dict[str, list[float]] | None = None, default: list[float] | None = None) -> None:
        self.vecs = vecs or {}
        self.default = default or [0.0, 1.0]
        self.batches: list[list[str]] = []
        self.tokens: list[str | None] = []

    def __call__(self, url: str, texts: list[str], token: str | None) -> list[list[float]]:
        self.batches.append(list(texts))
        self.tokens.append(token)
        return [self.vecs.get(t, self.default) for t in texts]


def jsonl(path: Path, rows: list[dict[str, str]]) -> Path:
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return path


def read_out(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def run(mod: types.ModuleType, tmp_path: Path, cau: Path, *train: Path, extra: tuple[str, ...] = ()) -> int:
    args = ["--cau", str(cau), "--out", str(tmp_path / "out.csv"), *extra]
    for t in train:
        args += ["--train", str(t)]
    code = mod.main(args)
    assert isinstance(code, int)
    return code


# ---------- Bước A: khớp chính xác ----------


def test_exact_khac_dau_hoa_thuong_khoang_trang(mod, tmp_path, capsys):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "Quên mật khẩu VPN"}])
    train = tmp_path / "train.txt"
    train.write_text("  QUEN MAT   khau\tvpn \n", encoding="utf-8")
    code = run(mod, tmp_path, cau, train, extra=("--no-embed",))
    assert code == 3
    (row,) = read_out(tmp_path / "out.csv")
    assert (row["the"], row["text"], row["kieu"], row["diem"]) == ("T1", "Quên mật khẩu VPN", "exact", "1.000000")
    assert row["nguon_file"] == str(train)
    assert "QUEN" in row["cau_train_gan_nhat"]


def test_train_nhan_thu_muc_nhieu_dinh_dang_va_lap_nhieu_lan(mod, tmp_path):
    d = tmp_path / "data"
    (d / "sub").mkdir(parents=True)
    jsonl(d / "a.jsonl", [{"text": "câu một", "nhan": "x"}])
    (d / "sub" / "b.csv").write_text("id,text\n1,Câu hai\n", encoding="utf-8")
    (d / "c.txt").write_text("cau ba\n", encoding="utf-8")
    (d / "bo_qua.md").write_text("câu bốn\n", encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("Câu năm\n", encoding="utf-8")
    cau = jsonl(
        tmp_path / "cau.jsonl",
        [{"the": f"T{i}", "text": t} for i, t in enumerate(["câu một", "câu hai", "câu ba", "câu bốn", "câu năm"])],
    )
    assert run(mod, tmp_path, cau, d, other, extra=("--no-embed",)) == 3
    got = {r["text"]: Path(r["nguon_file"]).name for r in read_out(tmp_path / "out.csv")}
    assert got == {"câu một": "a.jsonl", "câu hai": "b.csv", "câu ba": "c.txt", "câu năm": "other.txt"}


# ---------- Bước B: cosine ----------


def _cosine_case(mod, tmp_path, monkeypatch, vec_train, *extra):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T9", "text": "mở khóa tài khoản"}])
    train = tmp_path / "train.txt"
    train.write_text("tài khoản bị khóa cần mở\n", encoding="utf-8")
    fake = FakeEmbed({"mở khóa tài khoản": [1.0, 0.0], "tài khoản bị khóa cần mở": vec_train})
    monkeypatch.setattr(mod, "_embed_batch", fake)
    code = run(mod, tmp_path, cau, train, extra=("--embed-url", "http://ml:8200", *extra))
    return code, read_out(tmp_path / "out.csv"), fake


def test_gan_trung_tren_nguong(mod, tmp_path, monkeypatch):
    code, rows, _ = _cosine_case(mod, tmp_path, monkeypatch, [0.95, 0.312249])  # cos ≈ 0.95 ≥ 0.90 mặc định
    assert code == 3
    (row,) = rows
    assert (row["the"], row["kieu"]) == ("T9", "cosine")
    assert 0.94 < float(row["diem"]) < 0.96
    assert row["cau_train_gan_nhat"] == "tài khoản bị khóa cần mở"
    assert row["nguon_file"].endswith("train.txt")


def test_gan_trung_duoi_nguong(mod, tmp_path, monkeypatch):
    code, rows, _ = _cosine_case(mod, tmp_path, monkeypatch, [0.8, 0.6])  # cos 0.8 < 0.90
    assert code == 0
    assert rows == []


def test_dung_bang_nguong_tinh_la_trung(mod, tmp_path, monkeypatch):
    code, rows, _ = _cosine_case(mod, tmp_path, monkeypatch, [3.0, 4.0], "--nguong", "0.6")  # cos đúng 0.6
    assert code == 3
    assert [r["kieu"] for r in rows] == ["cosine"]


def test_nguong_khong_hop_le(mod, tmp_path, monkeypatch):
    fake = FakeEmbed()
    monkeypatch.setattr(mod, "_embed_batch", fake)
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "câu"}])
    for bad in ("1.5", "0", "-0.2"):
        assert run(mod, tmp_path, cau, cau.with_suffix(".txt"), extra=("--embed-url", "http://ml", "--nguong", bad)) == 2
    assert fake.batches == []


def test_gui_lo_toi_da_64(mod, tmp_path, monkeypatch):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": f"câu số {i}"} for i in range(130)])
    train = tmp_path / "train.txt"
    train.write_text("mẫu huấn luyện\n", encoding="utf-8")
    fake = FakeEmbed({"mẫu huấn luyện": [1.0, 0.0]}, default=[0.0, 1.0])
    monkeypatch.setattr(mod, "_embed_batch", fake)
    assert run(mod, tmp_path, cau, train, extra=("--embed-url", "http://ml")) == 0
    assert [len(b) for b in fake.batches] == [64, 64, 3]


def test_cau_da_trung_chinh_xac_khong_embed_lai(mod, tmp_path, monkeypatch):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "Đặt lại mật khẩu"}, {"the": "T2", "text": "in ấn lỗi"}])
    train = tmp_path / "train.txt"
    train.write_text("dat lai mat khau\nmáy in báo lỗi\n", encoding="utf-8")
    fake = FakeEmbed({"in ấn lỗi": [1.0, 0.0], "máy in báo lỗi": [1.0, 0.0]})
    monkeypatch.setattr(mod, "_embed_batch", fake)
    assert run(mod, tmp_path, cau, train, extra=("--embed-url", "http://ml")) == 3
    embedded = {t for b in fake.batches for t in b}
    assert "Đặt lại mật khẩu" not in embedded
    assert {r["the"]: r["kieu"] for r in read_out(tmp_path / "out.csv")} == {"T1": "exact", "T2": "cosine"}


# ---------- --no-embed ----------


def test_no_embed_khong_goi_embedder_va_bao_ro(mod, tmp_path, monkeypatch, capsys):
    def boom(*a, **k):
        raise AssertionError("không được gọi embed khi --no-embed")

    monkeypatch.setattr(mod, "_embed_batch", boom)
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "câu gần giống"}])
    train = tmp_path / "train.txt"
    train.write_text("câu hơi giống\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--no-embed",)) == 0
    assert "BỎ QUA (--no-embed)" in capsys.readouterr().out
    assert read_out(tmp_path / "out.csv") == []


def test_thieu_ca_embed_url_lan_no_embed(mod, tmp_path):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "x"}])
    with pytest.raises(SystemExit) as e:
        mod.main(["--cau", str(cau), "--train", str(cau), "--out", str(tmp_path / "o.csv")])
    assert e.value.code == 2


# ---------- tóm tắt ----------


def test_tom_tat_dem_dung(mod, tmp_path, monkeypatch, capsys):
    cau = jsonl(
        tmp_path / "cau.jsonl",
        [
            {"the": "T1", "text": "Quên mật khẩu"},
            {"the": "T1", "text": "câu độc lập"},
            {"the": "T2", "text": "vpn không kết nối"},
            {"the": "T3", "text": "hoàn toàn khác"},
        ],
    )
    train = tmp_path / "train.txt"
    train.write_text("quen mat khau\nvpn mất kết nối\n", encoding="utf-8")
    fake = FakeEmbed(
        {"vpn không kết nối": [1.0, 0.0, 0.0], "vpn mất kết nối": [1.0, 0.0, 0.0], "quen mat khau": [0.0, 1.0, 0.0]},
        default=[0.0, 0.0, 1.0],
    )
    monkeypatch.setattr(mod, "_embed_batch", fake)
    assert run(mod, tmp_path, cau, train, extra=("--embed-url", "http://ml")) == 3
    out = capsys.readouterr().out
    assert "Số câu thẻ: 4" in out
    assert "Trùng chính xác: 1" in out
    assert "Gần trùng (cosine ≥ 0.9): 1" in out
    assert "Số thẻ bị ảnh hưởng: 2" in out


def test_khong_trung_thi_ma_thoat_0(mod, tmp_path, capsys):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "một câu riêng"}])
    train = tmp_path / "train.txt"
    train.write_text("câu khác hẳn\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--no-embed",)) == 0
    assert "Số thẻ bị ảnh hưởng: 0" in capsys.readouterr().out
    assert read_out(tmp_path / "out.csv") == []


# ---------- lỗi đầu vào → mã 2, không lộ nội dung ----------


def test_jsonl_hong_ma_2_khong_lo_noi_dung(mod, tmp_path, capsys):
    cau = tmp_path / "cau.jsonl"
    cau.write_text('{"the": "T1", "text": "NOIDUNG_BI_MAT"\n', encoding="utf-8")
    train = tmp_path / "train.txt"
    train.write_text("x\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--no-embed",)) == 2
    cap = capsys.readouterr()
    assert "dòng 1" in cap.err
    assert "NOIDUNG_BI_MAT" not in cap.out + cap.err


def test_train_jsonl_hong_ma_2(mod, tmp_path, capsys):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "câu"}])
    train = tmp_path / "train.jsonl"
    train.write_text('{"text": "ok"}\nTRAIN_BI_MAT khong phai json\n', encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--no-embed",)) == 2
    cap = capsys.readouterr()
    assert "dòng 2" in cap.err
    assert "TRAIN_BI_MAT" not in cap.out + cap.err


@pytest.mark.parametrize(
    "row",
    [{"text": "thiếu thẻ"}, {"the": "T1"}, {"the": "", "text": "thẻ rỗng"}, {"the": "T1", "text": "   "}],
)
def test_cau_thieu_the_hoac_text_ma_2(mod, tmp_path, row):
    cau = jsonl(tmp_path / "cau.jsonl", [row])
    train = tmp_path / "train.txt"
    train.write_text("x\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--no-embed",)) == 2


def test_file_khong_ton_tai_ma_2(mod, tmp_path):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "câu"}])
    assert run(mod, tmp_path, tmp_path / "khong_co.jsonl", cau, extra=("--no-embed",)) == 2
    assert run(mod, tmp_path, cau, tmp_path / "khong_co.txt", extra=("--no-embed",)) == 2


def test_csv_train_thieu_cot_text_ma_2(mod, tmp_path):
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "câu"}])
    train = tmp_path / "train.csv"
    train.write_text("id,noi_dung\n1,câu\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--no-embed",)) == 2


def test_embed_loi_ma_2(mod, tmp_path, monkeypatch, capsys):
    def down(url, texts, token):
        raise httpx.ConnectError("EMBED_URL_BI_MAT")

    monkeypatch.setattr(mod, "_embed_batch", down)
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "câu"}])
    train = tmp_path / "train.txt"
    train.write_text("khác\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--embed-url", "http://ml")) == 2
    cap = capsys.readouterr()
    assert "ConnectError" in cap.err
    assert "EMBED_URL_BI_MAT" not in cap.out + cap.err


def test_embed_tra_sai_so_vector_ma_2(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_embed_batch", lambda url, texts, token: [[1.0, 0.0]])
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "câu"}])
    train = tmp_path / "train.txt"
    train.write_text("khác\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--embed-url", "http://ml")) == 2


# ---------- không in trường ngoài the/text ----------


def test_khong_in_truong_ngoai_the_text(mod, tmp_path, monkeypatch, capsys):
    cau = jsonl(
        tmp_path / "cau.jsonl",
        [{"the": "T1", "text": "Quên mật khẩu", "bi_mat": "GIATRI_BI_MAT", "gold": "LABEL_BI_MAT"}],
    )
    train = tmp_path / "train.txt"
    train.write_text("quen mat khau\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--no-embed",)) == 3
    cap = capsys.readouterr()
    raw = (tmp_path / "out.csv").read_text(encoding="utf-8")
    for secret in ("GIATRI_BI_MAT", "LABEL_BI_MAT", "bi_mat", "gold"):
        assert secret not in cap.out + cap.err + raw
    assert "Quên mật khẩu" not in cap.out + cap.err  # nội dung câu chỉ nằm trong CSV
    assert list(read_out(tmp_path / "out.csv")[0]) == [
        "the", "text", "kieu", "diem", "cau_train_gan_nhat", "nguon_file",
    ]  # fmt: skip


# ---------- gọi HTTP thật (đã mock bằng respx) và token ----------


def test_token_lay_tu_bien_moi_truong_khong_in(mod, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ML_SERVICE_TOKEN", "TOKEN_BI_MAT")
    fake = FakeEmbed({"a": [1.0, 0.0], "b": [0.0, 1.0]})
    monkeypatch.setattr(mod, "_embed_batch", fake)
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "a"}])
    train = tmp_path / "train.txt"
    train.write_text("b\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--embed-url", "http://ml")) == 0
    assert fake.tokens == ["TOKEN_BI_MAT"]
    cap = capsys.readouterr()
    assert "TOKEN_BI_MAT" not in cap.out + cap.err


@respx.mock
def test_embed_batch_hop_dong_http(mod):
    route = respx.post("http://ml:8200/embed").mock(
        return_value=httpx.Response(
            200, json={"vectors": [[1.0, 0.0], [0.0, 1.0]], "dim": 2, "model": "m", "truncated": [False] * 2, "token_counts": [1, 1]}
        )
    )
    assert mod._embed_batch("http://ml:8200/", ["x", "y"], "tok") == [[1.0, 0.0], [0.0, 1.0]]
    req = route.calls.last.request
    assert json.loads(req.content) == {"texts": ["x", "y"]}
    assert req.headers["X-Service-Token"] == "tok"


@respx.mock
def test_embed_http_401_ma_2(mod, tmp_path, capsys):
    respx.post("http://ml:8200/embed").mock(return_value=httpx.Response(401, json={"detail": "invalid_service_token"}))
    cau = jsonl(tmp_path / "cau.jsonl", [{"the": "T1", "text": "câu"}])
    train = tmp_path / "train.txt"
    train.write_text("khác\n", encoding="utf-8")
    assert run(mod, tmp_path, cau, train, extra=("--embed-url", "http://ml:8200")) == 2
    assert "HTTP 401" in capsys.readouterr().err
