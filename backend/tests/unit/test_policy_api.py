"""F7 — API chính sách CHỈ ĐỌC `/api/policy*` (P10 mục 3.3, test-first theo hợp đồng giao việc).

- GET `/api/policy`, GET `/api/policy/versions` (`policy:read`), POST `/api/policy/validate` (`policy:edit`) — chỉ
  manager.
- Thứ tự lỗi 401 → 403 (+ `permission_denied`) → 413 (middleware, trước cả quyền) → 422.
- validate chỉ KIỂM (schema policy + action thuộc intent), không lưu; lỗi `invalid_policy` có `loc` tính từ gốc content.
- Không có PUT / restore / simulate (405 / 404). Không ghi nội dung / msg policy vào log.

Mọi test dùng policy GIẢ của `policy_fake.py` (luật R81–R92, ngưỡng giả) — không dùng luật hay ngưỡng thật.
"""

import copy
import hashlib
import json
import logging
from collections.abc import Callable, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from app.api.policy import schema_msg
from tests.unit.auth_helpers import AuthEnv, auth_env
from tests.unit.policy_fake import (  # noqa: F401 — fake_config là fixture
    fake_config,
    fake_policy,
    reference_accepts,
    variant,
)
from tests.unit.test_auth_route_scan import route_auth

POLICY = "/api/policy"
VERSIONS = "/api/policy/versions"
VALIDATE = "/api/policy/validate"
RESTORE = "/api/policy/versions/1/restore"
SIMULATE = "/api/policy/simulate"
NON_MANAGERS = ["ha.lt", "long.nh", "an.nv"]  # L1, L2, nhân viên
JSON_HEADERS = {"content-type": "application/json"}
LIMIT = 64 * 1024
FORBIDDEN = (403, {"detail": "forbidden"})
UNAUTHORIZED = (401, {"detail": "unauthorized"})
META_KEYS = {"version_id", "version", "updated_by", "updated_at", "is_current"}
GET_KEYS = META_KEYS | {"content"}
VERSION_KEYS = META_KEYS | {"restored_from"}

Mutate = Callable[[dict[str, Any]], None]


@pytest.fixture
def env(fake_config: Path) -> Iterator[AuthEnv]:  # noqa: F811
    """`fake_config` chạy TRƯỚC `auth_env()` để `create_app` đọc policy giả."""
    with auth_env() as e:
        yield e


# ---- tiện ích ---------------------------------------------------------------------------------------------------------


def _file_version(raw: bytes) -> str:
    return "file-" + hashlib.sha256(raw).hexdigest()[:8]


def _preview(content: dict[str, Any]) -> str:
    sep = (",", ":")
    text = json.dumps(content, sort_keys=True, separators=sep, ensure_ascii=False)
    return "file-" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def _validate(env: AuthEnv, content: Any, token: str | None = None) -> httpx2.Response:
    headers = env.bearer(token) if token else {}
    return env.client.post(VALIDATE, json={"content": content}, headers=headers)


def _post_raw(env: AuthEnv, raw: bytes, token: str | None = None) -> httpx2.Response:
    headers = {**JSON_HEADERS, **(env.bearer(token) if token else {})}
    return env.client.post(VALIDATE, content=raw, headers=headers)


def _denied(env: AuthEnv, before: int) -> list[tuple[str | None, Any]]:
    events = env.sink.of("permission_denied")[before:]
    return [(e.route, e.detail.get("perm")) for e in events]


def _is_loc_part(p: Any) -> bool:
    return isinstance(p, str | int) and not isinstance(p, bool)


def _errors(r: httpx2.Response) -> list[dict[str, Any]]:
    """422 `invalid_policy`: đúng 2 khoá gốc; mỗi lỗi đúng {loc, msg}; loc là list str|int (không bool)."""
    assert r.status_code == 422, r.text
    body = r.json()
    assert set(body) == {"error", "errors"}, body
    assert body["error"] == "invalid_policy"
    errors = body["errors"]
    assert isinstance(errors, list) and errors, body
    for e in errors:
        assert set(e) == {"loc", "msg"}, e
        assert isinstance(e["loc"], list), e
        assert all(_is_loc_part(p) for p in e["loc"]), e
        assert isinstance(e["msg"], str) and e["msg"], e
    return errors


