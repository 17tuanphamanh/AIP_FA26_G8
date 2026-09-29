Test đầu–cuối qua API với ScriptedLLM. Xem docs/spec/build/01-kien-truc-project.md mục 3.

- `test_gate3_vpn.py` (cổng 3, phase3 11.5 h1–h19 + h15b + h11 lúc 20:00): API + runner + worker thật, mock thật, Postgres +
  Qdrant (fixture của `integration/conftest.py`), KB fixture ingest thật, FakeMl, ScriptedLLM — môi trường ở `gate3_env.py`.
  Cần Docker (testcontainers) và mở cổng local: chạy trong `make test`, không chạy được trong sandbox.
