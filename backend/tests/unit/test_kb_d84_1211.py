"""K1 soát 12/11 (agent 08 Q8/V15): KB thật (`kb/`) không được bảo người dùng TỰ đặt lại / đổi mật khẩu khi nghi bị lộ.

D-84: tài khoản nghi bị xâm nhập / lộ mật khẩu / vừa nhập mật khẩu vào trang giả → kỹ thuật viên xử lý (agent chuyển E1), không tự phục vụ.
Trước sửa, KB-GEN-008 bước 3 bảo "đổi mật khẩu … theo tài liệu tự đặt lại mật khẩu" — RAG trả câu này cho "lỡ nhập mật khẩu vào trang lạ
thì làm gì" là trái với chính hành vi của agent. Luật kiểm: trong một mục `##` có dấu hiệu bị lộ, mọi câu nói tới tự đặt lại / đổi mật
khẩu phải là câu phủ định ("không …"). KB-ACC-001 (quy trình tự đặt lại) phải nói rõ trường hợp nghi bị lộ thì không dùng quy trình này.
"""

import re
from pathlib import Path

KB = Path(__file__).resolve().parents[3] / "kb"
LEAK = re.compile(r"bị lộ|nhập mật khẩu vào trang|người lạ đăng nhập|bị hack|bị chiếm", re.IGNORECASE)
SELF = re.compile(r"tự đặt lại|tự đổi|đổi mật khẩu", re.IGNORECASE)
NEG = re.compile(r"\bkhông\b", re.IGNORECASE)


def _sections(text: str) -> list[str]:
    body = text.split("\n---\n", 1)[-1]
    return re.split(r"\n(?=## )", body)


def _sentences(section: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+|\n", section) if s.strip()]


def test_kb_khong_bao_tu_dat_lai_khi_nghi_bi_lo() -> None:
    bad = [
        f"{p.relative_to(KB)}: {s.strip()}"
        for p in sorted(KB.rglob("*.md"))
        if p.name != "README.md"
        for sec in _sections(p.read_text(encoding="utf-8"))
        if LEAK.search(sec)
        for s in _sentences(sec)
        if SELF.search(s) and not NEG.search(s)
    ]
    assert bad == []


def test_quy_trinh_tu_dat_lai_loai_tru_ca_nghi_bi_lo() -> None:
    text = (KB / "account" / "KB-ACC-001.md").read_text(encoding="utf-8")
    assert re.search(r"nghi[^.\n]*(bị lộ|người lạ đăng nhập)[^.\n]*không dùng quy trình này", text), "KB-ACC-001 thiếu câu loại trừ"


def test_luat_kiem_bat_duoc_cau_cu() -> None:
    old = ("## Nếu đã lỡ bấm liên kết hoặc nhập thông tin\n\nNếu bạn đã lỡ nhập mật khẩu vào trang web lạ:\n\n"
           "3. Nếu đã nhập mật khẩu, đổi mật khẩu tài khoản công ty càng sớm càng tốt theo tài liệu tự đặt lại mật khẩu.")  # fmt: skip
    [sec] = [s for s in _sections(old) if LEAK.search(s)]
    assert [s for s in _sentences(sec) if SELF.search(s) and not NEG.search(s)]