def _locs(r: httpx2.Response) -> list[list[Any]]:
    return [e["loc"] for e in _errors(r)]


def _assert_invalid_request(r: httpx2.Response) -> None:
    assert r.status_code == 422, r.text
    body = r.json()
    assert set(body) == {"error", "fields"}, body
    assert body["error"] == "invalid_request"
    assert isinstance(body["fields"], list)


def _reorder(value: Any) -> Any:
    """Cùng nội dung, đảo thứ tự khoá ở mọi cấp (list giữ nguyên thứ tự)."""
    if isinstance(value, dict):
        return {k: _reorder(value[k]) for k in reversed(list(value))}
    if isinstance(value, list):
        return [_reorder(v) for v in value]
    return value


# ---- biến thể (dùng chung T7–T12, T21) --------------------------------------------------------------------------------


def _low_eq_high(c: dict[str, Any]) -> None:
    c["constants"]["THRESHOLD_LOW"] = 0.6
    c["constants"]["THRESHOLD_HIGH"] = 0.6


def _low_gt_high(c: dict[str, Any]) -> None:
    c["constants"]["THRESHOLD_LOW"] = 0.8
    c["constants"]["THRESHOLD_HIGH"] = 0.4


def _type_unknown_5(c: dict[str, Any]) -> None:
    c["rules"][5]["type"] = "maybe_khong_co"


def _dup_id(c: dict[str, Any]) -> None:
    c["rules"][1]["id"] = c["rules"][0]["id"]


def _first_vpn_reset_password(c: dict[str, Any]) -> None:
    # luật 0 thuộc intent vpn; reset_password là action của intent account
    assert c["rules"][0]["intent"] == "vpn"
    c["rules"][0]["action"] = "reset_password"


def _extra_block(c: dict[str, Any]) -> None:
    c["extra_block"] = {"x": 1}


def _m5_method_unknown(c: dict[str, Any]) -> None:
    c["m5"]["p_method"] = "zzz_khong_co"


def _no_business_hours(c: dict[str, Any]) -> None:
    del c["business_hours"]


def _last_wrong_str(c: dict[str, Any]) -> None:
    # luật cuối thuộc intent vpn; install_software là action của intent software
    assert c["rules"][-1]["intent"] == "vpn"
    c["rules"][-1]["action"] = "install_software"


def _last_wrong_list1(c: dict[str, Any]) -> None:
    c["rules"][-1]["action"] = ["install_software"]


def _last_list_one_wrong(c: dict[str, Any]) -> None:
    c["rules"][-1]["action"] = ["renew_vpn_cert", "install_software"]


def _first_wrong_last_ok(c: dict[str, Any]) -> None:
    # luật đầu (vpn) sai intent; luật cuối giữ nguyên
    c["rules"][0]["action"] = "grant_permission"


def _noop(c: dict[str, Any]) -> None:
    pass


VARIANTS: list[tuple[str, Mutate]] = [
    ("hop_le", _noop),
    ("t7_low_eq_high", _low_eq_high),
    ("t7_low_gt_high", _low_gt_high),
    ("t8_type_la_luat_5", _type_unknown_5),
    ("t9_id_trung", _dup_id),
    ("t10_action_sai_intent_luat_dau", _first_vpn_reset_password),
    ("t12_khoa_la_goc", _extra_block),
    ("m5_p_method_la", _m5_method_unknown),
    ("thieu_business_hours", _no_business_hours),
    ("luat_cuoi_sai_intent_chuoi", _last_wrong_str),
    ("luat_cuoi_sai_intent_list_1_phan_tu", _last_wrong_list1),
    ("luat_cuoi_list_1_phan_tu_sai", _last_list_one_wrong),
    ("luat_dau_sai_luat_cuoi_dung", _first_wrong_last_ok),
]
VARIANT_IDS = [name for name, _ in VARIANTS]
VARIANT_FNS = [fn for _, fn in VARIANTS]


# ---- T1–T5: đọc -------------------------------------------------------------------------------------------------------


