"""G2 — nạp kịch bản (`app.eval.dataset`) theo CẤU TRÚC THẬT (`~/m9-notes/g2-chot.md:11-17`, chỉ tên trường + kiểu) + cấu hình lượt
chạy / `run_id` (`app.eval.config`) — P8 §5.1.

Chỉ kịch bản TỔNG HỢP viết vào `tmp_path` (`fake_stack.real_scenario`). Thông điệp lỗi mặc định nêu `file #i/N` + vị trí trường — KHÔNG
tên file, KHÔNG giá trị: mọi giá trị và tên file tổng hợp chứa chuỗi canh `SENTINEL_`. Tên file chỉ hiện khi `render(show_name=True)`
(cờ `--per-case`).
"""

import json
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
from app.eval.dataset import (
    SLOTS,
    Confirm,
    DatasetError,
    Reply,
    Scenario,
    load_scenarios,
    load_seed_users,
)
from app.eval.predictions import Strategy
from pydantic import ValidationError
from tests.unit.eval.fake_stack import (
    SEED_USERS,
    confirm,
    real_scenario,
    reply,
    write_seed,
)

SENTINEL = "SENTINEL_"
REPO = Path(__file__).resolve().parents[4]


def scenario(**over: Any) -> dict[str, Any]:
    """Kịch bản tổng hợp đủ khoá thật: câu đầu + 1 câu trả lời + 1 bước xác nhận; chưa nhãn (expected_route null)."""
    data = real_scenario(turns=["SENTINEL_TXT_mo dau", reply("SENTINEL_TXT_tra loi"), confirm(False)])
    data.update(over)
    return data


def write(d: Path, name: str, data: Any) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def load(directory: Path, **kw: Any) -> Any:
    return load_scenarios(directory, users=SEED_USERS, **kw)


def assert_no_sentinel(exc: BaseException) -> None:
    assert SENTINEL not in str(exc)


def fails(directory: Path, **kw: Any) -> DatasetError:
    """Nạp phải ném `DatasetError`; thông điệp mặc định không có chuỗi canh (giá trị lẫn tên file)."""
    with pytest.raises(DatasetError) as e:
        load(directory, **kw)
    assert_no_sentinel(e.value)
    assert all(SENTINEL not in line for line in e.value.render())
    return e.value


def at(data: dict[str, Any], path: tuple[str, ...]) -> dict[str, Any]:
    node = data
    for key in path:
        node = node[key]
    return node


# ---- cấu trúc thật ---------------------------------------------------------------------------------------------------


def test_dataset_load_ok(tmp_path: Path) -> None:
    write(tmp_path, "b.yaml", scenario(id="SENTINEL_ID_2"))
    write(tmp_path, "a.yaml", scenario())
    ds = load(tmp_path)
    assert ds.ignored_fields == ()
    assert [s.id for s in ds.scenarios] == ["SENTINEL_ID_1", "SENTINEL_ID_2"]  # sắp theo tên file
    s = ds.scenarios[0]
    assert s.opening == "SENTINEL_TXT_mo dau"
    assert isinstance(s.turns[1], Reply) and (s.turns[1].on_question_about, s.turns[1].reply) == ("device_id", "SENTINEL_TXT_tra loi")
    assert isinstance(s.turns[2], Confirm) and s.turns[2].on_confirm is False
    assert (s.replies, s.confirms) == (("SENTINEL_TXT_tra loi",), (False,))
    assert (s.requester.user_id, s.requester.role, s.requester.dept, s.requester.tenure_days) == (
        "u_sentinel", "employee", "SENTINEL_DEPT", 400)  # fmt: skip
    assert ds.usernames == {"SENTINEL_ID_1": "SENTINEL_USER", "SENTINEL_ID_2": "SENTINEL_USER"}
    assert (s.source, s.at, s.faults) == ("SENTINEL_SRC", "2026-10-20T09:00:00+07:00", ())
    assert (s.labels.annotator_1, s.labels.annotator_2) == (None, None)
    g = s.gold
    assert (g.need_type, g.expected_route, g.expected_exit, g.approver_decision) == ("SENTINEL_NEED", None, None, "approve")
    assert (g.action.type, g.action.target, g.action.requested_for) == ("SENTINEL_ACT", "SENTINEL_TGT", "SENTINEL_FOR")
    assert g.action.params == {"p": "SENTINEL_P", "n": 1} and g.facts == {"f": "SENTINEL_FACT", "b": True}
    assert g.gold_doc_ids == ("SENTINEL_DOC",)
    assert s.gold_intent == "vpn"
    assert s.labelled is False


