"""Hằng số của RAG ingest — MỘT nguồn (P3 §7; D-21; 3-Q15; PLAN-3b mục 4.0).

`RETRIEVAL_THRESHOLD` KHÔNG lặp ở đây — đọc `get_policy().constants.RETRIEVAL_THRESHOLD` (truyền qua deps).
"""

from datetime import timedelta, timezone

CHUNK_TOKENS_MIN = 120  # D-21: đoạn < 120 token nội dung → thử gộp
CHUNK_TOKENS_MAX = 380  # D-21: trần token NỘI DUNG
CHUNK_TEXT_MAX = 480  # D-21: trần cả đoạn (tiền tố + nội dung, gồm token đặc biệt)
COUNT_BATCH = 256  # ≤ 256 văn bản mỗi lời gọi đếm token (khớp MlClient)
UPSERT_BATCH = 64
INGEST_EMBED_GROUP = 1  # Q-3b-1: số văn bản mỗi lời gọi embed khi ingest
DENSE_DIM = 1024
ALIAS = "kb_current"
COLLECTION_RE = r"^kb_[0-9a-f]{64}$"
GATE_TOP_DOCS = 5
GATE_MIN_RECALL = 0.80  # 3-Q15 (b)
GATE_MAX_FALSE_GROUNDING = 0.05  # 3-Q15 (b)
GATE_MAX_DELTA = 0.05  # 3-Q15 (c)
GATE_EPS = 1e-9
KB_TZ = timezone(timedelta(hours=7))  # Q-3b-13: "tương lai" của updated_at so theo giờ VN (không DST)
INGEST_LOCK_KEY = 0x6B62_696E  # Q-3b-15: pg_try_advisory_lock — một lượt ingest mỗi lúc
