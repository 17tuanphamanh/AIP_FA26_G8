"""Cac tool ma agent duoc phep goi.

Moi tool gom 2 phan:
  - mot ham Python thuan (doc_file, liet_ke_file) - de goi truc tiep va viet test;
  - mot ban boc @beta_tool (tool_doc_file, ...) - de dua cho Claude.

Docstring cua ban boc chinh la phan Claude doc de biet khi nao goi tool nay,
nen viet cho ky. Schema tham so duoc SDK sinh tu type hint.

Them tool moi: viet ham thuan, viet ban boc @beta_tool, them vao DANH_SACH_TOOL.
"""

from pathlib import Path

from anthropic import beta_tool

from agent.config import GOC_REPO

# Gioi han so ky tu doc ra tu mot file, tranh nhoi het context window.
GIOI_HAN_KY_TU = 20_000


def _duong_dan_an_toan(duong_dan_tuong_doi: str) -> Path:
    """Chan viec truy cap file nam ngoai repo (vi du ../../.ssh/id_rsa)."""
    dich = (GOC_REPO / duong_dan_tuong_doi).resolve()
    if not dich.is_relative_to(GOC_REPO):
        raise ValueError("Chi duoc truy cap file nam trong thu muc du an.")
    return dich


def doc_file(duong_dan: str) -> str:
    """Doc noi dung mot file van ban trong repo, tra ve chuoi."""
    try:
        dich = _duong_dan_an_toan(duong_dan)
    except ValueError as loi:
        return f"Loi: {loi}"

    if not dich.is_file():
        return f"Loi: khong tim thay file {duong_dan}"

    noi_dung = dich.read_text(encoding="utf-8", errors="replace")
    if len(noi_dung) > GIOI_HAN_KY_TU:
        return noi_dung[:GIOI_HAN_KY_TU] + "\n... (da cat bot vi file qua dai)"
    return noi_dung


def liet_ke_file(thu_muc: str = ".") -> str:
    """Liet ke ten cac muc trong mot thu muc cua repo, moi ten mot dong."""
    try:
        dich = _duong_dan_an_toan(thu_muc)
    except ValueError as loi:
        return f"Loi: {loi}"

    if not dich.is_dir():
        return f"Loi: {thu_muc} khong phai thu muc"

    ten = sorted(
        muc.name + ("/" if muc.is_dir() else "")
        for muc in dich.iterdir()
        if not muc.name.startswith(".")
    )
    return "\n".join(ten) if ten else "(thu muc rong)"


@beta_tool
def tool_doc_file(duong_dan: str) -> str:
    """Doc noi dung mot file van ban trong thu muc du an.

    Args:
        duong_dan: Duong dan tuong doi tinh tu goc repo, vi du "docs/de-bai.md".
    """
    return doc_file(duong_dan)


@beta_tool
def tool_liet_ke_file(thu_muc: str = ".") -> str:
    """Liet ke ten cac file va thu muc con nam trong mot thu muc cua du an.

    Args:
        thu_muc: Duong dan tuong doi tinh tu goc repo. Mac dinh la goc repo.
    """
    return liet_ke_file(thu_muc)


DANH_SACH_TOOL = [tool_doc_file, tool_liet_ke_file]
