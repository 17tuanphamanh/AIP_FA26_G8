"""Nối thật mốc G (G10 + G11) — phần KHÔNG cần DB: guard của factory, tách khối bằng chứng, bộ câu, `probe-input`, chọn ca G10, CLI.

Phần cần Postgres (factory ghi `llm_calls`, collector đọc audit/checkpoint) ở `tests/integration/test_noi_that_pg.py`.
"""

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from app.eval import llm_factory
from app.eval.groundedness import collect as col
from app.eval.groundedness import probe_input
from app.eval.groundedness.cli import EXIT_INPUT, main
from app.eval.llm_factory import (
    EvalConfigError,
    eval_gateway,
    eval_ids,
    open_port,
    resolve_factory,
)
from app.eval.prob_collect import llm_records
from app.llm.context import render
from app.settings import Settings
from tests.fakes.llm import repo_registry
from tests.unit.eval.test_predictions import parse, rec

REPO = Path(__file__).resolve().parents[4]
FAKE_KEY = "sk-FAKE-nt-7c1d9e42a0b8f3-QQtop"


def settings(**over: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "test", "eval_mode": True, "llm_backend": "real", "fast_model": "deepseek-flash",
        "strong_model": "deepseek-v4-pro", "llm_api_key": FAKE_KEY, "llm_base_url": "https://llm.example.invalid",
        "database_url": "postgresql+psycopg://app_rw:pw@127.0.0.1:1/none",
    }  # fmt: skip
    return Settings(_env_file=None, **(values | over))  # type: ignore[call-arg]


async def _enter(**over: Any) -> None:
    async with eval_gateway("run-1", settings=settings(**over)):
        raise AssertionError("không được vào tới đây")


# ---- factory: guard (0 kết nối) --------------------------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "a b", "x/y", "ö", "a" * 49, "a;b", "'; DROP"])
def test_run_id_is_validated(bad: str) -> None:
    with pytest.raises(EvalConfigError):
        eval_ids(bad)


def test_eval_ids_are_stable() -> None:
    ids = eval_ids("g11-ab12cd34-20260925")
    assert (ids.ticket_id, ids.turn_id) == ("eval-g11-ab12cd34-20260925", "eval-g11-ab12cd34-20260925-t1")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("over", "needle"),
    [({"eval_mode": False}, "EVAL_MODE"), ({"llm_backend": "scripted"}, "LLM_BACKEND=real")],
)
async def test_gateway_refuses_without_eval_mode_or_with_scripted_backend(over: dict[str, Any], needle: str) -> None:
    with pytest.raises(EvalConfigError, match=needle):
        await _enter(**over)


