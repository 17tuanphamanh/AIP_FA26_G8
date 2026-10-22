"""Mutation chặng F7 (API chính sách chỉ đọc, `backend/app/api/policy.py`). Mỗi đột biến áp lên file thật, chạy
`backend/tests/unit/test_policy_api.py`, khôi phục trong `finally`, so md5 + `git diff --stat` trước/sau. Luật N3 (`n3.py`):
file đích còn chữ `MUTATION` → dừng; mốc xanh một lần trước khi đột biến.

  uv run python scripts/mutation/mutate_f7.py                    # cả 9 mã (unit backend, không Docker, không LLM)
  uv run python scripts/mutation/mutate_f7.py --only M-F7-4

M-F7-4 làm validate GHI file: chỉ khi biến môi trường `CONFIG_DIR` có đặt (test dùng thư mục tạm của `fake_config`) — không bao
giờ đụng `config/policy.json` thật; cuối lượt vẫn so `git diff --stat` để chắc.
Dự đoán test đỏ ghi theo TIỀN TỐ tên test (`test_t08` khớp `test_t08_…`).
"""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import n3  # scripts/mutation/n3.py — cùng thư mục (sys.path[0] khi chạy script)

REPO = Path(__file__).resolve().parents[2]
POLICY = "backend/app/api/policy.py"
CMD = ["uv", "run", "pytest", "backend/tests/unit/test_policy_api.py", "-q", "-p", "no:cacheprovider"]


class Mutation(NamedTuple):
    name: str
    edits: list[tuple[str, str, str, int]]  # (file, chuỗi gốc, chuỗi thay, số lần chuỗi gốc phải xuất hiện)
    expect: list[str]  # tiền tố tên test PHẢI đỏ


def one(old: str, new: str, times: int = 1) -> tuple[str, str, str, int]:
    return (POLICY, old, new, times)


_MARK = 'POLICY_FILE = "policy.json"\n'  # dòng neo để gắn chữ MUTATION khi chuỗi thay không có chỗ cho chú thích
_READ = 'Depends(require("policy:read"))'
_EDIT = 'Depends(require("policy:edit"))'
_PARSE = "json.loads(raw, parse_constant=_no_nan) if raw else None"
_LOC = 'PolicyIssue(loc=list(e["loc"]), msg=e["msg"])'
_OK = "    if isinstance(body, ValidateIn) and not issues:\n"
_ITEM = "    return [item]\n"
_ITEM_MODEL = "response_model=list[PolicyVersionItem]"
_ITEM_RET = "-> list[PolicyVersionItem]:"
_CHECK = '            check_policy_config(policy.model_copy(update={"rules": (rule,)}), slots, metadata)\n'
_LOOP = "    for i, rule in enumerate(policy.rules):\n"
_LOG = '    log.info("policy validate: %d lỗi", len(issues))  # chỉ đếm — không nội dung, không msg\n'

_WRITES = (
    '    if isinstance(body, ValidateIn) and __import__("os").environ.get("CONFIG_DIR"):  # MUTATION M-F7-4: validate ghi file\n'
    "        (get_settings().config_dir / POLICY_FILE).write_text(json.dumps(body.content), encoding=\"utf-8\")\n"
    "        _policy_bytes.cache_clear()\n"
)

MUTATIONS_ALL: list[Mutation] = [
    Mutation("M-F7-1 GET /api/policy[/versions] chỉ cần đăng nhập",
             [one(_READ, "Depends(require())", 2), one(_MARK, _MARK.rstrip("\n") + "  # MUTATION M-F7-1\n")],
             ["test_t02", "test_t05"]),
    Mutation("M-F7-2 bỏ parse_constant (NaN lọt qua bước đọc thân)",
             [one(_PARSE, "json.loads(raw) if raw else None  # MUTATION M-F7-2")],
             ["test_t11"]),
    Mutation("M-F7-3 loc giữ tiền tố content",
             [one(_LOC, 'PolicyIssue(loc=["content", *e["loc"]], msg=e["msg"])  # MUTATION M-F7-3')],
             ["test_t07", "test_t08", "test_t12"]),  # T10 không đỏ: loc lỗi action do _config_issues tự dựng, không qua Pydantic
    Mutation("M-F7-4 validate hợp lệ thì ghi file + xoá cache",
             [one(_OK, _WRITES + _OK)],
             ["test_t15"]),
    Mutation("M-F7-5 /versions trả {items: [...]} thay mảng trần",
             [one(_ITEM, '    return {"items": [item]}  # MUTATION M-F7-5\n'),
              one(_ITEM_MODEL, "response_model=dict[str, list[PolicyVersionItem]]"),
              one(_ITEM_RET, "-> dict[str, list[PolicyVersionItem]]:")],
             ["test_t04"]),
    Mutation("M-F7-6 validate chỉ cần đăng nhập",
             [one(_EDIT, "Depends(require())"), one(_MARK, _MARK.rstrip("\n") + "  # MUTATION M-F7-6\n")],
             ["test_t14"]),
    Mutation("M-F7-7 bỏ check_policy_config (action sai intent lọt)",
             [one(_CHECK, "            pass  # MUTATION M-F7-7\n")],
             ["test_t10", "test_t21"]),
    Mutation("M-F7-8 kiểm từng luật bỏ qua luật cuối",
             [one(_LOOP, "    for i, rule in enumerate(policy.rules[:-1]):  # MUTATION M-F7-8\n")],
             ["test_t21"]),
    Mutation("M-F7-9 log cả thân request",
             [one(_LOG, '    log.info("policy validate: %s", body)  # MUTATION M-F7-9\n')],
             ["test_t22"]),
]  # fmt: skip

