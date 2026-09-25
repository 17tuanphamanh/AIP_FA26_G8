#!/bin/sh
# Tạo 3 role Postgres (P6 mục 6, P7 mục 3) — chạy bằng superuser MỘT LẦN khi khởi tạo volume
# (docker-entrypoint-initdb.d). Cũng được conftest testcontainers dùng lại.
# Mật khẩu lấy từ env, không nằm trong migration. app_migrate làm owner schema public;
# Alembic chạy bằng app_migrate (không superuser) để tạo bảng, trigger, grant.
set -eu

: "${PG_MIGRATE_PASSWORD:?thiếu PG_MIGRATE_PASSWORD}"
: "${PG_RW_PASSWORD:?thiếu PG_RW_PASSWORD}"
: "${PG_MONITOR_PASSWORD:?thiếu PG_MONITOR_PASSWORD}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v db="$POSTGRES_DB" \
  -v migrate_pw="$PG_MIGRATE_PASSWORD" \
  -v rw_pw="$PG_RW_PASSWORD" \
  -v monitor_pw="$PG_MONITOR_PASSWORD" <<'SQL'
CREATE ROLE app_migrate LOGIN PASSWORD :'migrate_pw';
CREATE ROLE app_rw      LOGIN PASSWORD :'rw_pw';
CREATE ROLE app_monitor LOGIN PASSWORD :'monitor_pw';

REVOKE ALL ON DATABASE :"db" FROM PUBLIC;
GRANT CONNECT ON DATABASE :"db" TO app_migrate, app_rw, app_monitor;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO app_migrate;
GRANT USAGE ON SCHEMA public TO app_rw, app_monitor;
SQL
