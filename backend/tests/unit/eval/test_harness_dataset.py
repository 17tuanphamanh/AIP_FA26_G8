"""G2 mốc 1 — nạp kịch bản (`app.eval.dataset`) + cấu hình lượt chạy / `run_id` (`app.eval.config`) — P8 §4.1, §5.1.

Chỉ kịch bản TỔNG HỢP viết vào `tmp_path`. Thông điệp lỗi mặc định nêu `file #i/N` + vị trí trường — KHÔNG tên file, KHÔNG giá
trị: mọi giá trị và tên file tổng hợp chứa chuỗi canh `SENTINEL_` để test bắt được khi bị vọng lại. Tên file chỉ hiện khi
`render(show_name=True)` (cờ `--per-case`, Dương 19/10).
"""

import typing
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.db.models import P_METHODS
from app.eval.config import (
    ProbMethod,
    RunConfig,
    RunIdMismatch,
    StackStrategy,
    check_run_id,
    make_run_id,
)
from app.eval.dataset import DatasetError, Scenario, load_scenarios
from app.eval.predictions import Strategy
from pydantic import ValidationError

SENTINEL = "SENTINEL_"


def scenario(**over: Any) -> dict[str, Any]:
    """Một kịch bản đơn ý tổng hợp hợp lệ."""
    base: dict[str, Any] = {
        "id": "SENTINEL_ID_1", "family": "SENTINEL_FAM_1", "requester": "SENTINEL_USER",
        "turns": ["SENTINEL_TXT_mo dau", {"text": "SENTINEL_TXT_tra loi", "on_confirm": False}],
        "gold": {"intents": ["vpn"], "expected_route": "HITL", "approver_decision": "approve",
                 "gold_doc_ids": ["SENTINEL_DOC"]},
    }  # fmt: skip
    base.update(over)
    return base


def write(d: Path, name: str, data: Any) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def assert_no_sentinel(exc: BaseException) -> None:
    assert SENTINEL not in str(exc)


def fails(directory: Path, **kw: Any) -> DatasetError:
    """Nạp phải ném `DatasetError`; thông điệp mặc định không có chuỗi canh (giá trị lẫn tên file)."""
    with pytest.raises(DatasetError) as e:
        load_scenarios(directory, **kw)
    assert_no_sentinel(e.value)
    assert all(SENTINEL not in line for line in e.value.render())
    return e.value


# ---- dataset ---------------------------------------------------------------------------------------------------------


def test_dataset_load_ok(tmp_path: Path) -> None:
    write(tmp_path, "b.yaml", scenario(id="SENTINEL_ID_2"))
    write(tmp_path, "a.yaml", scenario())
    ds = load_scenarios(tmp_path)
    assert ds.ignored_fields == ()
    assert [s.id for s in ds.scenarios] == ["SENTINEL_ID_1", "SENTINEL_ID_2"]  # sắp theo tên file
    s = ds.scenarios[0]
    assert [t.text for t in s.turns] == ["SENTINEL_TXT_mo dau", "SENTINEL_TXT_tra loi"]
    assert [t.on_confirm for t in s.turns] == [None, False]
    assert s.gold.expected_route == "HITL"
    assert s.gold.gold_doc_ids == ("SENTINEL_DOC",)
    assert s.gold.hidden_factor is False
    assert s.gold_intent == "vpn"


def test_dataset_list_file(tmp_path: Path) -> None:
    write(tmp_path, "many.yaml", [scenario(), scenario(id="SENTINEL_ID_2")])
    assert len(load_scenarios(tmp_path).scenarios) == 2


def test_dataset_yml_suffix_and_other_files_ignored(tmp_path: Path) -> None:
    write(tmp_path, "a.yml", scenario())
    (tmp_path / "README.md").write_text("SENTINEL_TXT", encoding="utf-8")
    assert len(load_scenarios(tmp_path).scenarios) == 1


@pytest.mark.parametrize("field", ["id", "family", "requester", "turns", "gold"])
def test_dataset_missing_field(tmp_path: Path, field: str) -> None:
    data = scenario()
    del data[field]
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    err = fails(tmp_path)
    assert err.render() == [f"file #1/1: không hợp lệ ({field})"]


def test_dataset_extra_field(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(bogus="SENTINEL_TXT_x"))
    assert fails(tmp_path).render() == ["file #1/1: không hợp lệ (bogus)"]


