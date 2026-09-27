# Sơ đồ kiến trúc hệ thống (artifact)

Link: https://claude.ai/artifact/FKyrELziD9MkPEQqH8CkMz

Sơ đồ khối trực quan (HTML/SVG, theo phong cách "namespace box + icon + mũi tên" tham khảo từ một sơ đồ K8s mẫu người dùng gửi, nhưng vẽ đúng kiến trúc thật của đồ án — không dùng Kubernetes) thể hiện:

- **T1 — Cổng vào & bảo mật** (AuthN JWT 15' + refresh xoay vòng + MFA Trưởng BP · RBAC `require(perm)` · kiểm tra theo bản ghi `can_*()` chặn IDOR · privacy guard che PII/bí mật L0–L1 · rate limit): chạy như middleware HTTP, đứng trước mọi request vào graph — B1 trong tầng Agent chỉ *chốt lại* danh tính đã xác thực, không tự xác thực lại.
- 4 tầng trách nhiệm nghiệp vụ (sau T1): **Frontend** (React, 4 vai trò) → **Agent** (M1–M4) → **Kiểm soát** (M5–M7) → **B17** (điểm ghi duy nhất) → hệ thống ngoài (mock AD/VPN/Phần mềm/File), cộng tầng thứ tư song song **Monitor (M9)** chỉ đọc, không quyết định.
- Nhãn **modular monolith**: Agent + Kiểm soát + B17 chạy chung một tiến trình/image (`backend/`), khởi chạy 2 process (API+graph-runner, worker) — không phải microservices. Chỉ 3 thành phần tách service riêng vì lý do kỹ thuật cụ thể: `ml-service`, `mock`, `frontend`.
- Hạ tầng phụ trợ (4 khối): LLM Gateway (router fast/strong, cache, retry/fallback) · **ml-service** (D-09, FastAPI riêng, uvicorn 1 worker, cổng 8200 — phục vụ bge-m3 embed, bge-reranker-v2-m3, injection-clf, intent-clf; RAG/Qdrant chỉ lưu vector, không tự tính) · RAG data (Qdrant + hybrid BM25/RRF) · PostgreSQL — **22 bảng** (tickets, audit_logs, approvals, checkpoints + 5 bảng mới: security_events, llm_cache, wait_deadlines, side_effects, child_notices).
- Dải triển khai: Docker Compose (Caddy reverse proxy, uvicorn, worker APScheduler) + tóm tắt CI/CD (GitHub Actions → GHCR → staging → smoke test).
- Legend màu theo tầng/thành phần (11 mục, gồm T1 và ml-service) + phân biệt mũi tên "gọi/ghi" (nét liền) vs "chỉ đọc — Monitor" (nét đứt).

Nguồn nội dung: `huong-dan-xay-dung-he-thong-2.md` mục 3 (Kiến trúc tổng thể) và mục 17.9 (Tầng Monitor — sơ đồ 4 tầng); `build/02-cac-tang-he-thong.md` (mô hình 8 tầng T0–T7, đặc biệt T1 và T6); `build/nen-tang/P6-auth-bao-mat.md` (chi tiết T1); `build/nen-tang/P4-ml-service.md` (chi tiết ml-service); `build/01-kien-truc-project.md` (D-13 modular monolith); `build/nen-tang/P7-db-thay-doi.md` (DB 22 bảng).

Cập nhật lại sơ đồ này khi kiến trúc đổi: đọc lại artifact (Artifact tool, action "read", cùng URL) rồi republish cùng URL để giữ nguyên link.

**Đã cập nhật theo bộ `build/` (26/09/2026, Version 5):** đã thêm khối `ml-service` (D-09), tầng T1 "Cổng vào & bảo mật", nhãn "modular monolith" (D-13), và DB 22 bảng — đúng theo patch ghi ở `claude/bo-sung-bo-tai-lieu-build.md` Phần G. Cập nhật thực hiện chỉ dựa trên tài liệu project (theo yêu cầu người dùng), chưa đối chiếu với code thật trên máy — nếu sau này `backend/app/db/models.py` hoặc migration thực tế có sai khác so với các file `build/`, cần đối chiếu lại và vá tiếp.