def test_real_shape_variants(tmp_path: Path) -> None:
    """Đủ biến thể của cấu trúc thật: đã nhãn / chưa nhãn, chỉ câu đầu, nhiều reply + confirm, expected_exit có giá trị."""
    write(tmp_path, "a.yaml", real_scenario("SENTINEL_ID_A", expected_route="HITL", expected_exit="E5"))
    write(tmp_path, "b.yaml", real_scenario("SENTINEL_ID_B", turns=["SENTINEL_TXT_b", reply("x1", "account_type"),
                                                                     confirm(True), reply("x2", "duration")]))  # fmt: skip
    write(tmp_path, "c.yaml", real_scenario("SENTINEL_ID_C", user_id="u_an", decision="ignore", intents=("vpn", "account")))
    a, b, c = load(tmp_path).scenarios
    assert (a.labelled, a.gold.expected_route, a.gold.expected_exit) == (True, "HITL", "E5")
    assert (b.replies, b.confirms) == (("x1", "x2"), (True,))
    assert (c.gold.approver_decision, c.gold_intent) == ("ignore", None)


def test_slots_exact() -> None:
    assert set(SLOTS) == {"account_type", "permission_level", "resource_path", "duration", "device_id", "software_name",
                          "action", "target_corrected"}  # fmt: skip


@pytest.mark.parametrize("field", ["id", "family", "source", "at", "faults", "requester", "turns", "gold", "labels"])
def test_dataset_missing_field(tmp_path: Path, field: str) -> None:
    data = scenario()
    del data[field]
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    assert fails(tmp_path).render() == [f"file #1/1: không hợp lệ ({field})"]


@pytest.mark.parametrize(("path", "field"), [
    *((("requester",), f) for f in ("user_id", "role", "dept", "tenure_days")),
    *((("gold",), f) for f in ("intents", "need_type", "expected_route", "expected_exit", "approver_decision", "gold_doc_ids",
                               "action", "facts")),
    *((("gold", "action"), f) for f in ("type", "target")),  # `requested_for`, `params` không bắt buộc (#58, D-41)
    *((("labels",), f) for f in ("annotator_1", "annotator_2")),
])  # fmt: skip
def test_dataset_missing_nested_field(tmp_path: Path, path: tuple[str, ...], field: str) -> None:
    data = scenario()
    del at(data, path)[field]
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    assert fails(tmp_path).render() == [f"file #1/1: không hợp lệ ({'.'.join((*path, field))})"]


@pytest.mark.parametrize("path", [(), ("requester",), ("gold",), ("gold", "action"), ("labels",)])
def test_extra_forbidden(tmp_path: Path, path: tuple[str, ...]) -> None:
    data = scenario()
    at(data, path)["bogus"] = "SENTINEL_TXT_x"
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    assert fails(tmp_path).render() == [f"file #1/1: không hợp lệ ({'.'.join((*path, 'bogus'))})"]


def test_gold_hidden_factor_not_in_schema(tmp_path: Path) -> None:
    """Chỉ đúng các khoá của cấu trúc thật — `hidden_factor` để PR hợp đồng v1.1 (Dương 20/10)."""
    data = scenario()
    data["gold"]["hidden_factor"] = False
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    assert fails(tmp_path).render() == ["file #1/1: không hợp lệ (gold.hidden_factor)"]


