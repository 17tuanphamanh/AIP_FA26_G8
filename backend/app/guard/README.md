B2 — chuẩn hoá, privacy guard, mẫu injection, phân loại injection. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- `privacy.py` (2b-3): port `PrivacyGuard`, `RedactionResult` (B02 mục 4), `NotRedactingGuard` — bản KHÔNG che, chỉ nạp khi `APP_ENV` ∈ {dev, test} (2b-Q2). Guard thật: Phase 3.
