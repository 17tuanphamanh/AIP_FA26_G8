# PROGRESS

*Theo `docs/spec/CLAUDE.md` mục 4: phase đang mở, task xong, cổng nào xanh, câu hỏi mở.
Mọi đường dẫn dưới đây tính từ `docs/spec/`.*

## Trạng thái

| Mục | Giá trị |
|---|---|
| Chế độ xây | **Code trước, gắn API sau** (`build/decisions.md` mục 4): Phase 1–7 dùng `ScriptedLLM`, không gọi LLM thật |
| Phase đang mở | **1 — Hạ tầng, DB, domain, mock, auth** |
| Cổng xanh | Phase 0 |
| Cập nhật | 25/09/2026 |

## Phase 0 — đã xong (25/09/2026)

- D-01…D-33: **đã chốt theo đặc tả** (`build/decisions.md` mục 3).
- Q1–Q14: nhóm tự quyết, chỉ báo cáo GVHD, không có vòng hỏi (`build/decisions.md` mục 2).
- N3, N4, N5 đã chốt. N1 (chọn model) và N2 (VRAM) **chỉ chặn mốc G**, không chặn code.
- Bảng 20 luật R01–R20: `build/decisions.md` mục 1.1 (luật VPN thiết bị chưa đăng ký = **R17**, tài liệu cũ ghi R22).

## Việc đã làm (chuẩn bị repo, trước Phase 1)

- Gỡ agent thử nghiệm cũ; dựng cây thư mục theo `build/01-kien-truc-project.md` mục 3
  ngay tại gốc repo (chỉ `__init__.py` + README 1 dòng, **chưa có logic nghiệp vụ**).
- `pyproject.toml` (Python 3.12, uv) + `uv.lock`; `Makefile` theo 01 mục 7.1 — `test`,
  `lint` chạy được, các lệnh khác in TODO.
- `backend/tests/unit/test_smoke.py` — test giữ chỗ; **đã xoá** ở Phase 1b khi có test thật.

Cổng T01 (01 mục 8): mục 2 (5 hợp đồng import-linter trong `make lint` + hợp đồng 6 là test AST
trong `make test`) và mục 3 (test chữ ký
`policy_engine.evaluate`) **xanh** từ Phase 1b. Còn thiếu: mục 1 (`make up`, `/api/health`),
mục 4 (gitleaks), mục 5 (image backend = worker).

## Phase 1 — đang mở

| Việc | Trạng thái |
|---|---|
| docker-compose (postgres 16, qdrant, backend, mock_services) + `make up/down` | Chưa |
| DB 22 bảng + 3 role Postgres + trigger append-only (Alembic, P7) | Chưa |
| `backend/app/core`, `domain` (14 trạng thái, `is_allowed`, E0–E9, Action, hash) | **Xong** 25/09/2026 (Phase 1b) — `build_action` làm cùng B11 (câu hỏi 9) |
| `mock_services` + `seed.json` + `make seed` (P5) | Chưa |
| Auth (P6) | Chưa |
| `.importlinter` 5 hợp đồng + hợp đồng 6 bằng test AST (01 mục 4.3) | **Xong** 25/09/2026 (Phase 1b) — `make lint` + `test_side_effects_ast.py`, `test_write_adapters_listed.py`; đã thử phá từng hợp đồng, đều bắt được |
| `.env.example` theo 01 mục 5.1 (bỏ biến agent cũ; biến LLM để trống tới mốc G) | Chưa |

## Dồn về mốc G (cần LLM thật — làm sau Phase 7, trước Phase 8)

*Mỗi phase ghi thêm vào đây phần cổng cần LLM thật mà chưa chạy.*

| Phase | Việc | Nguồn |
|---|---|---|
| — | Chọn model fast/strong bằng probe, điền `pricing` (N1) | P2 mục 12–13 |
| — | Ghi GPU + VRAM 3 máy gaming (N2) | `build/decisions.md` mục 1.3 |
| 3 | Demo 4 ca VPN với LLM thật (+ chạy thử 1 lần bằng model rẻ ngay khi xong cổng code Phase 3) | `huong-dan` 5.1, `decisions.md` mục 4 |
| 5 | Cổng 5 thủ công | `huong-dan` 5.1 |
| 6 | Probe phân phối p | `huong-dan` 5.1 |

---

## Câu hỏi mở / điểm lệch

1. ~~Bảng `decisions.md` mục 2 hỏng~~ — **đã sửa** (25/09/2026).
2. ~~CSV trong `eval/reports/`~~ — **đã thêm** `!eval/reports/**/*.csv` (25/09/2026).
3. Ba package cùng tên `app` (backend, ml_service, mock_services): hướng xử lý là
   `make test`/`make lint` gọi pytest và mypy **riêng từng service**, mỗi lần một
   `PYTHONPATH`; không đổi tên package. Làm khi tới P4/P5.