def test_params_facts_free_dict(tmp_path: Path) -> None:
    data = scenario()
    data["gold"]["action"]["params"] = {"SENTINEL_K": {"nested": [1, 2]}, "x": None}
    data["gold"]["facts"] = {}
    write(tmp_path, "a.yaml", data)
    [s] = load(tmp_path).scenarios
    assert s.gold.action.params == {"SENTINEL_K": {"nested": [1, 2]}, "x": None} and s.gold.facts == {}


# ---- khoá không bắt buộc / null (#58, --check-only 22/10) ------------------------------------------------------------


def test_requested_for_missing_is_requester(tmp_path: Path) -> None:
    """D-41: vắng `gold.action.requested_for` → người gửi = `requester.user_id` của TỪNG kịch bản — cùng không gian id với giá trị có
    sẵn trong dữ liệu (user_id, Tuấn Anh 22/10), KHÔNG tra username (seed map sang username khác → phân biệt được)."""
    write(tmp_path, "a.yaml", real_scenario("SENTINEL_ID_A", drop_action=("requested_for",)))
    write(tmp_path, "b.yaml", real_scenario("SENTINEL_ID_B", user_id="u_an", drop_action=("requested_for",)))
    ds = load(tmp_path)
    a, b = ds.scenarios
    assert a.gold.action.requested_for is None and b.gold.action.requested_for is None
    assert (ds.requested_for(a), ds.requested_for(b)) == ("u_sentinel", "u_an")


