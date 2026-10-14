#!/usr/bin/env bash
# `make verify` (phase4 mục 4.4; Q-4-I, Q-4-T) — MỘT lệnh cho mọi DỪNG: lint → test → up → cổng theo G → trả stack về .env.
#
#   make verify              # G=3 (mặc định)
#   make verify G=23         # gate2 + gate3 (theo thứ tự chữ số)
#   make verify G=234        # + gate4 (APPROVAL_SLA_MINUTES_DEV=2 chỉ cho bước gate4 — 4d DỪNG 2)
#   make verify G=2345       # + gate5 (Phase 5 T24): nạp KB THẬT (kb/) ngay trước gate5 → sau lượt chạy stack ở KB thật (Q-T24-1)
#   make verify G=0          # chỉ lint + test (không đụng stack)
#   make verify G=3 BENCH=1  # thêm bench checkpoint (P6 — Postgres testcontainers, không dùng DB stack)
#
# gate2 cần FAKE_SCENARIO ĐẶT, gate3/gate4 cần KHÔNG đặt (G4-24); gate4 cần APPROVAL_SLA_MINUTES_DEV=2, gate2/gate3 rỗng (= mặc định
# 30 phút — kết quả không phụ thuộc .env có đặt hay không, PLAN-4d TQ-12) — script tạo lại backend+worker bằng BIẾN SHELL cho từng
# cổng (compose nội suy `${FAKE_SCENARIO:-}`, biến shell thắng `--env-file`), không bao giờ đọc/sửa `.env` (chỉ `test -f`).
# Bước 8 (trả backend+worker về cấu hình `.env`) LUÔN chạy nếu đã qua bước 3, kể cả khi đỏ giữa chừng hoặc Ctrl-C.
#
# Luật: không `down -v`, không `volume rm|prune`; không in giá trị biến môi trường (chỉ tên/nhãn enum); không `set -x`;
# APP_ENV của backend phải là `dev`. KB: gate3/gate4 cần KB fixture, gate5 cần KB THẬT (6 bài quy trình account/software/access — KB
# fixture chỉ có VPN → B11 S0-P10 ra E3); script nhớ KB đang nạp và chỉ nạp lại khi cổng kế tiếp cần KB khác (G không có 5 → như cũ). Đầu ra: `.verify/run-<giờ>.log` (toàn bộ) + `.verify/summary.txt` (ghi đè) — agent đọc
# summary. Biến vào (từ Makefile): G, BENCH, COMPOSE, MAKE_BIN. Tương thích bash 3.2 (macOS).
#
# Mọi hàm bước được gọi trong `if`/`||` — ở đó `set -e` KHÔNG có hiệu lực, nên MỖI lệnh con tự `|| return 1` (không thì một
# lệnh con đỏ mà lệnh sau xanh → cả bước "xanh oan").
#
# Phase 4 4d DỪNG 2 (Q-4d-4): trên macOS tự giữ máy thức (`caffeinate -i -w $$` — hết khi script thoát) và CẢNH BÁO khi chạy pin
# (Mac ngủ giữa lượt → hạn lượt theo đồng hồ tường hết → E2 `turn_budget_exceeded`). Không có `caffeinate` → bỏ qua.

set -euo pipefail

G="${G:-3}"
BENCH="${BENCH:-0}"
COMPOSE="${COMPOSE:-docker compose --env-file .env}"  # chuỗi lệnh — CỐ Ý không quote khi gọi (tách từ)
MAKE="${MAKE_BIN:-make}"  # Makefile truyền MAKE_BIN (không dùng biến MAKE của make — xem chú thích target verify)
HEALTH_URL="http://127.0.0.1:8000/api/health"
WAIT_S=180
KNOWN_GATES="02345"

if ! [[ "$G" =~ ^[0-9]+$ ]]; then
  echo "G phải là chuỗi chữ số (vd 3, 23, 0) — nhận: '$G'" >&2
  exit 2