def test_t01_get_policy_manager(env: AuthEnv, fake_config: Path) -> None:  # noqa: F811
    """T1 (hợp đồng mục 1): 200, đúng 6 khoá, kiểu từng trường, version = "file-" + sha256(byte file)[:8]."""
    raw = fake_config.read_bytes()
    r = env.client.get(POLICY, headers=env.bearer(env.manager_token()))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == GET_KEYS
    assert type(body["version_id"]) is int  # int, không phải bool
    assert body["version_id"] == 0
    assert isinstance(body["version"], str)
    assert len(body["version"]) <= 16
    assert body["version"] == _file_version(raw)
    assert body["content"] == json.loads(raw) == fake_policy()
    rules = body["content"]["rules"]
    assert isinstance(rules, list)
    assert len(rules) == 12
    assert body["updated_by"] is None
    assert isinstance(body["updated_at"], str)
    assert datetime.fromisoformat(body["updated_at"]).tzinfo is not None
    assert body["is_current"] is True


@pytest.mark.parametrize("username", NON_MANAGERS)
def test_t02_get_policy_non_manager_403(env: AuthEnv, username: str) -> None:
    """T2 (mục 1, 5): L1 / L2 / nhân viên → 403 forbidden + đúng một `permission_denied` (`policy:read`)."""
    headers = env.bearer(env.token(username))
    before = len(env.sink.of("permission_denied"))
    r = env.client.get(POLICY, headers=headers)
    assert (r.status_code, r.json()) == FORBIDDEN
    assert _denied(env, before) == [(POLICY, "policy:read")]


def test_t03_get_policy_no_token_401(env: AuthEnv) -> None:
    """T3 (mục 5): không token → 401."""
    r = env.client.get(POLICY)
    assert (r.status_code, r.json()) == UNAUTHORIZED


def test_t04_versions_manager(env: AuthEnv) -> None:
    """T4 (mục 2): mảng trần đúng 1 phần tử, is_current true, restored_from null, khớp GET /api/policy."""
    headers = env.bearer(env.manager_token())
    current = env.client.get(POLICY, headers=headers).json()
    r = env.client.get(VERSIONS, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, list), body
    assert len(body) == 1, body
    item = body[0]
    assert set(item) == VERSION_KEYS
    assert item["is_current"] is True
    assert item["restored_from"] is None
    assert type(item["version_id"]) is int
    assert item["version_id"] == current["version_id"]
    assert item["version"] == current["version"]
    assert item["updated_by"] == current["updated_by"]
    assert datetime.fromisoformat(item["updated_at"]).tzinfo is not None


@pytest.mark.parametrize("username", NON_MANAGERS)
def test_t05_versions_non_manager_403(env: AuthEnv, username: str) -> None:
    """T5 (mục 2, 5): L1 / L2 / nhân viên → 403 + `permission_denied` (`policy:read`)."""
    headers = env.bearer(env.token(username))
    before = len(env.sink.of("permission_denied"))
    r = env.client.get(VERSIONS, headers=headers)
    assert (r.status_code, r.json()) == FORBIDDEN
    assert _denied(env, before) == [(VERSIONS, "policy:read")]


def test_t05_versions_no_token_401(env: AuthEnv) -> None:
    """T5 (mục 5): không token → 401."""
    r = env.client.get(VERSIONS)
    assert (r.status_code, r.json()) == UNAUTHORIZED


# ---- T6–T13: validate -------------------------------------------------------------------------------------------------


def test_t06_validate_valid_preview_canonical(env: AuthEnv) -> None:
    """T6 (mục 3): bản giả hợp lệ → 200 {valid, version_preview}; preview băm dạng chuẩn hoá → đảo thứ tự khoá
    vẫn ra cùng giá trị."""
    token = env.manager_token()
    content = fake_policy()
    r = _validate(env, content, token)
    assert r.status_code == 200, r.text
    assert r.json() == {"valid": True, "version_preview": _preview(content)}
    reordered = _reorder(content)
    assert list(reordered) != list(content)  # thứ tự khoá thật sự khác
    r2 = _validate(env, reordered, token)
    assert r2.status_code == 200, r2.text
    assert r2.json()["version_preview"] == r.json()["version_preview"]