def test_params_missing_is_empty(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", real_scenario("SENTINEL_ID_A", drop_action=("params",)))
    write(tmp_path, "b.yaml", real_scenario("SENTINEL_ID_B", drop_action=("requested_for", "params")))  # như dữ liệu thật
    ds = load(tmp_path)
    a, b = ds.scenarios
    assert a.gold.action.params == {} and b.gold.action.params == {}
    assert a.gold.action.params is not b.gold.action.params
    assert ds.requested_for(a) == "SENTINEL_FOR" and ds.requested_for(b) == "u_sentinel"


def test_requested_for_params_present_kept(tmp_path: Path) -> None:
    """Có khoá → giữ nguyên; `requested_for: null` TƯỜNG MINH ≠ vắng khoá → giữ `None` (#58-Q2)."""
    write(tmp_path, "a.yaml", real_scenario("SENTINEL_ID_A"))
    null_for = real_scenario("SENTINEL_ID_B")
    null_for["gold"]["action"]["requested_for"] = None
    write(tmp_path, "b.yaml", null_for)
    ds = load(tmp_path)
    a, b = ds.scenarios
    assert ds.requested_for(a) == "SENTINEL_FOR" and a.gold.action.params == {"p": "SENTINEL_P", "n": 1}
    assert ds.requested_for(b) is None


def test_params_null_still_error(tmp_path: Path) -> None:
    """Chỉ VẮNG khoá mới thành `{}`; `params: null` vẫn sai kiểu."""
    data = scenario()
    data["gold"]["action"]["params"] = None
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    assert fails(tmp_path).render() == ["file #1/1: không hợp lệ (gold.action.params)"]


def test_approver_decision_null_loads(tmp_path: Path) -> None:
    """Họ không có bước duyệt (luật cấm) mang `approver_decision: null` → nạp được; THIẾU khoá vẫn lỗi
    (`test_dataset_missing_nested_field`)."""
    write(tmp_path, "a.yaml", real_scenario(decision=None))
    [s] = load(tmp_path).scenarios
    assert s.gold.approver_decision is None


@pytest.mark.parametrize(("path", "field", "value"), [
    (("gold", "action"), "params", ["SENTINEL_TXT_list"]),
    (("gold",), "facts", "SENTINEL_TXT_str"),
    (("requester",), "tenure_days", "SENTINEL_TXT_nan"),
    ((), "faults", "SENTINEL_TXT_str"),
])  # fmt: skip
def test_wrong_types(tmp_path: Path, path: tuple[str, ...], field: str, value: Any) -> None:
    data = scenario()
    at(data, path)[field] = value
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    [line] = fails(tmp_path).render()
    assert line.startswith(f"file #1/1: không hợp lệ ({'.'.join((*path, field))}")


def test_expected_route_null_unlabelled(tmp_path: Path) -> None:
    write(tmp_path, "a.yaml", scenario())
    write(tmp_path, "b.yaml", real_scenario("SENTINEL_ID_2", expected_route="ESCALATE_L2"))
    a, b = load(tmp_path).scenarios
    assert (a.gold.expected_route, a.labelled) == (None, False)
    assert (b.gold.expected_route, b.labelled) == ("ESCALATE_L2", True)


# ---- turns -----------------------------------------------------------------------------------------------------------


def test_turn0_must_be_str(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(turns=[reply("SENTINEL_TXT_r")]))
    assert fails(tmp_path).render() == ["file #1/1: không hợp lệ (turns)"]


def test_str_turn_after_first_rejected(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(turns=["SENTINEL_TXT_a", "SENTINEL_TXT_b"]))
    assert fails(tmp_path).render() == ["file #1/1: không hợp lệ (turns)"]


def test_reply_bad_slot(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(turns=["SENTINEL_TXT_a", reply("SENTINEL_TXT_r", "SENTINEL_SLOT")]))
    assert fails(tmp_path).render() == ["file #1/1: không hợp lệ (turns.1.on_question_about)"]


@pytest.mark.parametrize(("turn", "loc"), [
    ({"on_question_about": "device_id", "reply": "SENTINEL_TXT_r", "bogus": 1}, "turns.1.bogus"),
    ({"on_confirm": True, "bogus": 1}, "turns.1.bogus"),
    ({"on_question_about": "device_id"}, "turns.1.reply"),
    ({"reply": "SENTINEL_TXT_r"}, "turns.1.on_question_about"),
    ({"on_confirm": "SENTINEL_TXT_yes"}, "turns.1.on_confirm"),
    ({"on_question_about": "device_id", "reply": "x" * 4001}, "turns.1.reply"),
])  # fmt: skip
def test_turn_object_errors(tmp_path: Path, turn: dict[str, Any], loc: str) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(turns=["SENTINEL_TXT_a", turn]))
    assert fails(tmp_path).render() == [f"file #1/1: không hợp lệ ({loc})"]


@pytest.mark.parametrize("turns", [[], ["x" * 4001]])
def test_turns_empty_or_too_long(tmp_path: Path, turns: list[Any]) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(turns=turns))
    [line] = fails(tmp_path).render()
    assert line.startswith("file #1/1: không hợp lệ (turns") and "x" * 50 not in line


# ---- requester ↔ seed ------------------------------------------------------------------------------------------------


def test_requester_unknown_user_id(tmp_path: Path) -> None:
    data = scenario()
    data["requester"]["user_id"] = "SENTINEL_UID_khong_co"
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    write(tmp_path, "SENTINEL_FILE_b.yaml", scenario(id="SENTINEL_ID_2"))
    err = fails(tmp_path)
    assert err.render() == ["file #1/2: requester.user_id không có trong seed"]
    assert err.loaded == 1


def test_load_seed_users(tmp_path: Path) -> None:
    assert load_seed_users(write_seed(tmp_path / "seed.json")) == dict(SEED_USERS)


@pytest.mark.parametrize("content", [None, "{not json", json.dumps({"users": [{"user_id": "u1"}]}), json.dumps({"x": []}),
                                     json.dumps({"users": [{"user_id": "u1", "username": "a"}, {"user_id": "u1", "username": "b"}]})])  # fmt: skip