4. ~~`data/` cũ~~ — **đã gỡ** (25/09/2026). Luật `data/*` trong `.gitignore` giữ lại, vô hại.
5. P8 mục 4.2 ghi `eval/kb-facts.md` "tạo ở Phase 0" — chưa tạo; làm cùng luồng nội dung KB.
6. Nhóm `ml` trong `pyproject.toml` lấy `torch` từ PyPI; Dockerfile ml-service cần index
   CPU của PyTorch để không kéo bản CUDA — xử lý khi làm P4.
7. ~~Hook chặn nhầm~~ — **đã sửa** (25/09/2026): `.claude/hooks/pre-commit-test.sh` tự lọc
   lệnh có `git commit` từ stdin; `.githooks/pre-commit` dùng `uv run --locked`.
8. ~~Mâu thuẫn cấm số 5 ↔ D-29~~ — **đã giải quyết** (25/09/2026): người nới đặc tả (NGU-CANH IV 2.2,
   B02 mục 7, P1 5.1.1) thành `S_SCREENING` → ngoài {`S_CLASSIFYING`, `S_BLOCKED`, `S_ESCALATED`};
   `S_SCREENING → S_SCREENING` vẫn cấm. Có test ở `backend/tests/unit/test_states.py`. Ghi chép gốc:
   chuyển cấm số 5
   (`NGU-CANH-DAY-DU.md` IV 2.2 **[Chốt]**: `S_SCREENING` → bất kỳ đâu ngoài `S_CLASSIFYING`/`S_BLOCKED`)
   đụng D-29 quy tắc 2 (P1 5.1.1: mọi trạng thái chưa kết thúc → `S_ESCALATED`, ghi rõ "E2/E9 ở
   `S_NEW` **và `S_SCREENING`**"). Cả P1 5.1.1 lẫn 00-README đều ghi "`FORBIDDEN` luôn thắng" → hiểu
   theo chữ thì E9/E2 ở B2 vẫn ném `IllegalTransition`, ticket kẹt ở `S_SCREENING` — đúng lỗi L-13 mà
   D-29 sinh ra để sửa, và làm đỏ test P1 mục 11 "lỗi giả ở B2 → `S_ESCALATED` E9". B02 mục 7 (dòng
   163) cũng ghi "(cần nới cho dòng E2 ở trên khi chốt)" nhưng chưa ai nới. Quy tắc 1 (`S_SCREENING` →
   `S_SCREENING`) cũng va với chuyển cấm này theo chữ, nhưng hiện chưa node nào dùng.
9. ~~`build_action` chưa có~~ — **đã chốt** (25/09/2026): làm cùng B11 ở Phase 3 (cần
   `config/action_metadata.yaml` + `REQUIRED_SLOTS`); `domain/action.py` hiện chỉ có `Action`.
10. ~~Hợp đồng 6 va với `effects.once(…, approvals.create, …)`~~ — **đã giải quyết** (25/09/2026):
    01 mục 4.3 + P1 mục 5.3 bỏ hợp đồng 6 khỏi import-linter, thay bằng test AST
    `backend/tests/unit/test_side_effects_ast.py` (quét `graph/nodes/**`, tham chiếu tới
    `SIDE_EFFECT_FUNCS` ngoài vị trí `fn` của `effects.once` → đỏ; có mẫu node giả chứng minh bắt được).
    `tickets` = `backend/app/db/tickets.py` (chưa tạo). B15 đổi sang `approvals.notify_approver`.
11. ~~Wildcard `*_write`~~ — **đã giải quyết** (25/09/2026): 01 mục 4.3 chốt liệt kê tường minh
    `{ad,vpn,software,fileserver}_write`; `backend/tests/unit/test_write_adapters_listed.py` đỏ nếu có
    `tools/adapters/*_write.py` chưa khai báo trong `.importlinter`.
12. ~~Cách hiện thực cấm 2/3/4~~ — **đã chốt** (25/09/2026, P1 mục 5.1.1): cấm 2 chặn mọi
    `approval_result != "approved"`; cấm 3 chặn cả khi thiếu `action_plan_hash`; cấm 4 ở domain chỉ
    kiểm `step`/`event`, phần audit cùng transaction thuộc `goto()` Phase 2. `approval_result` đã có
    trong P1 `TicketState`. Cấm 1 giữ đúng chữ (`risk` rỗng không bị cấm 1 chặn).