@pytest.mark.parametrize("mutate", [_low_eq_high, _low_gt_high], ids=["eq", "gt"])
def test_t07_threshold_low_ge_high_422(env: AuthEnv, mutate: Mutate) -> None:
    """T7 (mục 3): THRESHOLD_LOW ≥ THRESHOLD_HIGH → 422 invalid_policy, có lỗi loc[0] == "constants"."""
    locs = _locs(_validate(env, variant(mutate), env.manager_token()))
    assert any(loc and loc[0] == "constants" for loc in locs), locs


def test_t08_rule_type_unknown_loc(env: AuthEnv) -> None:
    """T8 (mục 3): type lạ ở luật chỉ số 5 → có lỗi loc == ["rules", 5, "type"]."""
    locs = _locs(_validate(env, variant(_type_unknown_5), env.manager_token()))
    assert ["rules", 5, "type"] in locs, locs


def test_t09_duplicate_rule_id_422(env: AuthEnv) -> None:
    """T9 (mục 3): id luật trùng → 422 invalid_policy (ít nhất 1 lỗi)."""
    assert _errors(_validate(env, variant(_dup_id), env.manager_token()))


def test_t10_action_not_in_intent_loc(env: AuthEnv) -> None:
    """T10 (mục 3): luật 0 intent vpn mà action "reset_password" → có lỗi loc == ["rules", 0, "action"]."""
    content = variant(_first_vpn_reset_password)
    locs = _locs(_validate(env, content, env.manager_token()))
    assert ["rules", 0, "action"] in locs, locs


NON_FINITE = [float("nan"), float("inf"), float("-inf")]


@pytest.mark.parametrize("bad", NON_FINITE, ids=["NaN", "Infinity", "-Infinity"])
def test_t11_nan_infinity_raw_body_one_root_error(env: AuthEnv, bad: float) -> None:
    """T11 (mục 3): NaN / Infinity trong thân thô (JSON không chuẩn) → 422 invalid_policy, ĐÚNG MỘT lỗi
    loc == [] (chặn ở bước đọc JSON, trước schema)."""
    content = fake_policy()
    content["constants"]["THRESHOLD_LOW"] = bad
    raw = json.dumps({"content": content}, allow_nan=True).encode("utf-8")
    assert b"NaN" in raw or b"Infinity" in raw
    errors = _errors(_post_raw(env, raw, env.manager_token()))
    assert len(errors) == 1, errors
    assert errors[0]["loc"] == []


def test_t12_extra_root_key_loc(env: AuthEnv) -> None:
    """T12 (mục 3): khoá lạ cấp gốc content → lỗi loc == ["extra_block"] (không tiền tố "content")."""
    locs = _locs(_validate(env, variant(_extra_block), env.manager_token()))
    assert ["extra_block"] in locs, locs
    assert all(not loc or loc[0] != "content" for loc in locs), locs


BAD_SHAPES: list[tuple[str, bytes]] = [
    ("thieu_content", b"{}"),
    ("content_la_mang", json.dumps({"content": []}).encode()),
    ("khoa_la_goc_than", json.dumps({"content": fake_policy(), "extra": 1}).encode()),
    ("json_hong", b'{"content": {'),
    ("than_rong", b""),
]
BAD_SHAPE_IDS = [name for name, _ in BAD_SHAPES]
BAD_SHAPE_BODIES = [raw for _, raw in BAD_SHAPES]


@pytest.mark.parametrize("raw", BAD_SHAPE_BODIES, ids=BAD_SHAPE_IDS)
def test_t13_bad_body_shape_invalid_request(env: AuthEnv, raw: bytes) -> None:
    """T13 (mục 3): thân sai hình dạng → 422 {"error": "invalid_request", "fields": [...]}."""
    _assert_invalid_request(_post_raw(env, raw, env.manager_token()))


# ---- T14–T15: thứ tự lỗi, không đổi trạng thái ------------------------------------------------------------------------


@pytest.mark.parametrize("username", NON_MANAGERS)
def test_t14_non_manager_bad_body_403(env: AuthEnv, username: str) -> None:
    """T14 (mục 5): L1 / L2 / nhân viên gửi thân SAI hình dạng → 403 (không 422) + `permission_denied`
    (`policy:edit`)."""
    token = env.token(username)
    for raw in BAD_SHAPE_BODIES:
        before = len(env.sink.of("permission_denied"))
        r = _post_raw(env, raw, token)
        assert (r.status_code, r.json()) == FORBIDDEN, raw
        assert _denied(env, before) == [(VALIDATE, "policy:edit")], raw