fi
for ((i = 0; i < ${#G}; i++)); do
  if [[ "$KNOWN_GATES" != *"${G:i:1}"* ]]; then
    echo "G=$G: chữ số '${G:i:1}' chưa có cổng (có: $KNOWN_GATES)" >&2
    exit 2
  fi
done

mkdir -p .verify
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG=".verify/run-$STAMP.log"
SUMMARY=".verify/summary.txt"
ROWS=""
FAILED_STEP=""
FAILED_NAME=""
FAILED_OUT=""
RESTORE=0
RESTORED=0
KB_NOW="" # KB script đã nạp trong lượt này: "" | fixture | real (T24 Q-T24-1)
STEP_DUR=0
START_HMS="$(date +%H:%M:%S)"
POWER_NOTE=""
: >"$LOG"

say() { printf '%s\n' "$*" | tee -a "$LOG"; }

keep_awake() { # Q-4d-4 — chỉ macOS; mọi lỗi ở đây chỉ là ghi chú, không dừng verify
  if [[ "$(uname -s 2>/dev/null || true)" != "Darwin" ]]; then
    return 0
  fi
  if command -v caffeinate >/dev/null 2>&1; then
    caffeinate -i -w $$ >/dev/null 2>&1 &
    say "caffeinate: bật (giữ máy thức tới khi verify thoát)"
    POWER_NOTE="caffeinate bật"
  else
    say "caffeinate: không có — bỏ qua"
    POWER_NOTE="không có caffeinate"
  fi
  local batt
  batt="$({ pmset -g batt 2>/dev/null || true; } | head -1)" || batt=""
  if [[ "$batt" == *"Battery Power"* ]]; then
    say "CẢNH BÁO: máy đang chạy PIN — cắm sạc, mở nắp (Mac ngủ giữa lượt → E2 turn_budget_exceeded)"
    POWER_NOTE="$POWER_NOTE; CẢNH BÁO chạy pin"
  fi
}

fmt_dur() {
  local s=$1
  if ((s >= 60)); then printf '%dm%02ds' $((s / 60)) $((s % 60)); else printf '%ds' "$s"; fi
}

add_row() { # add_row <#> <tên> <PASS|FAIL|BỎ QUA> <giây> <ghi chú>
  ROWS="${ROWS}| $1 | $2 | $3 | $(fmt_dur "$4") | $5 |"$'\n'
}

fail() { # fail <#> <tên> <file đầu ra của bước>
  FAILED_STEP=$1
  FAILED_NAME=$2
  FAILED_OUT=$3
}

# run_step <#> <tên> <file đầu ra> <lệnh hoặc hàm...> — đầu ra vào file riêng + log chung; trả mã của lệnh.
run_step() {
  local num=$1 name=$2 out=$3 rc=0 t0=$SECONDS
  shift 3
  say "==== bước $num: $name"
  "$@" >"$out" 2>&1 || rc=$?
  cat "$out" >>"$LOG"
  STEP_DUR=$((SECONDS - t0))
  say "==== bước $num: $([[ $rc == 0 ]] && echo PASS || echo "FAIL (mã $rc)") ($(fmt_dur "$STEP_DUR"))"
  return "$rc"
}

pytest_totals() { # "backend 3166 passed · mock 94 passed · ml 77 passed, 5 deselected" từ đầu ra `make test`
  { grep -E '^[0-9]+ (passed|failed|error)|^=+ [0-9]+ (passed|failed|error).* =+$' "$1" || true; } \
    | sed -E 's/^=+ //; s/ =+$//; s/ in [0-9.]+s.*$//' \
    | awk 'BEGIN { split("backend mock ml", n, " ") } { printf "%s%s %s", (NR > 1 ? " · " : ""), n[NR], $0 }'
}

gate_totals() { # "8 PASS, 0 FAIL" từ dòng tổng của gate2/gate3
  { grep -E '^=+ [0-9]+ PASS, [0-9]+ FAIL =+$' "$1" || true; } | tail -1 | sed -E 's/^=+ //; s/ =+$//'
}

wait_health() {
  local i
  for ((i = 0; i < WAIT_S; i += 2)); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      echo "/api/health: 200"
      return 0
    fi
    sleep 2
  done
  echo "/api/health chưa 200 sau ${WAIT_S}s" >&2
  return 1
}

recreate() { # recreate <FAKE_SCENARIO> <FAKE_NODE_DELAY> <APPROVAL_SLA_MINUTES_DEV> — tạo lại backend+worker với biến shell (rỗng = không đặt)
  # shellcheck disable=SC2086  # $COMPOSE là chuỗi lệnh, cần tách từ
  env FAKE_SCENARIO="$1" FAKE_NODE_DELAY="$2" APPROVAL_SLA_MINUTES_DEV="$3" \
    $COMPOSE up -d --force-recreate --no-deps --wait --wait-timeout "$WAIT_S" backend worker || return 1
  wait_health || return 1
}

check_app_env() { # chốt an toàn như gate2/gate3: APP_ENV của backend = dev (chỉ so nhãn, không in biến nào khác)
  local v
  # shellcheck disable=SC2086
  v="$($COMPOSE exec -T backend printenv APP_ENV 2>/dev/null || true)"
  if [[ "$v" != "dev" ]]; then
    echo "APP_ENV của backend không phải dev — dừng (không chạy cổng trên môi trường khác)" >&2
    return 1
  fi
  echo "APP_ENV=dev"
}

step_up() { "$MAKE" up || return 1; check_app_env || return 1; }
step_ingest() { "$MAKE" ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated || return 1; }
step_ingest_real() { "$MAKE" ingest KB_DIR=kb || return 1; } # T24 Q-T24-1: KB thật cho gate5
step_gate3() { recreate "" "" "" || return 1; "$MAKE" gate3 S=all || return 1; }
step_gate2() { recreate approval 40 "" || return 1; "$MAKE" gate2 S=all || return 1; }
step_gate4() { recreate "" "" 2 || return 1; "$MAKE" gate4 S=all || return 1; }
step_gate5() { recreate "" "" "" || return 1; "$MAKE" gate5 S=all || return 1; }
step_bench() { PYTHONPATH=backend uv run python -m tests.stack.bench_checkpoint || return 1; }
step_restore() { # bước 8 — không biến shell nào đè FAKE_* / APPROVAL_SLA_MINUTES_DEV → đúng cấu hình .env
  # shellcheck disable=SC2086
  env -u FAKE_SCENARIO -u FAKE_NODE_DELAY -u APPROVAL_SLA_MINUTES_DEV \
    $COMPOSE up -d --force-recreate --no-deps --wait --wait-timeout "$WAIT_S" backend worker || return 1
  wait_health || return 1
}

restore() {
  if ((RESTORE == 0 || RESTORED == 1)); then
    return 0
  fi
  RESTORED=1
  local out=".verify/step8.out"
  if run_step 8 "trả về cấu hình .env" "$out" step_restore; then
    add_row 8 "trả về .env" PASS "$STEP_DUR" "backend+worker theo .env"
  else
    add_row 8 "trả về .env" FAIL "$STEP_DUR" "chạy tay: $COMPOSE up -d --force-recreate --no-deps backend worker"
    [[ -n "$FAILED_STEP" ]] || fail 8 "trả về .env" "$out"
  fi
}

ensure_ingest() { # bước 4 — trước cổng cần KB fixture (3 hoặc 4) khi KB đang nạp không phải fixture (G không có 5: MỘT lần)
  local out=".verify/step4.out"
  if [[ "$KB_NOW" == "fixture" ]]; then
    return 0
  fi
  if run_step 4 "ingest KB fixture" "$out" step_ingest; then
    add_row 4 ingest PASS "$STEP_DUR" "$({ grep -E 'KB không đổi|kb_version=' "$out" || true; } | tail -1 | cut -c1-90)"
    KB_NOW=fixture
  else
    add_row 4 ingest FAIL "$STEP_DUR" ""
    fail 4 ingest "$out"
    return 1
  fi
}

ensure_ingest_real() { # bước 11 — trước gate5 khi KB đang nạp không phải KB thật (T24 Q-T24-1)
  local out=".verify/step11.out"
  if [[ "$KB_NOW" == "real" ]]; then
    return 0
  fi
  if run_step 11 "ingest KB thật (kb/)" "$out" step_ingest_real; then
    add_row 11 "ingest KB thật" PASS "$STEP_DUR" "$({ grep -E 'KB không đổi|kb_version=' "$out" || true; } | tail -1 | cut -c1-90)"
    KB_NOW=real
  else
    add_row 11 "ingest KB thật" FAIL "$STEP_DUR" ""
    fail 11 "ingest KB thật" "$out"
    return 1
  fi
}

run_gate() { # run_gate <chữ số> — 0 nếu xanh; đỏ → ghi fail, trả 1
  local out
  case "$1" in
    0) return 0 ;;
    3)
      ensure_ingest || return 1
      out=".verify/step5.out"
      if run_step 5 "gate3 (FAKE_SCENARIO không đặt)" "$out" step_gate3; then
        add_row 5 gate3 PASS "$STEP_DUR" "$(gate_totals "$out")"
      else
        add_row 5 gate3 FAIL "$STEP_DUR" "$(gate_totals "$out")"
        fail 5 gate3 "$out"
        return 1
      fi
      ;;
    2)
      out=".verify/step6.out"
      if run_step 6 "gate2 (FAKE_SCENARIO=approval, FAKE_NODE_DELAY=40)" "$out" step_gate2; then
        add_row 6 gate2 PASS "$STEP_DUR" "$(gate_totals "$out")"
      else
        add_row 6 gate2 FAIL "$STEP_DUR" "$(gate_totals "$out")"
        fail 6 gate2 "$out"
        return 1
      fi
      ;;
    4)
      ensure_ingest || return 1
      out=".verify/step10.out"
      if run_step 10 "gate4 (FAKE_SCENARIO không đặt, APPROVAL_SLA_MINUTES_DEV=2)" "$out" step_gate4; then
        add_row 10 gate4 PASS "$STEP_DUR" "$(gate_totals "$out")"
      else
        add_row 10 gate4 FAIL "$STEP_DUR" "$(gate_totals "$out")"
        fail 10 gate4 "$out"
        return 1
      fi
      ;;
    5)
      ensure_ingest_real || return 1
      out=".verify/step12.out"
      if run_step 12 "gate5 (FAKE_SCENARIO không đặt, KB thật)" "$out" step_gate5; then
        add_row 12 gate5 PASS "$STEP_DUR" "$(gate_totals "$out")"
      else
        add_row 12 gate5 FAIL "$STEP_DUR" "$(gate_totals "$out")"
        fail 12 gate5 "$out"
        return 1
      fi
      ;;
  esac
}

