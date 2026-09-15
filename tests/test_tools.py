"""Test cac tool - chay duoc ma khong can goi API."""

from agent.tools import doc_file, liet_ke_file


def test_doc_file_doc_duoc_file_co_that():
    noi_dung = doc_file("README.md")
    assert "AIP_FA26_G8" in noi_dung


def test_doc_file_bao_loi_khi_khong_co_file():
    assert doc_file("khong-ton-tai.md").startswith("Loi:")


def test_doc_file_chan_duong_dan_ra_ngoai_repo():
    ket_qua = doc_file("../../etc/passwd")
    assert ket_qua.startswith("Loi:")


def test_liet_ke_file_thay_thu_muc_agent():
    ket_qua = liet_ke_file(".")
    assert "agent/" in ket_qua.splitlines()


def test_liet_ke_file_bao_loi_khi_khong_phai_thu_muc():
    assert liet_ke_file("README.md").startswith("Loi:")