def test_t14_validate_no_token_401(env: AuthEnv) -> None:
    """T14 (mục 5): không token → 401, kể cả thân sai hình dạng / thân hợp lệ."""
    valid = json.dumps({"content": fake_policy()}).encode()
    for raw in [*BAD_SHAPE_BODIES, valid]:
        r = _post_raw(env, raw)
        assert (r.status_code, r.json()) == UNAUTHORIZED, raw


def _changed(c: dict[str, Any]) -> None:
    c["rules"][0]["description"] = "[GIẢ] mô tả đã sửa"
    c["constants"]["SLA_MINUTES"] += 7


def test_t15_validate_does_not_change_policy(env: AuthEnv, fake_config: Path) -> None:  # noqa: F811
    """T15 (mục 3 "chỉ KIỂM, không lưu"): validate bản khác hợp lệ rồi bản lỗi → GET /api/policy y nguyên
    (version, content, updated_at), file policy.json không đổi byte."""
    raw_before = fake_config.read_bytes()
    token = env.manager_token()
    headers = env.bearer(token)
    snap = env.client.get(POLICY, headers=headers).json()
    r = _validate(env, variant(_changed), token)
    assert r.status_code == 200, r.text
    after_ok = env.client.get(POLICY, headers=headers).json()
    r_bad = _validate(env, variant(_type_unknown_5), token)
    assert r_bad.status_code == 422, r_bad.text
    after_bad = env.client.get(POLICY, headers=headers).json()
    for after in (after_ok, after_bad):
        for key in ("version_id", "version", "content", "updated_at"):
            assert after[key] == snap[key], key
        assert after["content"] == fake_policy()
    assert fake_config.read_bytes() == raw_before
    versions = env.client.get(VERSIONS, headers=headers).json()
    assert len(versions) == 1
    assert versions[0]["version"] == snap["version"]


# ---- T16–T19: khai báo route ------------------------------------------------------------------------------------------


def test_t16_openapi_response_models(env: AuthEnv) -> None:
    """T16 (mục 6): 3 route có schema phản hồi 200 (không rỗng); validate khai thêm 422."""
    paths = env.app.openapi()["paths"]
    for path, method in ((POLICY, "get"), (VERSIONS, "get"), (VALIDATE, "post")):
        responses = paths[path][method]["responses"]
        schema = responses["200"]["content"]["application/json"]["schema"]
        assert schema, (path, method)
    assert "422" in paths[VALIDATE]["post"]["responses"]


def test_t17_route_scan_requirements(env: AuthEnv) -> None:
    """T17 (mục 1–3): marker quyền — đọc `policy:read`, validate `policy:edit`, không đòi đăng nhập gần."""
    routes = list(route_auth(env.app))
    found = {(m, c.path): c.requirements for c in routes for m in c.methods}
    assert found[("GET", POLICY)] == (("policy:read", None, False),)
    assert found[("GET", VERSIONS)] == (("policy:read", None, False),)
    assert found[("POST", VALIDATE)] == (("policy:edit", None, False),)


def test_t18_put_policy_405(env: AuthEnv) -> None:
    """T18 (mục 4): PUT /api/policy không có route → 405, có hay không token manager."""
    body = {"content": fake_policy()}
    assert env.client.put(POLICY, json=body).status_code == 405
    headers = env.bearer(env.manager_token())
    assert env.client.put(POLICY, json=body, headers=headers).status_code == 405


def test_t19_restore_simulate_404(env: AuthEnv) -> None:
    """T19 (mục 4): restore và simulate không có route → 404 (manager)."""
    headers = env.bearer(env.manager_token())
    body = {"content": fake_policy()}
    assert env.client.post(RESTORE, json={}, headers=headers).status_code == 404
    assert env.client.post(SIMULATE, json=body, headers=headers).status_code == 404


# ---- T20: 413 trước quyền ---------------------------------------------------------------------------------------------


