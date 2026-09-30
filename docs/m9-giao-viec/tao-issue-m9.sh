#!/usr/bin/env bash
# Tạo issue M9 chia hai luồng (epic + A0–A4 của Lưu Dương + B0–B3 của Tạ Duy Anh) bằng gh.
#   bash docs/m9-giao-viec/tao-issue-m9.sh          # chạy thử: chỉ in việc sẽ làm, không đụng GitHub (ngoài đọc)
#   bash docs/m9-giao-viec/tao-issue-m9.sh --run    # tạo thật
#   ASSIGNEE_A=<github Dương> ASSIGNEE_B=<github Duy Anh> bash ... --run   # gán người (tuỳ chọn, phải là collaborator)
# Chạy lại an toàn: issue đã có đúng tiêu đề thì dùng lại số, chỉ cập nhật thân.
# Issue kế hoạch cũ một người ([M9-0]…[M9-7], epic cũ) nếu còn mở → comment trỏ sang epic mới rồi đóng (not planned).
set -euo pipefail

REPO="${REPO:-17tuanphamanh/AIP_FA26_G8}"
ASSIGNEE_A="${ASSIGNEE_A:-}"
ASSIGNEE_B="${ASSIGNEE_B:-}"
DIR="$(cd "$(dirname "$0")" && pwd)/issues"
RUN=0
[[ "${1:-}" == "--run" ]] && RUN=1

