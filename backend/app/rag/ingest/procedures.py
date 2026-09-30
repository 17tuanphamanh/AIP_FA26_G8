"""Cảnh báo `procedure_doc` khi ingest (Phase 4 S0-P10, Q-4-U A+, D-34) — KHÔNG chặn ingest.

Mỗi `action_type` khai `procedure_doc` trong `config/action_metadata.yaml`; B11 chỉ cho hành động đi tiếp khi tài liệu đó có
trong KB hiện hành, `enabled` và người gửi được xem (`base_filter`). KB mới thiếu/tắt/đặt `restricted` tài liệu quy trình →
mọi yêu cầu hành động tương ứng (của nhân viên) sẽ ra E3 `no_procedure` → in cảnh báo để người nạp KB thấy trước. Chỉ in
định danh (`doc_id`, `intent/action_type`), không in nội dung tài liệu.
"""

from collections.abc import Mapping
from pathlib import Path

import yaml

from app.domain.action import ActionMeta
from app.rag.filters import allowed_sensitivity
from app.rag.models import Doc
from app.settings import load_action_metadata


def procedure_warnings(docs: list[Doc], metadata: Mapping[str, Mapping[str, ActionMeta]]) -> list[str]:
    """Một dòng mỗi `procedure_doc` có vấn đề: không có trong KB / `enabled=false` / nhân viên không được xem (độ nhạy
    ngoài `allowed_sensitivity("employee")`, vd `restricted`). Thứ tự theo `doc_id`."""
    users: dict[str, list[str]] = {}
    for intent, actions in metadata.items():
        for action_type, meta in actions.items():
            users.setdefault(meta.procedure_doc, []).append(f"{intent}/{action_type}")
    by_id = {d.fm.doc_id: d for d in docs}
    employee = set(allowed_sensitivity("employee"))
    out: list[str] = []
    for doc_id in sorted(users):
        doc = by_id.get(doc_id)
        if doc is None:
            problem = "không có trong KB"
        elif not doc.fm.enabled:
            problem = "enabled=false"
        elif doc.fm.sensitivity not in employee:
            problem = f"sensitivity={doc.fm.sensitivity} (nhân viên không xem được)"
        else:
            continue
        out.append(
            f"cảnh báo: procedure_doc {doc_id} ({', '.join(sorted(users[doc_id]))}) {problem} — "
            "yêu cầu hành động tương ứng sẽ ra E3 no_procedure (B11)"
        )
    return out


def procedure_warnings_for(config_dir: Path, docs: list[Doc]) -> list[str]:
    """Nạp `action_metadata.yaml` của `config_dir` rồi gọi `procedure_warnings`. File hỏng không chặn ingest (backend/worker
    tự từ chối khởi động với file hỏng — `check_intent_config`) → một dòng cảnh báo chỉ nêu loại lỗi."""
    try:
        metadata = load_action_metadata(config_dir / "action_metadata.yaml").root
    except (OSError, ValueError, yaml.YAMLError) as e:  # ValidationError là ValueError
        return [f"cảnh báo: không kiểm được procedure_doc — action_metadata.yaml lỗi ({type(e).__name__})"]
    return procedure_warnings(docs, metadata)
