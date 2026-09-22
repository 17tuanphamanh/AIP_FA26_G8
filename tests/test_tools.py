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


def test_read_file_refuses_the_env_file():
    """.env sits inside the repo, so the "stay inside the repo" check misses it."""
    assert read_file(".env").startswith("Lỗi: Không được phép")


def test_refusing_a_secret_does_not_reveal_whether_it_exists():
    """Same message either way — .env is absent here, .gitignore says it may appear."""
    assert read_file(".env") == read_file(".env.local")


def test_read_file_still_allows_the_public_sample():
    assert "ANTHROPIC_API_KEY" in read_file(".env.example")


def test_read_file_refuses_the_git_directory():
    assert read_file(".git/config").startswith("Lỗi: Không được phép")


def test_read_file_refuses_key_and_secrets_paths():
    assert read_file("private.key").startswith("Lỗi: Không được phép")
    assert read_file("secrets/token.txt").startswith("Lỗi: Không được phép")


def test_list_files_refuses_the_git_directory():
    assert list_files(".git").startswith("Lỗi: Không được phép")