def test_dataset_extra_gold_field(tmp_path: Path) -> None:
    data = scenario()
    data["gold"]["bogus"] = "SENTINEL_TXT_x"
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    assert fails(tmp_path).render() == ["file #1/1: không hợp lệ (gold.bogus)"]


def test_load_error_hides_file_name(tmp_path: Path) -> None:
    """Dương 19/10: mặc định `file #i/N` — tên file (có thể lộ thẻ/họ) chỉ hiện với `show_name=True` (`--per-case`)."""
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario())
    write(tmp_path, "SENTINEL_FILE_b.yaml", scenario(id="SENTINEL_ID_2", bogus=1))
    err = fails(tmp_path)
    assert "SENTINEL_FILE" not in str(err)
    assert err.render() == ["file #2/2: không hợp lệ (bogus)"]
    assert err.render(show_name=True) == ["SENTINEL_FILE_b.yaml: không hợp lệ (bogus)"]


def test_load_collects_all_errors(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(family=None))
    write(tmp_path, "SENTINEL_FILE_b.yaml", scenario(id="SENTINEL_ID_2"))
    write(tmp_path, "SENTINEL_FILE_c.yaml", scenario(id="SENTINEL_ID_3", requester=None))
    err = fails(tmp_path)
    assert err.loaded == 1
    assert err.render() == ["file #1/3: không hợp lệ (family)", "file #3/3: không hợp lệ (requester)"]


def test_allow_extra_fields_records_paths(tmp_path: Path) -> None:
    """Cờ `--allow-extra-fields`: bỏ trường lạ, ghi ĐƯỜNG DẪN (chỉ số danh sách → `*`), không giá trị."""
    data = scenario(bogus="SENTINEL_TXT_x")
    data["gold"]["leaves"] = ["SENTINEL_TXT_y"]
    data["turns"][1]["extra_key"] = "SENTINEL_TXT_z"
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    write(tmp_path, "SENTINEL_FILE_b.yaml", scenario(id="SENTINEL_ID_2", bogus=2))
    ds = load_scenarios(tmp_path, allow_extra=True)
    assert len(ds.scenarios) == 2
    assert sorted(ds.ignored_fields) == ["bogus", "bogus", "gold.leaves", "turns.*.extra_key"]
    assert all(SENTINEL not in f for f in ds.ignored_fields)


def test_allow_extra_fields_other_errors_still_fail(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(bogus=1, family=None))
    err = fails(tmp_path, allow_extra=True)
    assert err.render() == ["file #1/1: không hợp lệ (family)"]


@pytest.mark.parametrize(("path", "value"), [
    (("gold", "expected_route"), "SENTINEL_ROUTE"),
    (("gold", "approver_decision"), "SENTINEL_DEC"),
    (("gold", "intents"), []),
    (("turns",), []),
    (("turns",), ["x" * 4001]),
])  # fmt: skip
def test_dataset_bad_value_not_echoed(tmp_path: Path, path: tuple[str, ...], value: Any) -> None:
    data = scenario()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    err = fails(tmp_path)
    assert err.render()[0].startswith("file #1/1: không hợp lệ (")
    assert "x" * 50 not in str(err)


def test_dataset_list_position_in_error(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_many.yaml", [scenario(), scenario(id="SENTINEL_ID_2", family=None)])
    err = fails(tmp_path)
    assert err.render() == ["file #1/1[1]: không hợp lệ (family)"]
    assert err.loaded == 1


def test_dataset_duplicate_id(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario())
    write(tmp_path, "SENTINEL_FILE_b.yaml", scenario())
    assert fails(tmp_path).render() == ["file #2/2: id kịch bản trùng với kịch bản trước"]


def test_dataset_yaml_error_not_echoed(tmp_path: Path) -> None:
    tmp_path.joinpath("SENTINEL_FILE_a.yaml").write_text("id: SENTINEL_ID\n  bad: [SENTINEL_TXT\n", encoding="utf-8")
    [line] = fails(tmp_path).render()
    assert line.startswith("file #1/1: YAML lỗi dòng ")


@pytest.mark.parametrize("content", ["", "SENTINEL_TXT_chuoi\n", "42\n"])
def test_dataset_not_mapping(tmp_path: Path, content: str) -> None:
    tmp_path.joinpath("SENTINEL_FILE_a.yaml").write_text(content, encoding="utf-8")
    assert fails(tmp_path).render() == ["file #1/1: phải là một kịch bản (mapping) hoặc danh sách kịch bản"]


def test_dataset_empty_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="không có file kịch bản"):
        load_scenarios(tmp_path)


