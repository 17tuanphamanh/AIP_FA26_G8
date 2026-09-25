# Sơ đồ kiến trúc hệ thống (artifact)

Link: https://claude.ai/artifact/FKyrELziD9MkPEQqH8CkMz

Sơ đồ khối trực quan (HTML/SVG, theo phong cách "namespace box + icon + mũi tên" tham khảo từ một sơ đồ K8s mẫu người dùng gửi, nhưng vẽ đúng kiến trúc thật của đồ án — không dùng Kubernetes) thể hiện:

- 4 tầng trách nhiệm: **Frontend** (React, 4 vai trò) → **Agent** (M1–M4) → **Kiểm soát** (M5–M7) → **B17** (điểm ghi duy nhất) → hệ thống ngoài (mock AD/VPN/Phần mềm/File), cộng tầng thứ tư song song **Monitor (M9)** chỉ đọc, không quyết định.
- Hạ tầng phụ trợ: LLM Gateway (router fast/strong, cache, retry/fallback), RAG data (Qdrant + bge-m3 + bge-reranker-v2-m3 + BM25/RRF), PostgreSQL (tickets, audit_logs, approvals, policy_versions, checkpoints, turns/spans/llm_calls, escalations).
- Dải triển khai: Docker Compose (Caddy reverse proxy, uvicorn, worker APScheduler) + tóm tắt CI/CD (GitHub Actions → GHCR → staging → smoke test).
- Legend màu theo tầng/thành phần + phân biệt mũi tên "gọi/ghi" (nét liền) vs "chỉ đọc — Monitor" (nét đứt).

Nguồn nội dung: `huong-dan-xay-dung-he-thong-2.md` mục 3 (Kiến trúc tổng thể) và mục 17.9 (Tầng Monitor — sơ đồ 4 tầng), cộng bảng module/công nghệ ở mục 3–4 và thiết kế DB (hiện hành 22 bảng, `build/nen-tang/P7-db-thay-doi.md`).

Cập nhật lại sơ đồ này khi kiến trúc đổi: đọc lại artifact (Artifact tool, action "read", cùng URL) rồi republish cùng URL để giữ nguyên link.

**Artifact chưa cập nhật theo bộ `build/` (25/09/2026):** còn thiếu khối `ml-service` (D-09), tầng T1 "Cổng vào & bảo mật" (AuthN/RBAC/privacy guard), nhãn "modular monolith" (D-13), và DB 22 bảng. Việc cập nhật ghi ở `claude/bo-sung-bo-tai-lieu-build.md` Phần G.