MUTATIONS = MUTATIONS_ALL
if "--only" in sys.argv:
    prefix = sys.argv[sys.argv.index("--only") + 1]
    MUTATIONS = [m for m in MUTATIONS_ALL if m.name.startswith(prefix)]


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def git_diff_stat() -> str:
    return subprocess.run(["git", "diff", "--stat"], cwd=REPO, capture_output=True, text=True, check=False).stdout


def _hit(prefix: str, failed: list[str]) -> bool:
    return any(f.split("::")[-1].startswith(prefix) for f in failed)


def main() -> int:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    files = sorted({rel for m in MUTATIONS for rel, *_ in m.edits})
    stop = n3.guard(REPO, files, [CMD], env)  # N3: không dấu sót, mốc xanh
    if stop is not None:
        return stop
    before = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 trước  {before[rel]}  {rel}")
    diff_before = git_diff_stat()
    bad = 0
    for m in MUTATIONS:
        originals = {rel: (REPO / rel).read_text(encoding="utf-8") for rel, *_ in m.edits}
        mutated = dict(originals)
        wrong = []
        for rel, old, new, n in m.edits:
            if mutated[rel].count(old) != n:
                wrong.append(f"{rel}: {mutated[rel].count(old)}/{n}")
            mutated[rel] = mutated[rel].replace(old, new)
        if wrong:
            print(f"!! {m.name}: chuỗi gốc không khớp số lần {wrong} — bỏ qua")
            bad += 1
            continue
        unmarked = [rel for rel, text in mutated.items() if n3.MARK not in text]
        if unmarked:
            print(f"!! {m.name}: file đột biến thiếu chữ {n3.MARK!r} {unmarked} — bỏ qua (N3a không bắt được nếu bị giết)")
            bad += 1
            continue
        try:
            for rel, text in mutated.items():
                (REPO / rel).write_text(text, encoding="utf-8")
            out = subprocess.run(CMD, cwd=REPO, env=env, capture_output=True, text=True, timeout=1800, check=False)
        finally:
            for rel, text in originals.items():
                (REPO / rel).write_text(text, encoding="utf-8")
        failed = sorted(set(re.findall(r"^FAILED (\S+?::\w+(?:\[.*?\])?)(?: - |$)", out.stdout, re.MULTILINE)))
        errors = re.findall(r"^ERROR (\S+)", out.stdout, re.MULTILINE)
        missing = [e for e in m.expect if not _hit(e, failed)]
        status = "ĐỎ đúng dự đoán" if not missing else ("ĐỎ (khác dự đoán)" if failed else "SỐNG")
        bad += bool(missing)
        print(f"{m.name}: {status} — {len(failed)} test đỏ{'; lỗi thu thập: ' + str(errors) if errors else ''}")
        for f in failed:
            print(f"    {f}")
        if missing:
            print(f"    thiếu test dự đoán: {missing}")
            print("    " + "\n    ".join(out.stdout.strip().splitlines()[-5:]))
    after = {rel: md5(REPO / rel) for rel in files}
    for rel in files:
        print(f"md5 sau    {after[rel]}  {rel}")
    assert after == before, "md5 khác sau khôi phục!"
    print("md5 sau khôi phục: khớp")
    assert git_diff_stat() == diff_before, "git diff --stat khác lúc đầu!"
    print("git diff --stat: khớp lúc đầu")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
