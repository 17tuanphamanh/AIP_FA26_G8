#!/usr/bin/env bash
# DB mới cho buổi demo mà GIỮ KB (V16/O1, 12/11 — báo cáo soát 10 mục V1).
#
#   bash scripts/ops/db_moi_giu_kb.sh          # chỉ IN các lệnh sẽ chạy (mặc định)
#   bash scripts/ops/db_moi_giu_kb.sh --chay   # chạy thật
#   make db-moi-giu-kb ARGS=--chay             # như trên
#
# Làm gì: xoá ca cũ (volume `servicedesk_pgdata`: ticket, audit, hàng chờ L2, chi LLM, phiên, OTP) nhưng GIỮ Qdrant
# (`servicedesk_qdrant`) → ingest đi nhánh "ghi bù DB" từ metadata collection, không embed lại (rag/ingest/pipeline.py bước 5).
# Không xoá được ca bằng SQL: audit_logs, transaction_log… có trigger chặn UPDATE/DELETE/TRUNCATE.
#
# Chỉ đụng postgres, backend, worker (+ đặt lại mock):
# - KHÔNG `docker compose down`, KHÔNG dựng lại ml-service / qdrant → tránh bẫy MODELS_DIR (dựng lại ml-service ở thư mục
#   không có ./models thì ml-service không lên). KHÔNG `make up`, không build image: dùng image đang chạy.
# - Xoá đúng MỘT volume, sau khi kiểm nhãn compose của nó là `servicedesk/pgdata`; sai nhãn → dừng, không xoá gì.
#
# Chạy ở máy đang chạy stack (compose project `servicedesk`), cùng môi trường shell với lúc deploy (vd `DOCKER_CONFIG`). Compose
# tự đọc `.env` ở thư mục gốc repo; script không đọc `.env`. Owner KB chưa có dòng `users` → ingest cảnh báo "owner … = NULL"
# (cột này không được code nào đọc). Sau script: đặt OTP quan.tm với `--user-id it_mgr01` (in ở cuối) — không quay output đó.
set -euo pipefail

PROJECT=servicedesk
VOLUME="${PROJECT}_pgdata"
WANT_LABEL="${PROJECT}/pgdata"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
  sed -n '2,5p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

CHAY=0
for arg in "$@"; do
  case "$arg" in
    --chay) CHAY=1 ;;
    -h | --help) usage; exit 0 ;;
    *) echo "Tham số lạ: $arg (chỉ có --chay)" >&2; usage >&2; exit 2 ;;
  esac
done

DC=(docker compose -p "$PROJECT")
cd "$ROOT"  # compose tìm docker-compose.yml + .env theo thư mục hiện tại

# In lệnh; có --chay thì chạy luôn (dừng ở lệnh lỗi đầu tiên — set -e).
step() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [ "$CHAY" = 1 ]; then
    "$@"
  fi
}

check_volume() {
  echo "+ docker volume inspect -f '{{index .Labels \"com.docker.compose.project\"}}/{{index .Labels \"com.docker.compose.volume\"}}' $VOLUME"
  if [ "$CHAY" = 0 ]; then
    echo "  (phải in đúng: $WANT_LABEL — sai thì dừng, không xoá)"
    return 0
  fi
  local got
  got="$(docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}/{{index .Labels "com.docker.compose.volume"}}' "$VOLUME" 2>/dev/null || true)"
  if [ "$got" != "$WANT_LABEL" ]; then
    echo "DỪNG: volume $VOLUME có nhãn '${got}', không phải '$WANT_LABEL' — không xoá gì. Kiểm 'docker volume ls'." >&2
    exit 1
  fi
}

if [ "$CHAY" = 0 ]; then
  echo "# Chế độ IN LỆNH (chưa chạy gì). Chạy thật: bash scripts/ops/db_moi_giu_kb.sh --chay"
fi
echo "# 1. Dừng backend + worker (ngừng ghi DB); gỡ container postgres để giải phóng volume"
step "${DC[@]}" stop backend worker
step "${DC[@]}" rm -f -s postgres
echo "# 2. Kiểm nhãn rồi xoá ĐÚNG volume $VOLUME (giữ ${PROJECT}_qdrant)"
check_volume
step docker volume rm "$VOLUME"
echo "# 3. Postgres mới (init-roles chạy vì volume trống) → migration → backend + worker"
step "${DC[@]}" up -d --wait --no-deps postgres
step "${DC[@]}" run --rm --no-deps backend alembic upgrade head
step "${DC[@]}" up -d --wait --no-deps backend worker
echo "# 4. Ingest: KB không đổi → chỉ ghi bù DB (phải in 'đã ghi bù DB cho kb_…' hoặc 'KB không đổi')"
step "${DC[@]}" run --rm --no-deps -v "$ROOT/kb:/srv/kb:ro" backend python -m app.rag.ingest.cli --kb-dir /srv/kb
echo "# 5. Mock về seed"
step "${DC[@]}" exec -T mock python -m app.seed reset

cat <<EOF
# Việc tay tiếp theo (không quay output lệnh OTP):
#   docker compose -p $PROJECT exec backend python -m app.auth.mfa enroll quan.tm --user-id it_mgr01 --by <ten> --reason demo
#   curl -s http://127.0.0.1:8000/api/health     # status=ok, kb.status=ready, warnings=[]
EOF
