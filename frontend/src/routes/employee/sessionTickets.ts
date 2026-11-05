// Lịch sử "Gần đây" trên thanh bên = ticket tạo TRONG PHIÊN NÀY (KH 4.6): chỉ trong bộ nhớ, mất khi tải lại trang,
// xoá khi đăng xuất / hết phiên. Chưa có `GET /api/tickets?mine=1` (Phase 7) — không hiện dữ liệu bịa.
//
// Câu yêu cầu (12b Q-fe-18): `TicketView.conversation` KHÔNG chứa câu yêu cầu đầu (Nợ API #8) → giữ câu vừa gõ ở đây,
// và CHỈ giữ khi 202 trả `notices` rỗng — guard không che gì (backend/app/guard/privacy.py: notices rỗng ⇔ 0 bí mật,
// 0 PII) nên câu gõ vào trùng câu đã che. `notices` khác rỗng → KHÔNG giữ câu gốc ở đâu cả. Tiêu đề và mục "Gần đây"
// chỉ lấy từ câu yêu cầu, không lấy từ câu trả lời.
import { useSyncExternalStore } from "react";
import type { Tone } from "./status.ts";

export type SessionTicket = {
  ticket_id: string;
  /** Câu yêu cầu đúng như đã gõ — null khi guard đã che bớt (hoặc ticket không tạo trong phiên này). */
  request: string | null;
  /** Guard đã che bí mật / PII trong câu yêu cầu → hiện REDACTED_NOTE thay câu gốc. */
  redacted: boolean;
  tone: Tone;
};

export const DEFAULT_TITLE = "Yêu cầu của bạn";
export const REDACTED_NOTE = "Nội dung đã được ẩn bớt thông tin nhạy cảm.";

let items: readonly SessionTicket[] = [];
const listeners = new Set<() => void>();

function set(next: readonly SessionTicket[]): void {
  items = next;
  for (const listener of listeners) listener();
}

export const sessionTickets = {
  /** Ticket vừa tạo (202) — đứng đầu danh sách. */
  add(ticket_id: string, request: string, notices: readonly string[]): void {
    if (items.some((t) => t.ticket_id === ticket_id)) return;
    const redacted = notices.length > 0;
    set([{ ticket_id, request: redacted ? null : request, redacted, tone: "processing" }, ...items]);
  },
  /** Chỉ cập nhật ticket đã có trong phiên (mở ticket cũ bằng URL không thêm vào danh sách). */
  setTone(ticket_id: string, tone: Tone): void {
    const current = items.find((t) => t.ticket_id === ticket_id);
    if (!current || current.tone === tone) return;
    set(items.map((t) => (t.ticket_id === ticket_id ? { ...t, tone } : t)));
  },
  clear(): void {
    if (items.length) set([]);
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
  getSnapshot: (): readonly SessionTicket[] => items,
};

export function useSessionTickets(): readonly SessionTicket[] {
  return useSyncExternalStore(sessionTickets.subscribe, sessionTickets.getSnapshot);
}

/** Tiêu đề hội thoại / mục "Gần đây": câu yêu cầu, một dòng, cắt ngắn (KH 4.6). Không có → DEFAULT_TITLE. */
export function titleOf(ticket: Pick<SessionTicket, "request"> | undefined, max = 60): string {
  if (!ticket?.request) return DEFAULT_TITLE;
  const line = ticket.request.replace(/\s+/g, " ").trim();
  return line.length > max ? `${line.slice(0, max - 1).trimEnd()}…` : line;
}