def test_load_seed_users_bad(tmp_path: Path, content: str | None) -> None:
    p = tmp_path / "seed.json"
    if content is not None:
        p.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="seed"):
        load_seed_users(p)


def test_real_seed_has_smoke_users() -> None:
    """`mock_services/seed.json` (seed của mock — được đọc): có người gửi / người duyệt mà smoke dùng."""
    names = set(load_seed_users(REPO / "mock_services" / "seed.json").values())
    assert {"an.nv", "binh.tt", "son.nt", "ha.lt"} <= names


# ---- giữ từ bản trước (nạp, lỗi, sha) --------------------------------------------------------------------------------


def test_dataset_list_file(tmp_path: Path) -> None:
    write(tmp_path, "many.yaml", [scenario(), scenario(id="SENTINEL_ID_2")])
    assert len(load(tmp_path).scenarios) == 2


def test_dataset_yml_suffix_and_other_files_ignored(tmp_path: Path) -> None:
    write(tmp_path, "a.yml", scenario())
    (tmp_path / "README.md").write_text("SENTINEL_TXT", encoding="utf-8")
    assert len(load(tmp_path).scenarios) == 1


def test_load_error_hides_file_name(tmp_path: Path) -> None:
    """Mặc định `file #i/N` — tên file (có thể lộ thẻ/họ) chỉ hiện với `show_name=True` (`--per-case`)."""
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
    data["requester"]["extra_key"] = "SENTINEL_TXT_w"
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    write(tmp_path, "SENTINEL_FILE_b.yaml", scenario(id="SENTINEL_ID_2", bogus=2))
    ds = load(tmp_path, allow_extra=True)
    assert len(ds.scenarios) == 2
    assert sorted(ds.ignored_fields) == ["bogus", "bogus", "gold.leaves", "requester.extra_key", "turns.*.extra_key"]
    assert all(SENTINEL not in f for f in ds.ignored_fields)
    assert ds.scenarios[0].replies == ("SENTINEL_TXT_tra loi",)


def test_allow_extra_fields_other_errors_still_fail(tmp_path: Path) -> None:
    write(tmp_path, "SENTINEL_FILE_a.yaml", scenario(bogus=1, family=None))
    assert fails(tmp_path, allow_extra=True).render() == ["file #1/1: không hợp lệ (family)"]


@pytest.mark.parametrize(("path", "field", "value"), [
    (("gold",), "expected_route", "SENTINEL_ROUTE"),
    (("gold",), "approver_decision", "SENTINEL_DEC"),
    (("gold",), "approver_decision", ""),
    (("gold",), "approver_decision", "Approve"),
    (("gold",), "intents", []),
])  # fmt: skip
def test_dataset_bad_value_not_echoed(tmp_path: Path, path: tuple[str, ...], field: str, value: Any) -> None:
    data = scenario()
    at(data, path)[field] = value
    write(tmp_path, "SENTINEL_FILE_a.yaml", data)
    assert fails(tmp_path).render() == [f"file #1/1: không hợp lệ ({'.'.join((*path, field))})"]


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
        load(tmp_path)


def test_dataset_not_a_dir(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="không phải thư mục"):
        load(tmp_path / "khong-co")


def test_dataset_sha_stable(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, "x.yaml", scenario())
    write(a, "y.yaml", scenario(id="SENTINEL_ID_2"))
    write(b, "y.yaml", scenario(id="SENTINEL_ID_2"))  # tạo theo thứ tự ngược
    write(b, "x.yaml", scenario())
    sha = load(a).sha256
    assert len(sha) == 64 and sha == load(b).sha256
    p = b / "x.yaml"
    p.write_bytes(p.read_bytes() + b"\n")  # 1 byte khác, nội dung YAML vẫn như cũ
    assert load(b).sha256 != sha


def test_dataset_sha_depends_on_name(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write(a, "x.yaml", scenario())
    write(b, "z.yaml", scenario())
    assert load(a).sha256 != load(b).sha256


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
