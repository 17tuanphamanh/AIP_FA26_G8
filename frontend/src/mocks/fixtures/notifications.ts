// Fixture N-TB (dev:mock) — thông báo của nhân viên + ticket minh hoạ đang chờ IT duyệt có `deadline`/`server_now`.
// Mã ticket tiền tố `tkt-demo-tb-` / `tkt-demo-duyet-` (không bao giờ có ở backend; check:dist bắt nếu lọt bản build).
import type { NotificationItem, NotificationPage, TicketView } from "../../api/types.ts";

export const TB_TICKET_PREFIX = "tkt-demo-tb-";
export const DUYET_PREFIX = "tkt-demo-duyet-";
/** Chờ duyệt, còn 12 phút kể từ lần GET đầu. */
export const DUYET_CON_HAN = `${DUYET_PREFIX}1`;
/** Chờ duyệt, hết hạn 20 giây sau lần GET đầu (minh hoạ câu quá hạn + tải lại một lần); 15 giây sau hạn → đã chuyển L2. */
export const DUYET_SAP_HET = `${DUYET_PREFIX}het`;
export const DUYET_IDS: readonly string[] = [DUYET_CON_HAN, DUYET_SAP_HET];

const iso = (ms: number) => new Date(ms).toISOString();

const APPROVAL_TEXT = {
  approved: "IT đã duyệt yêu cầu cấp quyền thư mục dự án của bạn. Hệ thống đang thực hiện.",
  rejected: "IT đã từ chối yêu cầu cài phần mềm vì phần mềm chưa có trong danh mục được phép.",
} as const;
const CLOSE_TEXT = {
  completed: "Kỹ thuật viên đã xử lý xong sự cố VPN của bạn.",
  confirmed_denial: "Kỹ thuật viên đã xem lại và giữ quyết định không cấp quyền quản trị máy.",
  reopened_as_new: "Kỹ thuật viên đề nghị bạn gửi một yêu cầu mới cho việc đổi thiết bị.",
} as const;

/** 26 thông báo (mới nhất trước), cách nhau 47 phút; dòng 3 có chữ dáng mã (minh hoạ bộ lọc), dòng 2 = `reopened_as_new` (không mã ticket mới). */
export function createNotifications(now: number): NotificationItem[] {
  const out: NotificationItem[] = [];
  for (let i = 0; i < 26; i++) {
    const created_at = iso(now - 4 * 60_000 - i * 47 * 60_000);
    const ticket_id = `${TB_TICKET_PREFIX}${String(i + 1).padStart(2, "0")}`;
    if (i % 2 === 0) {
      const result = i % 4 === 0 ? "approved" : "rejected";
      out.push({ id: `appr:${9100 + i}`, kind: "approval_decided", ticket_id, text: APPROVAL_TEXT[result], result, new_ticket_id: null, created_at });
    } else {
      const result = (["reopened_as_new", "completed", "confirmed_denial"] as const)[((i - 1) / 2) % 3]!;
      out.push({
        id: `esc:${700 + i}`,
        kind: "escalation_closed",
        ticket_id,
        text: CLOSE_TEXT[result],
        result,
        new_ticket_id: null, // ĐP 23:51: luôn null đợt này
        created_at,
      });
    }
  }
  // Chữ server lỡ mang mã nội bộ → màn phải thay bằng câu chung (P4).
  out[2] = { ...out[2]!, text: "Yêu cầu bị từ chối theo luật R18 (ngoài giờ), trạng thái S_REJECTED." };
  return out;
}

/** Trang theo con trỏ mờ "o<vị trí>". Con trỏ lạ → null (handler trả 422). */
export function pageOf(all: readonly NotificationItem[], limit: number, after: string | null): NotificationPage | null {
  let start = 0;
  if (after !== null) {
    const m = /^o([0-9]{1,4})$/.exec(after);
    if (!m) return null;
    start = Number(m[1]);
  }
  const items = all.slice(start, start + limit);
  const next = start + limit < all.length ? `o${start + limit}` : null;
  return { items, next_cursor: next };
}

export type DuyetTicket = { id: string; created: number; deadline: number };

export function createDuyet(id: string, now: number): DuyetTicket {
  return { id, created: now - 2 * 60_000, deadline: id === DUYET_SAP_HET ? now + 20_000 : now + 12 * 60_000 };
}

/** Quá hạn 15 giây mà chưa ai duyệt → backend tự chuyển kỹ thuật viên (E6); trước đó vẫn chờ duyệt (đồng hồ báo quá hạn). */
export function duyetView(t: DuyetTicket, now: number): TicketView {
  const escalated = now >= t.deadline + 15_000;
  return {
    ticket_id: t.id,
    status: escalated ? "S_ESCALATED" : "S_PENDING_APPROVAL",
    waiting_for: escalated ? null : "approval",
    conversation: [
      {
        role: "assistant",
        text: escalated
          ? "Yêu cầu chưa được duyệt kịp nên đã chuyển cho kỹ thuật viên. Kỹ thuật viên sẽ liên hệ bạn."
          : "Yêu cầu cấp quyền ghi thư mục dự án cần IT duyệt trước khi thực hiện. Mình sẽ báo ngay khi có kết quả.",
      },
    ],
    exit_code: escalated ? "E6" : null,
    close_reason: null,
    final_state: escalated ? "S_ESCALATED" : null,
    created_at: iso(t.created),
    closed_at: escalated ? iso(t.deadline + 15_000) : null,
    deadline: escalated ? null : iso(t.deadline),
    server_now: iso(now),
  };
}