def test_t20_body_over_64kb_413_before_403(env: AuthEnv) -> None:
    """T20 (mục 5): thân > 64 KB → 413 với L1 (trước 403, không `permission_denied`) và với manager."""
    content = fake_policy()
    content["rules"][0]["description"] = "a" * 70_000
    raw = json.dumps({"content": content}, ensure_ascii=False).encode("utf-8")
    assert len(raw) > LIMIT
    l1 = env.token("ha.lt")
    before = len(env.sink.of("permission_denied"))
    assert _post_raw(env, raw, l1).status_code == 413
    assert _denied(env, before) == []
    assert _post_raw(env, raw, env.manager_token()).status_code == 413


# ---- T21: so khớp với kiểm gốc ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("mutate", VARIANT_FNS, ids=VARIANT_IDS)
def test_t21_validate_matches_reference(env: AuthEnv, mutate: Mutate) -> None:
    """T21 (mục 3 "đúng schema + kiểm action thuộc intent như lúc khởi động"): (validate 200) ==
    reference_accepts (bản gốc chạy cả file)."""
    content = variant(mutate)
    expected = reference_accepts(copy.deepcopy(content))
    r = _validate(env, content, env.manager_token())
    assert r.status_code in (200, 422), r.text
    assert (r.status_code == 200) == expected, (expected, r.text)


def test_t21_variants_cover_both_outcomes(fake_config: Path) -> None:  # noqa: F811
    """T21: danh sách biến thể có cả ca bản gốc nhận lẫn ca bản gốc từ chối (không gọi route)."""
    outcomes = {name: reference_accepts(variant(fn)) for name, fn in VARIANTS}
    assert outcomes["hop_le"] is True, outcomes
    assert outcomes["luat_cuoi_sai_intent_chuoi"] is False, outcomes
    assert {True, False} <= set(outcomes.values()), outcomes


# ---- T22: không log nội dung policy -----------------------------------------------------------------------------------


MARKER = "MARKER-F7-XYZ"


def _marked(c: dict[str, Any]) -> None:
    c["rules"][0]["description"] = f"[GIẢ] {MARKER}"


def _marked_bad(c: dict[str, Any]) -> None:
    _marked(c)
    _type_unknown_5(c)


def _capture_all_loggers(caplog: pytest.LogCaptureFixture) -> list[logging.Logger]:
    """Mức DEBUG cho root + mọi logger đã có; gắn handler của caplog vào logger không propagate."""
    caplog.set_level(logging.DEBUG)
    attached: list[logging.Logger] = []
    for name, lg in list(logging.root.manager.loggerDict.items()):
        if isinstance(lg, logging.Logger):
            caplog.set_level(logging.DEBUG, logger=name)
            if not lg.propagate:
                lg.addHandler(caplog.handler)
                attached.append(lg)
    return attached


