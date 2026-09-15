"""Test phan cau hinh - khong goi API that."""

import pytest

from agent.config import MODEL_MAC_DINH, CauHinh, doc_prompt


def test_thieu_api_key_thi_bao_loi_ro_rang(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        CauHinh.tu_moi_truong()


def test_doc_duoc_cau_hinh_tu_bien_moi_truong(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-gia-lap")
    monkeypatch.delenv("MODEL", raising=False)
    cau_hinh = CauHinh.tu_moi_truong()
    assert cau_hinh.api_key == "sk-ant-gia-lap"
    assert cau_hinh.model == MODEL_MAC_DINH


def test_co_file_system_prompt():
    assert "AIP_FA26_G8" in doc_prompt("system.md")
