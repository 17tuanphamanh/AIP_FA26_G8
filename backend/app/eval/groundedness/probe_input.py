"""`probe-input`: `kb/eval/retrieval_set.yaml` → bộ câu cho `make probe` + `families.jsonl` cho `collect --from-probe` [Đề xuất 22/10 — P6 xác nhận].

- Chỉ câu `role: employee` (probe gửi bằng một người dùng thường). Dòng probe: `{"id": <id>, "kind": "intent", "text": <query>, "gold": <intent>}`.
- Họ = `expected_doc_ids[0]` — phần tử ĐẦU theo đúng thứ tự trong YAML (P8 v1.5 6.3.1, P6 chốt 22/10). Câu ÂM TÍNH (`expected_doc_ids` rỗng)
  có họ riêng = id của chính câu (mỗi câu một họ, KHÔNG gộp chung một họ "không có đáp án"). Mọi câu `employee` đều vào cả hai file.
- Chỉ đọc YAML, không import `app.rag`. Ghi file mới (`x`): không ghi đè.
"""

import json
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROBE_FILE = "probe.jsonl"
FAMILIES_FILE = "families.jsonl"


class _Item(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    intent: str = Field(min_length=1)
    role: str = Field(min_length=1)
    expected_doc_ids: list[str]
    near_topic: Any = None


class _Set(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, hide_input_in_errors=True)

    items: list[_Item] = Field(min_length=1)


def build_probe_input(path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, int]]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        parsed = _Set.model_validate(raw)
    except (yaml.YAMLError, ValidationError):
        raise ValueError(f"{path.name}: không đọc được bộ câu truy hồi (sai YAML hoặc sai khoá)") from None
    ids = [i.id for i in parsed.items]
    if len(set(ids)) != len(ids):
        raise ValueError(f"{path.name}: id trùng")
    probe: list[dict[str, str]] = []
    families: list[dict[str, str]] = []
    not_employee = own_family = 0
    for item in parsed.items:
        if item.role != "employee":
            not_employee += 1
            continue
        if item.expected_doc_ids:
            family = item.expected_doc_ids[0]
        else:
            family, own_family = item.id, own_family + 1
        probe.append({"id": item.id, "kind": "intent", "text": item.query, "gold": item.intent})
        families.append({"scenario_id": item.id, "family": family})
    report = {"n_items": len(parsed.items), "n_written": len(probe), "n_own_family": own_family,
              "n_not_employee_skipped": not_employee, "n_families": len({f["family"] for f in families})}  # fmt: skip
    return probe, families, report


def write_probe_input(out: Path, probe: list[dict[str, str]], families: list[dict[str, str]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in ((PROBE_FILE, probe), (FAMILIES_FILE, families)):
        with (out / name).open("x", encoding="utf-8", newline="\n") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
