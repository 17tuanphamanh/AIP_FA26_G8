"""Chạy trước mọi test (conftest ở rootdir nạp trước mọi module test): test không chạm `.env` thật.

Hai đường chạm, chặn cả hai:
  1. pytest tự duyệt thư mục gốc (Dir.collect) và gọi `is_dir()` lên TỪNG mục, kể cả `.env` —
     tức là stat file bí mật. `collect_ignore_glob` được xét TRƯỚC `is_dir()` nên chặn được;
     `norecursedirs` thì không (xét sau).
  2. `app.settings.Settings` đọc file env theo `APP_ENV_FILE` — đặt rỗng để tắt hẳn, test chỉ
     thấy biến môi trường do chính test đặt.

Kèm: `APP_ENV=test` (2b-Q2): thiếu APP_ENV thì app từ chối nạp thành phần giả (guard không che,
   người duyệt giả). Test nào kiểm luật fail-closed tự truyền `app_env` khác.
"""

import os

os.environ["APP_ENV_FILE"] = ""
os.environ["APP_ENV"] = "test"

collect_ignore_glob = [".env*"]
