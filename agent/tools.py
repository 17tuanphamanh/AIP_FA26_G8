"""Tools the agent is allowed to call.

Every tool comes in two layers:
  - a plain Python function (read_file, list_files) — callable directly and testable;
  - a @beta_tool wrapper (tool_read_file, ...) — the thing handed to Claude.

The wrapper's docstring is what Claude reads to decide when to call the tool, so
write it carefully. The SDK derives the parameter schema from the type hints.

Adding a tool: write the plain function, write the @beta_tool wrapper, append to TOOLS.
"""

from pathlib import Path

from anthropic import beta_tool

from agent.config import REPO_ROOT

# Cap on characters read from a single file, so one file cannot fill the context window.
CHAR_LIMIT = 20_000


def _safe_path(relative_path: str) -> Path:
    """Block access to files outside the repo (e.g. ../../.ssh/id_rsa)."""
    target = (REPO_ROOT / relative_path).resolve()
    if not target.is_relative_to(REPO_ROOT):
        raise ValueError("Chỉ được truy cập file nằm trong thư mục dự án.")
    return target


def read_file(path: str) -> str:
    """Read a text file inside the repo and return its contents."""
    try:
        target = _safe_path(path)
    except ValueError as err:
        return f"Lỗi: {err}"

    if not target.is_file():
        return f"Lỗi: không tìm thấy file {path}"

    content = target.read_text(encoding="utf-8", errors="replace")
    if len(content) > CHAR_LIMIT:
        return content[:CHAR_LIMIT] + "\n... (đã cắt bớt vì file quá dài)"
    return content


def list_files(directory: str = ".") -> str:
    """List the entries of a directory in the repo, one name per line."""
    try:
        target = _safe_path(directory)
    except ValueError as err:
        return f"Lỗi: {err}"

    if not target.is_dir():
        return f"Lỗi: {directory} không phải thư mục"

    names = sorted(
        entry.name + ("/" if entry.is_dir() else "")
        for entry in target.iterdir()
        if not entry.name.startswith(".")
    )
    return "\n".join(names) if names else "(thư mục rỗng)"


@beta_tool
def tool_read_file(path: str) -> str:
    """Read a text file inside the project directory.

    Args:
        path: Path relative to the repo root, e.g. "docs/de-bai.md".
    """
    return read_file(path)


@beta_tool
def tool_list_files(directory: str = ".") -> str:
    """List the files and sub-directories inside a directory of the project.

    Args:
        directory: Path relative to the repo root. Defaults to the repo root.
    """
    return list_files(directory)


TOOLS = [tool_read_file, tool_list_files]
