// Hàng đợi L2 MINH HOẠ (N-PA §4; chỉ dev:mock + vitest). `ticket_id` mang tiền tố `tkt-demo-esc-` (check:dist bắt nếu lọt).
// Đủ > 2 trang (50 ca/trang) ca MỞ + vài ca ĐÃ ĐÓNG. Thứ tự như server: priority → created_at → escalation_id.
import type { EscalationCloseResult, EscalationQueueItem } from "../../api/types.ts";
import type { QueueItem } from "../../api/escalations.ts";

export const ESC_DEMO_PREFIX = "tkt-demo-esc-";

const SEED: { code: string; priority: number; label: string; deny?: boolean }[] = [
  { code: "E0", priority: 2, label: "An ninh" },
  { code: "E6", priority: 3, label: "Có SLA" },
  { code: "E2", priority: 4, label: "Hạ tầng" },
  { code: "E5", priority: 5, label: "Cao", deny: true },
  { code: "E3", priority: 6, label: "Thường, cần bổ sung KB" },
];

function item(n: number, base: number): EscalationQueueItem {
  const seed = SEED[n % SEED.length]!;
  return {
    escalation_id: 9000 + n,
    ticket_id: `${ESC_DEMO_PREFIX}${String(n).padStart(3, "0")}`,
    exit_code: seed.code,
    priority: seed.priority,
    label: seed.label,
    reason_detail: null,
    is_deny_case: seed.deny === true,
    handoff_note: {
      request: "Không vào được VPN từ sáng (minh hoạ).",
      done_so_far: "Đã kiểm trạng thái chứng chỉ.",
      why_escalated: `${seed.code} — ca minh hoạ số ${n}.`,
      next_for_l2: "Kiểm tra lại và đóng ca.",
    },
    assigned_to: null,
    created_at: new Date(base - (200 - n) * 60_000).toISOString(),
  };
}

const order = (a: EscalationQueueItem, b: EscalationQueueItem) =>
  a.priority - b.priority || Date.parse(a.created_at) - Date.parse(b.created_at) || a.escalation_id - b.escalation_id;

export type CloseOutcome = { status: number; body: Record<string, unknown> };

/** Kho trong bộ nhớ: 62 ca mở + 4 ca đã đóng. Đóng ca chuyển ca sang danh sách đã đóng. */
export function createEscalationStore(base: number, openCount = 62) {
  const open: QueueItem[] = Array.from({ length: openCount }, (_, i) => item(i, base)).sort(order);
  const closed: QueueItem[] = [0, 1, 2, 3].map((i) => {
    const it = item(100 + i, base);
    const results: EscalationCloseResult[] = ["completed", "confirmed_denial", "reopened_as_new", "completed"];
    return {
      ...it,
      exit_code: "E3",
      priority: 6,
      label: "Thường, cần bổ sung KB",
      is_deny_case: false,
      closed_at: new Date(base - (i + 1) * 3_600_000).toISOString(),
      close_result: results[i]!,
      closed_by: "long.nh",
      ...(i === 0 ? { close_note: "Đã bổ sung tài liệu KB và xác nhận với người dùng (minh hoạ)." } : {}),
    };
  });

  return {
    list: (status: "open" | "closed") => (status === "open" ? open : closed),
    find: (id: number) => open.find((i) => i.escalation_id === id) ?? closed.find((i) => i.escalation_id === id),
    /** Đóng ca: không có → 404; đã đóng → 409; E5/E6 + completed → 422 (B20); còn lại → 200. */
    close(id: number, result: EscalationCloseResult, note: string, by: string, now: number): CloseOutcome {
      const idx = open.findIndex((i) => i.escalation_id === id);
      if (idx < 0) {
        return closed.some((i) => i.escalation_id === id)
          ? { status: 409, body: { detail: "already_closed" } }
          : { status: 404, body: { detail: "not_found" } };
      }
      const it = open[idx]!;
      if (result === "completed" && (it.is_deny_case || it.exit_code === "E6")) return { status: 422, body: { detail: "deny_case_cannot_complete" } };
      open.splice(idx, 1);
      closed.unshift({ ...it, closed_at: new Date(now).toISOString(), close_result: result, closed_by: by, close_note: note });
      return { status: 200, body: { escalation_id: id, close_result: result } };
    },
  };
}
export type EscalationStore = ReturnType<typeof createEscalationStore>;