def test_t22_no_policy_content_in_logs(
    env: AuthEnv,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """T22 (mục 7): validate bản lỗi + bản hợp lệ có marker trong `description` → không bản ghi log nào
    (mọi logger, mức DEBUG) chứa marker hay msg lỗi trả về."""
    token = env.manager_token()
    attached = _capture_all_loggers(caplog)
    caplog.clear()
    try:
        msgs = [e["msg"] for e in _errors(_validate(env, variant(_marked_bad), token))]
        r_good = _validate(env, variant(_marked), token)
        assert r_good.status_code == 200, r_good.text
    finally:
        for lg in attached:
            lg.removeHandler(caplog.handler)
    for rec in caplog.records:
        text = f"{rec.getMessage()} {rec.__dict__!r}"
        assert MARKER not in text, rec
        for msg in msgs:
            assert msg not in text, (msg, rec)


# ---- T23: câu lỗi schema tiếng Việt theo loại lỗi pydantic (lô N, N9) -------------------------------------------------


def _wrong_type_5(c: dict[str, Any]) -> None:
    c["rules"][5]["type"] = "maybe_khong_co"


def _max_loops_str(c: dict[str, Any]) -> None:
    c["constants"]["MAX_LOOPS"] = "bon"


def _max_loops_frac(c: dict[str, Any]) -> None:
    c["constants"]["MAX_LOOPS"] = 1.5


def _description_int(c: dict[str, Any]) -> None:
    c["rules"][0]["description"] = 5


def _bad_rule_id(c: dict[str, Any]) -> None:
    c["rules"][0]["id"] = "X1"  # sai mẫu ^R\d{2}$ → string_pattern_mismatch (không có câu riêng)


SCHEMA_MSG_CASES: list[tuple[str, Mutate, list[Any], str]] = [
    ("literal_rule_type", _wrong_type_5, ["rules", 5, "type"], "Phải là một trong: 'allow', 'approval_required', 'deny'"),
    ("literal_p_method", _m5_method_unknown, ["m5", "p_method"], "Phải là một trong: 'self_report', 'sampling_k5'"),
    ("missing", _no_business_hours, ["business_hours"], "Thiếu trường bắt buộc"),
    ("extra_forbidden", _extra_block, ["extra_block"], "Trường không được phép"),
    ("int_parsing", _max_loops_str, ["constants", "MAX_LOOPS"], "Phải là số nguyên"),
    ("int_from_float", _max_loops_frac, ["constants", "MAX_LOOPS"], "Phải là số nguyên"),
    ("string_type", _description_int, ["rules", 0, "description"], "Phải là chuỗi"),
    ("du_phong", _bad_rule_id, ["rules", 0, "id"], "Giá trị không hợp lệ"),
]


@pytest.mark.parametrize(
    ("mutate", "loc", "msg"), [c[1:] for c in SCHEMA_MSG_CASES], ids=[c[0] for c in SCHEMA_MSG_CASES]
)
def test_t23_schema_msg_vietnamese_by_type(env: AuthEnv, mutate: Mutate, loc: list[Any], msg: str) -> None:
    """T23: 422 invalid_policy giữ loc + hình dạng {loc, msg}; msg tiếng Việt theo `type` lỗi pydantic, không còn "Input should"."""
    errors = _errors(_validate(env, variant(mutate), env.manager_token()))
    assert {"loc": loc, "msg": msg} in errors, errors
    assert all("Input should" not in e["msg"] and "Field required" not in e["msg"] for e in errors), errors


def test_t23_own_vietnamese_msg_kept(env: AuthEnv) -> None:
    """T23: câu do validator của schema tự viết (value_error) giữ nguyên msg gốc — THRESHOLD_LOW ≥ THRESHOLD_HIGH."""
    errors = _errors(_validate(env, variant(_low_eq_high), env.manager_token()))
    assert {"loc": ["constants"], "msg": "Value error, THRESHOLD_LOW phải nhỏ hơn THRESHOLD_HIGH"} in errors, errors


SCHEMA_MSG_PURE: list[tuple[str, dict[str, Any], str]] = [
    ("bool_type", {"type": "bool_type", "msg": "Input should be a valid boolean"}, "Phải là đúng/sai"),
    ("bool_parsing", {"type": "bool_parsing", "msg": "Input should be a valid boolean, unable to interpret input"}, "Phải là đúng/sai"),
    ("int_type", {"type": "int_type", "msg": "Input should be a valid integer"}, "Phải là số nguyên"),
    ("literal_mot_gia_tri", {"type": "literal_error", "msg": "x", "ctx": {"expected": "'only'"}}, "Phải là một trong: 'only'"),
    ("literal_thieu_ctx", {"type": "literal_error", "msg": "Input should be 'a' or 'b'"}, "Giá trị không hợp lệ"),
    ("value_error", {"type": "value_error", "msg": "Value error, câu tự viết", "ctx": {"error": ValueError("x")}}, "Value error, câu tự viết"),
    ("assertion_error", {"type": "assertion_error", "msg": "Assertion failed, câu tự viết"}, "Assertion failed, câu tự viết"),
    ("loai_la", {"type": "greater_than_equal", "msg": "Input should be greater than or equal to 1"}, "Giá trị không hợp lệ"),
]


@pytest.mark.parametrize(("error", "msg"), [c[1:] for c in SCHEMA_MSG_PURE], ids=[c[0] for c in SCHEMA_MSG_PURE])
def test_t23_schema_msg_pure(error: dict[str, Any], msg: str) -> None:
    """T23 (thuần): bool / int_type (không dựng được qua schema policy hiện tại), literal thiếu ctx, value_error, loại lạ."""
    assert schema_msg(error) == msg