finish() {
  local head dirty env_file conclusion
  head="$(git rev-parse --short=7 HEAD 2>/dev/null || echo '?')"
  dirty="$({ git status --porcelain 2>/dev/null || true; } | wc -l | tr -d ' ')"  # pipefail: git lỗi không được giết summary
  env_file=".env.example"
  if test -f .env; then env_file=".env"; fi
  if [[ -z "$FAILED_STEP" ]]; then
    conclusion="KẾT LUẬN: XANH"
  else
    conclusion="KẾT LUẬN: ĐỎ ở bước $FAILED_STEP ($FAILED_NAME) — 30 dòng cuối log: $LOG"
  fi
  {
    echo "verify G=$G BENCH=$BENCH HEAD=$head dirty=$dirty env=$env_file bắt đầu=$START_HMS kết thúc=$(date +%H:%M:%S)"
    echo "| # | Bước | Kết quả | Thời gian | Ghi chú |"
    printf '%s' "$ROWS"
    echo "$conclusion"
    if [[ -n "$FAILED_STEP" ]]; then
      echo "---- 30 dòng cuối của bước $FAILED_STEP ----"
      tail -30 "$FAILED_OUT"
    fi
  } >"$SUMMARY"
  tee -a "$LOG" <"$SUMMARY"
}

