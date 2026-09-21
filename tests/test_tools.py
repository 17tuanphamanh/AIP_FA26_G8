"""Tests for the tools — runnable without any API call."""

from agent.tools import list_files, read_file


def test_read_file_reads_an_existing_file():
    content = read_file("README.md")
    assert "AIP_FA26_G8" in content


def test_read_file_reports_a_missing_file():
    assert read_file("khong-ton-tai.md").startswith("Lỗi:")


def test_read_file_rejects_a_path_outside_the_repo():
    result = read_file("../../etc/passwd")
    assert result.startswith("Lỗi:")


def test_list_files_sees_the_agent_directory():
    result = list_files(".")
    assert "agent/" in result.splitlines()


def test_list_files_reports_a_non_directory():
    assert list_files("README.md").startswith("Lỗi:")
