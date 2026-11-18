"""Script đối chiếu model intent với LLM (`scripts/eval/doi_chieu_intent/`) — dữ liệu giả, không gọi ml-service hay LLM.

Thêm một test ghim file `eval/doi-chieu-intent/dau-vao.jsonl` đã commit (đủ 100 thẻ, sha câu đúng, trạng thái LLM).
"""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[4]
DIR = REPO / "scripts" / "eval" / "doi_chieu_intent"


def _load(name: str) -> ModuleType:
    if str(DIR) not in sys.path:
        sys.path.insert(0, str(DIR))
    return importlib.import_module(name)


cb = _load("chuan_bi")
ch = _load("cham")
pt = _load("phan_tich")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- chuan_bi -------------------------------------------------------------------------------------------------------------


def test_llm_view_phan_loai_trang_thai(tmp_path: Path) -> None:
    pred = tmp_path / "p.jsonl"
    pred.write_text(
        "\n".join(
            json.dumps({"run_id": cb.S1_RUN_ID, "scenario_id": s, "intent": i})
            for s, i in [("A", "vpn"), ("B", None)]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "o.jsonl"
    out.write_text(
        "\n".join(
            json.dumps({"scenario_id": s, "outcome": o})
            for s, o in [("A", "ok"), ("C", "multi_leaf"), ("D", "error")]
        ),
        encoding="utf-8",
    )
    v = cb.llm_view(pred, out)
    assert v == {
        "A": ("mot_la", "vpn"),
        "B": ("dung_o_b2", None),
        "C": ("tach_nhieu_y", None),
        "D": ("khong_chay", None),
    }


def test_llm_view_tu_choi_luot_khac(tmp_path: Path) -> None:
    pred = tmp_path / "p.jsonl"
    pred.write_text(
        json.dumps({"run_id": "khac", "scenario_id": "A", "intent": "vpn"}),
        encoding="utf-8",
    )
    (tmp_path / "o.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="không phải lượt"):
        cb.llm_view(pred, tmp_path / "o.jsonl")


def test_build_rows_dung_cau_dau_da_che() -> None:
    cards = [
        {
            "id": "X1",
            "family": "F",
            "turns": ["Câu gốc", {"reply": "x"}],
            "gold": {"intents": ["access"]},
        }
    ]
    rows = cb.build_rows(cards, lambda t: t.upper(), {})
    assert rows == [{
        "id": "X1", "family": "F", "text": "CÂU GỐC", "text_sha256": _sha("CÂU GỐC"), "gold_intent": "access",
        "llm_status": "khong_chay", "llm_intent": None,
    }]  # fmt: skip


# ---- cham -----------------------------------------------------------------------------------------------------------------


def _dau_vao_lines(texts: dict[str, str]) -> list[str]:
    head = {
        "kind": "header",
        "app_commit": "bf94df2" + "0" * 33,
        "s1_run_id": cb.S1_RUN_ID,
        "n": len(texts),
    }
    rows = [{"id": k, "text": t, "text_sha256": _sha(t), "gold_intent": "vpn", "llm_status": "mot_la", "llm_intent": "vpn"}
            for k, t in texts.items()]  # fmt: skip
    return [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in [head, *rows]]


def _fake_post(probs: dict[str, float]) -> Any:
    calls: list[tuple[str, Any]] = []

    def post(path: str, body: Any) -> dict[str, Any]:
        calls.append((path, body))
        if path == "/health":
            return {"status": "ok"}
        return {
            "probs": probs,
            "truncated": False,
            "model": "intent-clf",
            "version": "v3.1-seed42-st",
            "tau_hi": {},
            "tau_lo": {},
        }

    post.calls = calls  # type: ignore[attr-defined]
    return post


def test_cham_goi_tung_cau_va_ghi_header() -> None:
    lines = _dau_vao_lines({"A": "vpn hỏng", "B": "quên mật khẩu"})
    post = _fake_post(dict.fromkeys(pt.LABELS, 0.1) | {"vpn": 0.9})
    out = ch.score(lines, post)
    assert out[0]["kind"] == "header" and out[0]["health"] == {"status": "ok"}
    assert out[0]["dau_vao_sha256"] == _sha("".join(line + "\n" for line in lines))
    assert [c[1] for c in post.calls[1:]] == [
        {"text": "vpn hỏng"},
        {"text": "quên mật khẩu"},
    ]
    assert [r["id"] for r in out[1:]] == ["A", "B"] and out[1][
        "version"
    ] == "v3.1-seed42-st"


def test_cham_dung_khi_sha_cau_lech() -> None:
    lines = _dau_vao_lines({"A": "vpn hỏng"})
    row = json.loads(lines[1])
    row["text"] = "câu đã bị sửa"
    lines[1] = json.dumps(row, ensure_ascii=False)
    with pytest.raises(SystemExit, match="sha"):
        ch.score(lines, _fake_post(dict.fromkeys(pt.LABELS, 0.2)))


# ---- phan_tich ------------------------------------------------------------------------------------------------------------


def _bo(
    cases: list[tuple[str, str, str | None, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    """cases: (id, gold, llm hoặc None = dung_o_b2, nhãn model)."""
    head = {
        "kind": "header",
        "app_commit": "bf94df2" + "0" * 33,
        "s1_run_id": cb.S1_RUN_ID,
    }
    dv = [head] + [{"id": i, "text": i, "text_sha256": _sha(i), "gold_intent": g,
                    "llm_status": "mot_la" if llm else "dung_o_b2", "llm_intent": llm} for i, g, llm, _ in cases]  # fmt: skip
    sha = "f" * 64
    mr = [{"kind": "header", "dau_vao_sha256": sha, "health": {}}] + [
        {"id": i, "text_sha256": _sha(i), "probs": dict.fromkeys(pt.LABELS, 0.05) | {m: 0.8}, "truncated": False,
         "model": "intent-clf", "version": "v3.1-seed42-st"} for i, _, _, m in cases]  # fmt: skip
    return dv, mr, sha


def test_phan_tich_tinh_X_Y_Z_va_bang_cheo() -> None:
    dv, mr, sha = _bo([
        ("a", "vpn", "vpn", "vpn"),        # cả hai đúng
        ("b", "access", "access", "account"),  # chỉ model sai
        ("c", "account", "access", "account"),  # chỉ LLM sai
        ("d", "software", None, "software"),   # dừng ở B2: chỉ vào Y 100 thẻ
    ])  # fmt: skip
    k = pt.analyse(dv, mr, sha)
    assert (k["Y_model_khop_vang_100"]["k"], k["Y_model_khop_vang_100"]["n"]) == (3, 4)
    assert (
        k["Y_model_khop_vang_tap_chung"]["k"],
        k["Y_model_khop_vang_tap_chung"]["n"],
    ) == (2, 3)
    assert (k["X_model_khop_llm"]["k"], k["X_model_khop_llm"]["n"]) == (1, 3)
    assert (k["Z_llm_khop_vang"]["k"], k["Z_llm_khop_vang"]["n"]) == (2, 3)
    assert k["bang_cheo_tap_chung"] == {
        "ca_hai_dung": 1,
        "chi_model_sai": 1,
        "chi_llm_sai": 1,
        "ca_hai_sai": 0,
    }
    assert {r["id"] for r in k["ca_lech"]} == {"b", "c"}
    lo, hi = k["X_model_khop_llm"]["ktc95"]
    assert 0.0 < lo < 1 / 3 < hi < 1.0
    md = pt.bang_md(k)
    assert "| b | access | access | account |" in md and "Model khớp LLM" in md
    # nhãn theo số câu thật, không ghi cứng 100 thẻ
    assert "trên 4 câu" in md and "cả 4 câu: 3/4" in md and "100 thẻ" not in md


def test_phan_tich_tu_choi_sha_dau_vao_lech() -> None:
    dv, mr, _ = _bo([("a", "vpn", "vpn", "vpn")])
    with pytest.raises(ValueError, match="sha"):
        pt.analyse(dv, mr, "0" * 64)


def test_phan_tich_tu_choi_hai_phien_ban_model() -> None:
    dv, mr, sha = _bo([("a", "vpn", "vpn", "vpn"), ("b", "vpn", "vpn", "vpn")])
    mr[2]["version"] = "khac"
    with pytest.raises(ValueError, match="phiên bản"):
        pt.analyse(dv, mr, sha)


def test_model_label_hoa_diem_thi_dung() -> None:
    with pytest.raises(ValueError, match="hoà"):
        pt.model_label(dict.fromkeys(pt.LABELS, 0.2))
    with pytest.raises(ValueError, match="5 nhãn"):
        pt.model_label({"vpn": 1.0})


def test_macro_f1_tinh_out_of_scope_la_sai() -> None:
    assert (
        pt.macro_f1(
            ["vpn", "access", "account", "software"],
            ["vpn", "access", "account", "software"],
        )
        == 1.0
    )
    assert (
        pt.macro_f1(
            ["vpn", "access", "account", "software"],
            ["vpn", "access", "account", "out_of_scope"],
        )
        == 0.75
    )


# ---- file đầu vào đã commit -----------------------------------------------------------------------------------------------


def test_dau_vao_da_commit_du_100_the() -> None:
    rows = pt.read_jsonl(REPO / "eval" / "doi-chieu-intent" / "dau-vao.jsonl")
    head, items = rows[0], rows[1:]
    assert (
        head["kind"] == "header"
        and head["app_commit"].startswith("bf94df2")
        and head["s1_run_id"] == "95b5a579ec7e"
    )
    assert len(items) == 100 and len({r["id"] for r in items}) == 100
    assert all(_sha(r["text"]) == r["text_sha256"] for r in items)
    status = {s: sum(r["llm_status"] == s for r in items) for s in cb.STATUS}
    assert status == {"mot_la": 93, "dung_o_b2": 3, "tach_nhieu_y": 2, "khong_chay": 2}
    assert all(
        (r["llm_intent"] is None) == (r["llm_status"] != "mot_la") for r in items
    )


def test_gop_R1_R2_theo_luat_khoa_truoc() -> None:
    def row(i: str, gold: str, llm: str, model: str, p: float) -> dict[str, Any]:
        return {"id": i, "gold": gold, "llm": llm, "model": model, "p_max": p}

    one = [
        row("a", "vpn", "vpn", "vpn", 0.9),  # khớp, đúng
        row(
            "b", "access", "account", "access", 0.9
        ),  # lệch, model chắc và đúng → R2 sửa đúng
        row(
            "c", "account", "account", "access", 0.95
        ),  # lệch, model chắc nhưng sai → R2 sửa sai
        row(
            "d", "software", "software", "vpn", 0.6
        ),  # lệch, model không chắc → R2 giữ LLM
    ]
    g = pt.gop(one)
    assert (g["chi_llm"]["k"], g["chi_llm"]["n"]) == (3, 4)
    r1 = g["R1_dong_thuan"]
    assert (
        r1["tu_nhan"],
        r1["tu_nhan_dung"]["k"],
        r1["chuyen_nguoi_them"],
        r1["llm_sai_duoc_chan"],
    ) == (1, 1, 3, 1)
    r2 = g["R2_model_sua_khi_chac"]
    assert (r2["dung"]["k"], r2["so_lan_sua"], r2["sua_dung"], r2["sua_sai"]) == (
        3,
        2,
        1,
        1,
    )


def test_gop_tap_rong_khong_vo() -> None:
    g = pt.gop([])
    assert g["chi_llm"]["n"] == 0 and g["R1_dong_thuan"]["tu_nhan"] == 0
    assert pt._pct(g["chi_llm"]) == "0/0"


def test_chuan_bi_cong5_lay_nhan_llm_va_cau_tu_ticket() -> None:
    c5 = _load("chuan_bi_cong5")
    kq = {"rows": [
        {"id": "I-ACS-07", "kind": "intent", "gold": "access", "labels": ["out_of_scope"], "ticket": "t1"},
        {"id": "I-ACC-01", "kind": "intent", "gold": "account", "labels": [], "ticket": "t2"},
        {"id": "A-01", "kind": "attack", "gold": None, "labels": [], "ticket": "t3"},
    ]}  # fmt: skip
    tickets = {
        "t1": {"redacted_request": "xin quyền"},
        "t2": {"redacted_request": "quên mk"},
        "t3": {"redacted_request": "x"},
    }
    rows = c5.build_rows(kq, tickets, str.upper)
    assert [
        (r["id"], r["family"], r["text"], r["llm_status"], r["llm_intent"])
        for r in rows
    ] == [
        ("I-ACS-07", "I-ACS", "XIN QUYỀN", "mot_la", "out_of_scope"),
        ("I-ACC-01", "I-ACC", "QUÊN MK", "khong_nhan", None),
    ]
    assert rows[0]["text_sha256"] == _sha("XIN QUYỀN")