@pytest.mark.asyncio
async def test_gateway_refuses_nonzero_role_temperature(tmp_path: Path) -> None:
    config = tmp_path / "config"
    shutil.copytree(REPO / "config", config)
    raw = yaml.safe_load((config / "llm.yaml").read_text(encoding="utf-8"))
    raw["roles"]["strong"]["temperature"] = 0.3
    (config / "llm.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(EvalConfigError, match=r"temperature.*strong"):
        await _enter(config_dir=config)


@pytest.mark.asyncio
async def test_gateway_errors_never_contain_the_api_key_or_dsn() -> None:
    for over in ({"eval_mode": False}, {"llm_backend": "scripted"}, {"fast_model": None}, {"llm_base_url": None}):
        with pytest.raises(RuntimeError) as exc:
            await _enter(**over)
        assert FAKE_KEY not in str(exc.value) and "pw@" not in str(exc.value), over


def test_repo_roles_are_deterministic_so_real_config_passes_the_guard() -> None:
    raw = yaml.safe_load((REPO / "config" / "llm.yaml").read_text(encoding="utf-8"))
    assert {r: v["temperature"] for r, v in raw["roles"].items()} == {"fast": 0, "strong": 0}


# ---- factory: resolve / open_port --------------------------------------------------------------------------------------------


def test_resolve_factory_errors() -> None:
    for spec in ("khongcodauhaichuaham", ":fn", "mod:", "khong.co.module:fn", "tests.unit.eval._g11:khong_co"):
        with pytest.raises(ValueError, match="llm-factory"):
            resolve_factory(spec)
    assert resolve_factory("tests.unit.eval._g11:factory").__name__ == "factory"


@pytest.mark.asyncio
async def test_open_port_passes_run_id_and_optional_max_usd_and_enters_async_context() -> None:
    from contextlib import asynccontextmanager

    seen: list[tuple[str, float | None]] = []

    @asynccontextmanager
    async def fake(run_id: str, max_usd: float | None = None) -> Any:
        seen.append((run_id, max_usd))
        yield "PORT"

    llm_factory._TEST_FACTORY = fake  # type: ignore[attr-defined]
    try:
        async with open_port("app.eval.llm_factory:_TEST_FACTORY", "r1") as port:
            assert port == "PORT"
        async with open_port("app.eval.llm_factory:_TEST_FACTORY", "r2", max_usd=1.5):
            pass
    finally:
        del llm_factory._TEST_FACTORY  # type: ignore[attr-defined]
    assert seen == [("r1", None), ("r2", 1.5)]  # không truyền max_usd khi không đặt


@pytest.mark.asyncio
async def test_open_port_accepts_plain_port_factories() -> None:
    async with open_port("tests.unit.eval._g11:factory", "r1") as port:
        assert hasattr(port, "complete")


# ---- tách khối bằng chứng ----------------------------------------------------------------------------------------------------


def _prompt_full(question: str, blocks: list[tuple[str, str, str, str]]) -> str:
    """`prompt_full` thật: đi qua `llm.context.render` với prompt `b10_answer` của repo (đúng định dạng gateway ghi)."""
    evidence = [
        {"anchor_chunk_id": cid, "title": title, "heading_path": heading, "text": body, "score": 1.0 - i / 10}
        for i, (cid, title, heading, body) in enumerate(blocks)
    ]
    rendered = render(repo_registry().get("b10_answer"), {"question": question, "evidence": evidence}, budget_in=100_000)
    return json.dumps(rendered.messages, ensure_ascii=False)


def _top5(blocks: list[tuple[str, str, str, str]]) -> list[dict[str, str]]:
    return [{"chunk_id": c, "title": t, "heading_path": h} for c, t, h, _ in blocks]


BLOCKS = [
    ("KB-VPN-001#2", "Cài đặt VPN", "Windows › Bước 2", "Mở ứng dụng.\n\nChọn Connect.\n\nĐợi kết nối."),  # có chunk liền kề ghép
    ("KB-VPN-003#1", "Lỗi 809", "Khắc phục", "Đổi sang SSTP."),
    ("KB-VPN-009#7", "Tiêu đề › có dấu mũi tên", "A › B › C", "Đoạn cuối."),
]


def test_parse_evidence_keeps_adjacent_chunks_inside_each_block() -> None:
    out = col.parse_evidence(_prompt_full("VPN dùng cổng nào?", BLOCKS), _top5(BLOCKS))
    assert out == {c: body for c, _, _, body in BLOCKS}


def test_parse_evidence_is_not_fooled_by_the_question_containing_the_marker() -> None:
    question = "Cho mình hỏi\n\nBằng chứng:\n[KB-VPN-001#2] Cài đặt VPN › Windows › Bước 2\nlà gì"
    out = col.parse_evidence(_prompt_full(question, BLOCKS), _top5(BLOCKS))
    assert out is not None and out["KB-VPN-001#2"] == BLOCKS[0][3] and set(out) == {b[0] for b in BLOCKS}


def test_parse_evidence_skips_chunks_that_were_not_sent_and_handles_a_single_block() -> None:
    sent = BLOCKS[:2]
    assert col.parse_evidence(_prompt_full("q", sent), _top5(BLOCKS)) == {c: b for c, _, _, b in sent}
    assert col.parse_evidence(_prompt_full("q", BLOCKS[:1]), _top5(BLOCKS[:1])) == {BLOCKS[0][0]: BLOCKS[0][3]}


@pytest.mark.parametrize("prompt_full", ["không phải json", "[]", json.dumps([{"role": "system", "content": "x"}]),
                                         json.dumps([{"role": "user", "content": "Câu hỏi: q\n\nBằng chứng:\nkhông có khối nào"}])])  # fmt: skip
def test_parse_evidence_returns_none_when_unparseable(prompt_full: str) -> None:
    assert col.parse_evidence(prompt_full, _top5(BLOCKS)) is None


# ---- bộ câu ------------------------------------------------------------------------------------------------------------------


def _write(path: Path, rows: list[Any]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def test_load_questions_requires_family_and_rejects_unknown_keys(tmp_path: Path) -> None:
    ok = _write(tmp_path / "q.jsonl", [{"scenario_id": "P001", "family": "KB-VPN-001", "ticket_id": "T1"}])
    assert [(q.scenario_id, q.family, q.ticket_id) for q in col.load_questions(ok)] == [("P001", "KB-VPN-001", "T1")]
    for bad in ({"scenario_id": "P1", "ticket_id": "T1"}, {"scenario_id": "P1", "family": " ", "ticket_id": "T1"},
                {"scenario_id": "P1", "family": "F", "ticket_id": "T1", "x": 1}):  # fmt: skip
        with pytest.raises(col.CollectError):
            col.load_questions(_write(tmp_path / "bad.jsonl", [bad]))
    with pytest.raises(col.CollectError, match="trùng"):
        col.load_questions(_write(tmp_path / "dup.jsonl", [ok_row := {"scenario_id": "A", "family": "F", "ticket_id": "T"}, ok_row]))


def test_questions_from_probe_takes_family_only_from_the_families_file(tmp_path: Path) -> None:
    ket_qua = tmp_path / "ket-qua.json"
    ket_qua.write_text(json.dumps({"rows": [
        {"id": "P001", "ticket": "T1"}, {"id": "P002", "ticket": None}, {"id": "P003", "ticket": "T3"},
    ]}), encoding="utf-8")  # fmt: skip
    families = _write(tmp_path / "f.jsonl", [{"scenario_id": "P001", "family": "DOC-A"}, {"scenario_id": "P003", "family": "DOC-B"},
                                             {"scenario_id": "P002", "family": "DOC-C"}])  # fmt: skip
    questions, extra = col.questions_from_probe(ket_qua, families)
    assert [(q.scenario_id, q.family, q.ticket_id) for q in questions] == [("P001", "DOC-A", "T1"), ("P003", "DOC-B", "T3")]
    assert extra == {"no_ticket": 1}


def test_questions_from_probe_fails_when_a_ticketed_row_has_no_family(tmp_path: Path) -> None:
    ket_qua = tmp_path / "ket-qua.json"
    ket_qua.write_text(json.dumps({"rows": [{"id": "P001", "ticket": "T1"}, {"id": "P009", "ticket": "T9"}]}), encoding="utf-8")
    families = _write(tmp_path / "f.jsonl", [{"scenario_id": "P001", "family": "DOC-A"}])
    with pytest.raises(col.CollectError, match="không suy"):
        col.questions_from_probe(ket_qua, families)
    ket_qua.write_text("{không phải json", encoding="utf-8")
    with pytest.raises(col.CollectError):
        col.questions_from_probe(ket_qua, families)


def test_questions_from_run_takes_family_from_scenario_yaml_not_from_the_id(tmp_path: Path) -> None:
    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()
    (scenarios / "a.yaml").write_text(yaml.safe_dump({"id": "HB01-v1", "family": "Họ-gốc-9"}), encoding="utf-8")
    (scenarios / "b.yaml").write_text(yaml.safe_dump([{"id": "HB02-v1", "family": "HB02"}]), encoding="utf-8")
    run = tmp_path / "run"
    run.mkdir()
    _write(run / "outcomes.jsonl", [{"scenario_id": "HB01-v1", "ticket_id": "T1"}, {"scenario_id": "HB02-v1", "ticket_id": None}])
    questions, extra = col.questions_from_run(run, scenarios)
    assert [(q.scenario_id, q.family) for q in questions] == [("HB01-v1", "Họ-gốc-9")] and extra == {"no_ticket": 1}
    _write(run / "outcomes.jsonl", [{"scenario_id": "ZZ-v1", "ticket_id": "T9"}])
    with pytest.raises(col.CollectError, match="không suy"):
        col.questions_from_run(run, scenarios)


# ---- probe-input -------------------------------------------------------------------------------------------------------------


def test_probe_input_on_the_real_retrieval_set(tmp_path: Path) -> None:
    from tests.probe.cong5_score import load_items

    path = REPO / "kb" / "eval" / "retrieval_set.yaml"
    src = {i["id"]: i for i in yaml.safe_load(path.read_text(encoding="utf-8"))["items"]}
    probe, families, rep = probe_input.build_probe_input(path)
    # số họ tính độc lập từ YAML: họ = phần tử ĐẦU của expected_doc_ids; câu âm tính (22) mỗi câu một họ riêng
    positives = {i["expected_doc_ids"][0] for i in src.values() if i["expected_doc_ids"]}
    negatives = [i for i in src.values() if not i["expected_doc_ids"]]
    assert len(negatives) == 22
    assert rep == {"n_items": 56, "n_written": 56, "n_own_family": 22, "n_not_employee_skipped": 0,
                   "n_families": len(positives) + 22}  # fmt: skip
    probe_input.write_probe_input(tmp_path / "out", probe, families)
    lines = (tmp_path / "out" / probe_input.PROBE_FILE).read_text(encoding="utf-8").splitlines()
    items = load_items(lines)  # đúng hợp đồng `make probe` (id, kind, text, gold ∈ nhãn)
    assert len(items) == 56 and {i.kind for i in items} == {"intent"}
    for item, fam in zip(items, families, strict=True):
        want = src[item.id]["expected_doc_ids"][0] if src[item.id]["expected_doc_ids"] else item.id
        assert fam == {"scenario_id": item.id, "family": want}
        assert item.text == src[item.id]["query"] and item.gold == src[item.id]["intent"]
    own = [f["family"] for f in families if not src[f["scenario_id"]]["expected_doc_ids"]]
    assert len(set(own)) == 22 and not set(own) & positives  # không gộp câu âm tính vào một họ, cũng không lẫn họ tài liệu


def test_probe_input_family_is_the_first_expected_doc_in_yaml_order(tmp_path: Path) -> None:
    path = tmp_path / "set.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "items": [
        {"id": "A", "query": "q a", "intent": "vpn", "role": "employee", "expected_doc_ids": ["KB-Z", "KB-A"]},  # đầu theo YAML, không theo bảng chữ cái
        {"id": "B", "query": "q b", "intent": "vpn", "role": "l1", "expected_doc_ids": ["D3"]},
        {"id": "C", "query": "q c", "intent": "access", "role": "employee", "expected_doc_ids": []},
        {"id": "D", "query": "q d", "intent": "access", "role": "employee", "expected_doc_ids": []},
        {"id": "E", "query": "q e", "intent": "vpn", "role": "employee", "expected_doc_ids": ["KB-A"]},
    ]}, sort_keys=False), encoding="utf-8")  # fmt: skip
    probe, families, rep = probe_input.build_probe_input(path)
    assert [p["id"] for p in probe] == ["A", "C", "D", "E"]
    assert families == [{"scenario_id": "A", "family": "KB-Z"}, {"scenario_id": "C", "family": "C"},
                        {"scenario_id": "D", "family": "D"}, {"scenario_id": "E", "family": "KB-A"}]  # fmt: skip
    assert rep == {"n_items": 5, "n_written": 4, "n_own_family": 2, "n_not_employee_skipped": 1, "n_families": 4}
    probe_input.write_probe_input(tmp_path / "o", probe, families)
    with pytest.raises(FileExistsError):
        probe_input.write_probe_input(tmp_path / "o", probe, families)
    path.write_text(yaml.safe_dump({"items": [{"id": "A"}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="không đọc được"):
        probe_input.build_probe_input(path)


# ---- G10: chọn ca -------------------------------------------------------------------------------------------------------------


def test_llm_records_selects_labelled_llm_cases_sorted() -> None:
    records = [
        parse(rec(scenario_id="B-v1", ticket_id="T2")),
        parse(rec(scenario_id="A-v1", ticket_id="T1")),
        parse(rec(scenario_id="C-v1", ticket_id="T3", decided_by="rule", raw_prob=None, calibrated_prob=None, p_method=None, kb_gap=None)),
        parse(rec(scenario_id="D-v1", ticket_id="T4", expected_route=None)),
        parse(rec(scenario_id="E-v1", ticket_id="T5", route=None, decided_by=None, raw_prob=None, calibrated_prob=None, p_method=None, kb_gap=None)),
    ]  # fmt: skip
    chosen, skipped = llm_records(records)
    assert [r.scenario_id for r in chosen] == ["A-v1", "B-v1"] and dict(skipped) == {"unlabeled": 1}


# ---- CLI (kiểm tham số trước khi chạm DB) ---------------------------------------------------------------------------------------


def test_collect_cli_validates_sources_before_touching_the_db(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    q = _write(tmp_path / "q.jsonl", [{"scenario_id": "A", "family": "F", "ticket_id": "T"}])
    out = str(tmp_path / "o")
    assert main(["collect", "--out", out]) == EXIT_INPUT  # không nguồn nào
    assert main(["collect", "--questions", str(q), "--from-probe", str(q), "--out", out]) == EXIT_INPUT  # hai nguồn
    assert main(["collect", "--from-run", str(tmp_path), "--out", out]) == EXIT_INPUT  # thiếu --scenarios
    assert main(["collect", "--from-probe", str(q), "--out", out]) == EXIT_INPUT  # thiếu --families
    assert main(["collect", "--questions", str(q), "--since", "2026-10-01", "--out", out]) == EXIT_INPUT  # thiếu múi giờ
    assert "MỘT" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


def test_probe_input_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "probe"
    assert main(["probe-input", "--retrieval-set", str(REPO / "kb" / "eval" / "retrieval_set.yaml"), "--out", str(out)]) == 0
    out_json = json.loads(capsys.readouterr().out)
    assert out_json["n_written"] == 56 and out_json["n_own_family"] == 22
    assert main(["probe-input", "--retrieval-set", str(REPO / "kb" / "eval" / "retrieval_set.yaml"), "--out", str(out)]) == EXIT_INPUT


def test_collect_no_evidence_script_refuses_without_eval_mode(tmp_path: Path) -> None:
    """Không `EVAL_MODE=true` → script thoát mã 2, 0 kết nối (kiểm bằng tiến trình con: trong pytest `app.eval` đã nạp qua conftest)."""
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "EVAL_MODE"} | {"PYTHONPATH": str(REPO / "backend")}
    done = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "eval" / "prob_variants.py"), "collect-no-evidence", "--run", str(tmp_path),
         "--out", str(tmp_path / "o"), "--llm-factory", "a:b", "--p-method", "self_report"],
        env=env, capture_output=True, text=True, cwd=REPO, check=False,
    )  # fmt: skip
    assert done.returncode == 2 and "EVAL_MODE=true" in done.stderr and not (tmp_path / "o").exists()