def test_dataset_not_a_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="không phải thư mục"):
        load_scenarios(tmp_path / "khong-co")


def test_dataset_sha_stable(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, "x.yaml", scenario())
    write(a, "y.yaml", scenario(id="SENTINEL_ID_2"))
    write(b, "y.yaml", scenario(id="SENTINEL_ID_2"))  # tạo theo thứ tự ngược
    write(b, "x.yaml", scenario())
    sha = load_scenarios(a).sha256
    assert len(sha) == 64 and sha == load_scenarios(b).sha256
    p = b / "x.yaml"
    p.write_bytes(p.read_bytes() + b"\n")  # 1 byte khác, nội dung YAML vẫn như cũ
    assert load_scenarios(b).sha256 != sha


def test_dataset_sha_depends_on_name(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, "x.yaml", scenario())
    write(b, "z.yaml", scenario())
    assert load_scenarios(a).sha256 != load_scenarios(b).sha256


def test_gold_intent_multi_is_none() -> None:
    """TODO(G2-Q12): nhiều ý → `gold_intent` None (lá nhiều ý không vào predictions v1)."""
    s = Scenario.model_validate(scenario(gold={"intents": ["vpn", "account"], "expected_route": "AUTO"}))
    assert s.gold_intent is None


def test_scenario_frozen() -> None:
    s = Scenario.model_validate(scenario())
    with pytest.raises(ValidationError):
        s.id = "khac"  # type: ignore[misc]


# ---- config / run_id -------------------------------------------------------------------------------------------------


def cfg(**over: Any) -> RunConfig:
    base: dict[str, Any] = {"strategy": "hybrid", "split": "test", "timeout_s": 300, "prob_method": "self_report",
                            "llm_roles": {"fast": "m-fast", "strong": "m-strong"}}  # fmt: skip
    base.update(over)
    return RunConfig.model_validate(base)


def test_stack_strategy_subset() -> None:
    """P8 §5.1: lượt stack chỉ hybrid / llm_only; phải nằm trong `Strategy` của hợp đồng."""
    assert set(typing.get_args(StackStrategy)) == {"hybrid", "llm_only"}
    assert set(typing.get_args(StackStrategy)) <= set(typing.get_args(Strategy))


def test_prob_method_matches_db() -> None:
    assert typing.get_args(ProbMethod) == P_METHODS


@pytest.mark.parametrize("strategy", ["rule_only", "manual", "full_auto", "hybrid_guarded"])
def test_config_strategy_rejects(strategy: str) -> None:
    with pytest.raises(ValidationError):
        cfg(strategy=strategy)


@pytest.mark.parametrize("timeout", [0, -1])
def test_config_timeout_positive(timeout: int) -> None:
    with pytest.raises(ValidationError):
        cfg(timeout_s=timeout)


def test_config_defaults() -> None:
    c = cfg()
    assert c.seed == 20260925 and c.enable_proactive_diagnosis is True


def test_run_id_deterministic() -> None:
    rid = make_run_id(cfg(), "a" * 64, "c0ffee")
    assert len(rid) == 12 and all(ch in "0123456789abcdef" for ch in rid)
    assert make_run_id(cfg(), "a" * 64, "c0ffee") == rid
    # thứ tự khoá của dict không đổi run_id
    assert make_run_id(cfg(llm_roles={"strong": "m-strong", "fast": "m-fast"}), "a" * 64, "c0ffee") == rid


@pytest.mark.parametrize("change", [
    {"config": {"strategy": "llm_only"}}, {"config": {"timeout_s": 301}}, {"config": {"split": "calibration"}},
    {"config": {"enable_proactive_diagnosis": False}}, {"config": {"llm_roles": {"fast": "khac"}}},
    {"sha": "b" * 64}, {"commit": "deadbe"},
])  # fmt: skip
def test_run_id_changes(change: dict[str, Any]) -> None:
    base = make_run_id(cfg(), "a" * 64, "c0ffee")
    other = make_run_id(cfg(**change.get("config", {})), change.get("sha", "a" * 64), change.get("commit", "c0ffee"))
    assert other != base


def test_check_run_id() -> None:
    rid = make_run_id(cfg(), "a" * 64, "c0ffee")
    check_run_id(None, rid)
    check_run_id(rid, rid)
    with pytest.raises(RunIdMismatch) as e:
        check_run_id("0" * 12, rid)
    assert isinstance(e.value, ValueError)
