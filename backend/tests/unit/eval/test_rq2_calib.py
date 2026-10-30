"""RQ2 — hiệu chỉnh kiểm tra chéo 5 phần theo họ: không rò rỉ giữa phần; fit lỗi → không có p hiệu chỉnh (không lấy p thô thay)."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from app.eval.rq2 import calib
from app.eval.rq2.calib import CalRow, cross_fit
from app.risk.calibrator import LabeledSample, LeakageError, fit_platt

NOW = datetime(2026, 11, 1, tzinfo=UTC)


def _rows(n_fam: int = 20, per: int = 4) -> tuple[list[CalRow], dict[str, float]]:
    rows, raw = [], {}
    for f in range(n_fam):
        for j in range(per):
            tid = f"t{f:02d}-{j}"
            p = ((f * 7 + j * 3) % 19) / 20 + 0.025
            rows.append(CalRow(tid, f"H{f:02d}", f % 5 + 1, (p + (j % 2) * 0.2) > 0.55))
            raw[tid] = p
    return rows, raw


def test_family_in_two_folds_is_leakage() -> None:
    rows, raw = _rows()
    rows[1] = CalRow(rows[1].ticket_id, rows[1].family, rows[1].fold % 5 + 1, rows[1].y)
    with pytest.raises(LeakageError):
        cross_fit(rows, lambda r: raw[r.ticket_id], now=NOW)


def test_fit_never_sees_held_out_fold(monkeypatch: pytest.MonkeyPatch) -> None:
    rows, raw = _rows()
    fold_of = {r.family: r.fold for r in rows}
    seen: list[set[int]] = []

    def spy(samples: Sequence[LabeledSample], *, now: datetime) -> Any:
        seen.append({fold_of[s.family] for s in samples})
        assert all(s.split == "calibration" for s in samples)
        return fit_platt(samples, now=now)

    monkeypatch.setattr(calib, "fit_platt", spy)
    _, infos = cross_fit(rows, lambda r: raw[r.ticket_id], now=NOW)
    assert [i.status for i in infos] == ["ok"] * 5
    assert [sorted(s) for s in seen] == [sorted(set(range(1, 6)) - {k}) for k in range(1, 6)]


def test_held_out_labels_do_not_change_their_predictions() -> None:
    """Đổi nhãn của phần 3 → p hiệu chỉnh của lá phần 3 không đổi (fit không thấy phần đó); lá phần khác thì đổi."""
    rows, raw = _rows()
    base, _ = cross_fit(rows, lambda r: raw[r.ticket_id], now=NOW)
    flipped = [CalRow(r.ticket_id, r.family, r.fold, (not r.y) if r.fold == 3 else r.y) for r in rows]
    again, _ = cross_fit(flipped, lambda r: raw[r.ticket_id], now=NOW)
    fold3 = [r.ticket_id for r in rows if r.fold == 3]
    other = [r.ticket_id for r in rows if r.fold != 3]
    assert all(base[t] == again[t] for t in fold3)
    assert any(base[t] != again[t] for t in other)


def test_fit_failure_gives_none_not_raw() -> None:
    rows, raw = _rows()
    one_class = [CalRow(r.ticket_id, r.family, r.fold, r.fold == 1 and r.y) for r in rows]  # ngoài phần 1 chỉ có y = False
    got, infos = cross_fit(one_class, lambda r: raw[r.ticket_id], now=NOW)
    first = infos[0]
    assert first.fold == 1 and first.status == "fit_failed" and first.calibrator_version is None
    assert all(got[r.ticket_id] is None for r in rows if r.fold == 1)


def test_missing_raw_excluded() -> None:
    rows, raw = _rows()
    gone = rows[0].ticket_id
    got, _ = cross_fit(rows, lambda r: None if r.ticket_id == gone else raw[r.ticket_id], now=NOW)
    assert gone not in got and len(got) == len(rows) - 1