on_signal() {
  say "!! bị ngắt — trả stack về .env rồi thoát"
  [[ -n "$FAILED_STEP" ]] || fail "-" "bị ngắt" "$LOG"
  restore || true
  finish
  exit 130
}
trap on_signal INT TERM HUP # HUP: đóng terminal / mất ssh giữa chừng vẫn trả stack về .env (soát 4d DỪNG 2)

main() {
  local out i note
  keep_awake
  if test -f .env; then note=".env có"; else note="không có .env — dùng .env.example"; fi
  add_row 0 "chuẩn bị" PASS 0 "$note${POWER_NOTE:+; $POWER_NOTE}"

  out=".verify/step1.out"
  if run_step 1 lint "$out" "$MAKE" lint; then add_row 1 lint PASS "$STEP_DUR" ""; else
    add_row 1 lint FAIL "$STEP_DUR" ""; fail 1 lint "$out"; return 1; fi

  out=".verify/step2.out"
  if run_step 2 test "$out" "$MAKE" test; then add_row 2 test PASS "$STEP_DUR" "$(pytest_totals "$out")"; else
    add_row 2 test FAIL "$STEP_DUR" "$(pytest_totals "$out")"; fail 2 test "$out"; return 1; fi

  if [[ ! "$G" =~ ^0+$ ]]; then # có ít nhất một cổng → cần stack
    out=".verify/step3.out"
    if run_step 3 up "$out" step_up; then add_row 3 up PASS "$STEP_DUR" "APP_ENV=dev"; else
      add_row 3 up FAIL "$STEP_DUR" ""; fail 3 up "$out"; return 1; fi
    RESTORE=1 # đã qua bước 3: từ đây, dù đỏ ở đâu cũng trả stack về .env
    for ((i = 0; i < ${#G}; i++)); do
      run_gate "${G:i:1}" || return 1
    done
  fi

  if [[ "$BENCH" == "1" ]]; then
    out=".verify/step7.out"
    if run_step 7 "bench checkpoint (testcontainers)" "$out" step_bench; then
      add_row 7 bench PASS "$STEP_DUR" "$({ grep -E '^(5|20|50) KB' "$out" || true; } | awk '{printf "%s%s", (NR > 1 ? "; " : ""), $0}' | cut -c1-150)"
    else
      add_row 7 bench FAIL "$STEP_DUR" ""; fail 7 bench "$out"; return 1
    fi
  fi
}

main || true
restore || true

# 9 — CI (không bắt buộc): gh lỗi (vd sandbox chặn keychain) → "bỏ qua (gh)"
branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
if ci="$(gh run list --branch "$branch" -L 1 2>/dev/null)" && [[ -n "$ci" ]]; then
  add_row 9 "CI (gh)" PASS 0 "$(printf '%s' "$ci" | cut -f1-2,7 | tr '\t' ' ')"
else
  add_row 9 "CI (gh)" "BỎ QUA" 0 "bỏ qua (gh)"
fi

finish
[[ -z "$FAILED_STEP" ]]