command -v gh >/dev/null || { echo "Thiếu gh"; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh chưa đăng nhập: gh auth login"; exit 1; }
[[ "$(gh repo view "$REPO" --json hasIssuesEnabled -q .hasIssuesEnabled)" == "true" ]] \
  || { echo "Repo $REPO chưa bật Issues (Settings → General → Features → Issues)"; exit 1; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

# key|file|labels|assignee-var|title
ITEMS=(
  "EPIC|00-epic.md|m9,epic||[M9] Tầng Monitor (backend) — hai luồng A/B"
  "A0|A0.md|m9,backend,luong-a|A|[M9-A0] Nền chỉ-đọc app_monitor + window.py + import-linter"
  "A1|A1.md|m9,backend,luong-a|A|[M9-A1] View SQL + chỉ số dashboard nghiệp vụ"
  "A2|A2.md|m9,backend,luong-a|A|[M9-A2] Chỉ số dashboard AI/LLMOps"
  "A3|A3.md|m9,backend,luong-a|A|[M9-A3] API dashboard + cảnh báo (ack)"
  "A4|A4.md|m9,backend,luong-a|A|[M9-A4] Health LLM + hiệu năng + nghiệm thu P9"
  "B0|B0.md|m9,backend,luong-b|B|[M9-B0] Khung luật cảnh báo thuần (rules, evaluator)"
  "B1|B1.md|m9,backend,luong-b|B|[M9-B1] Luật theo sự kiện + job worker 60 giây"
  "B2|B2.md|m9,backend,luong-b|B|[M9-B2] Luật tổng hợp + job giờ/ngày"
  "B3|B3.md|m9,backend,luong-b,nen-co|B|[M9-B3] Drift PSI (Nên có)"
)
OLD_TITLES=(  # kế hoạch v1.0 (một người) — đóng nếu đã lỡ tạo
  "[M9] Tầng Monitor (backend) — theo dõi"
  "[M9-0] Chuẩn bị máy + kết nối chỉ-đọc app_monitor"
  "[M9-1] View SQL + chỉ số dashboard nghiệp vụ"
  "[M9-2] Chỉ số dashboard AI/LLMOps"
  "[M9-3] API dashboard + cảnh báo (ack)"
  "[M9-4] Khung luật cảnh báo + luật theo sự kiện + job worker"
  "[M9-5] Luật cảnh báo tổng hợp"
  "[M9-6] Health LLM + hiệu năng + nghiệm thu P9"
  "[M9-7] Drift PSI (Nên có)"
)

declare -A NUM

find_issue() {  # $1 = tiêu đề, $2 = state (all|open) → số issue đúng tiêu đề, rỗng nếu chưa có
  gh issue list -R "$REPO" --state "${2:-all}" --limit 300 --search "in:title \"$1\"" \
    --json number,title --jq ".[] | select(.title == \"$1\") | .number" | head -n1
}

fill() {  # thay số issue + người
  local text="$1" k
  for k in "${!NUM[@]}"; do text="${text//__${k}__/${NUM[$k]}}"; done
  if [[ -n "$ASSIGNEE_A" ]]; then text="${text//__ASSIGNEE_A__/@$ASSIGNEE_A (Lưu Dương)}"
  else text="${text//__ASSIGNEE_A__/Lưu Dương}"; fi
  if [[ -n "$ASSIGNEE_B" ]]; then text="${text//__ASSIGNEE_B__/@$ASSIGNEE_B (Tạ Duy Anh)}"
  else text="${text//__ASSIGNEE_B__/Tạ Duy Anh}"; fi
  printf '%s' "$text"
}

if (( RUN )); then
  gh label create m9      -R "$REPO" --color 5319E7 --description "Tầng Monitor M9"                 --force >/dev/null
  gh label create epic    -R "$REPO" --color 0E8A16 --description "Issue theo dõi"                  --force >/dev/null
  gh label create backend -R "$REPO" --color 1D76DB --description "Backend"                         --force >/dev/null
  gh label create nen-co  -R "$REPO" --color C5DEF5 --description "Nên có"                          --force >/dev/null
  gh label create luong-a -R "$REPO" --color FBCA04 --description "M9 luồng A — Lưu Dương"           --force >/dev/null
  gh label create luong-b -R "$REPO" --color D93F0B --description "M9 luồng B — Tạ Duy Anh"          --force >/dev/null
fi

# Lượt 1: tạo (hoặc tìm) mọi issue để có đủ số — thân tạm, sửa ở lượt 2 vì A4 trỏ B2, B1 trỏ A0/A1…
for item in "${ITEMS[@]}"; do
  IFS='|' read -r key file labels who title <<<"$item"
  existing="$(find_issue "$title" all || true)"
  if [[ -n "$existing" ]]; then NUM[$key]="$existing"; echo "Đã có   #$existing  $title"; continue; fi
  if (( RUN )); then
    printf 'Đang tạo — thân đầy đủ được cập nhật ngay sau.\n' > "$TMP/tmp.md"
    args=(-R "$REPO" --title "$title" --body-file "$TMP/tmp.md" --label "$labels")
    [[ "$who" == "A" && -n "$ASSIGNEE_A" ]] && args+=(--assignee "$ASSIGNEE_A")
    [[ "$who" == "B" && -n "$ASSIGNEE_B" ]] && args+=(--assignee "$ASSIGNEE_B")
    url="$(gh issue create "${args[@]}")"; NUM[$key]="${url##*/}"
    echo "Tạo    #${NUM[$key]}  $title"
  else
    NUM[$key]="<$key>"; echo "Sẽ tạo  $title  [$labels]"
  fi
done

# Lượt 2: thân đầy đủ cho mọi issue; không còn placeholder nào mới ghi.
for item in "${ITEMS[@]}"; do
  IFS='|' read -r key file labels who title <<<"$item"
  body="$(fill "$(cat "$DIR/$file")")"
  if grep -q '__[A-Z0-9_]*__' <<<"$body"; then
    echo "Thân $file còn placeholder: $(grep -o '__[A-Z0-9_]*__' <<<"$body" | sort -u | tr '\n' ' ')"; exit 1
  fi
  if (( RUN )); then
    printf '%s' "$body" > "$TMP/body.md"
    gh issue edit "${NUM[$key]}" -R "$REPO" --body-file "$TMP/body.md" >/dev/null
    echo "Ghi thân #${NUM[$key]}  ($file)"
  fi
done

# Đóng issue kế hoạch cũ (một người) nếu còn mở.
for t in "${OLD_TITLES[@]}"; do
  old="$(find_issue "$t" open || true)"
  [[ -z "$old" ]] && continue
  if (( RUN )); then
    gh issue comment "$old" -R "$REPO" \
      --body "Kế hoạch đổi sang hai luồng (Lưu Dương — A, Tạ Duy Anh — B). Theo dõi ở epic #${NUM[EPIC]}." >/dev/null
    gh issue close "$old" -R "$REPO" --reason "not planned" >/dev/null
    echo "Đóng cũ #$old  $t"
  else
    echo "Sẽ đóng cũ #$old  $t"
  fi
done

(( RUN )) && echo "Xong. Epic: #${NUM[EPIC]}" || { echo; echo "Chạy thử xong. Tạo thật: bash $0 --run"; }
