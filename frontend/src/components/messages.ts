// Kiểm dạng `conversation` (list[dict], không có schema — contracts-tam.ts TicketView). Phần tử hỏng bị bỏ, không làm
// vỡ màn; `kind` lạ giữ nguyên để hiện như tin thường (12b Q-fe-2). `kind:"digest"` (tin tổng hợp nhiều ý, D-31 — T20b
// 5df24c7): hình dạng ĐÃ kiểm chặt ở api/tickets.ts `parseTicketView` (sai → cả ticket lỗi 502, không tới đây); ở đây chỉ
// chuẩn hoá giá trị lạ. `items: []` (vòng cuối chỉ có câu tổng kết) → hiện `text` như tin thường.
import type { DigestItem, DigestItemKind, DigestNeeds, Source } from "../api/types.ts";

/** `summary`: câu tổng kết (bảng 5.2.5) ở dòng cuối `text` của vòng cuối còn khối — chỉ khi tách được chính xác. */
export type Digest = { round: number; items: DigestItem[]; summary?: string };
export type Message = { role: "user" | "assistant"; kind: string; text: string; sources: Source[]; digest?: Digest };

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);

function toText(v: unknown): string {
  if (typeof v === "string") return v;
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  return "";
}

function toSources(v: unknown): Source[] {
  if (!Array.isArray(v)) return [];
  return v.filter(
    (s): s is Source =>
      isRecord(s) && typeof s.chunk_id === "string" && typeof s.title === "string" && typeof s.heading_path === "string",
  );
}

// Backend tự nối danh sách nguồn vào cuối câu trả lời (backend/app/domain/answer.py render_answer: "\n\n" + "Nguồn:"
// + mỗi dòng "- {title} › {heading_path}", bỏ trùng theo chuỗi, giữ thứ tự) — trùng với ô nguồn của UI (12b Q-fe-19).
export const SOURCES_HEADER = "Nguồn:";
export const PATH_SEP = " › ";

/** Cắt khối "Nguồn:" ở CUỐI câu trả lời CHỈ khi khớp đúng từng ký tự với `sources`. Lệch (định dạng backend đổi, nguồn
 *  khác) → giữ nguyên: lặp thì chấp nhận được, mất nguồn thì không. */
export function stripSourcesBlock(text: string, sources: readonly Source[]): string {
  if (sources.length === 0) return text;
  const lines = [...new Set(sources.map((s) => `${s.title}${PATH_SEP}${s.heading_path}`))].map((line) => `- ${line}`);
  const block = `${SOURCES_HEADER}\n${lines.join("\n")}`;
  if (text === block) return "";
  return text.endsWith(`\n\n${block}`) ? text.slice(0, -(block.length + 2)) : text;
}

const ITEM_KINDS: ReadonlySet<string> = new Set<DigestItemKind>(["result", "question", "rejection", "escalation"]);
const NEEDS: ReadonlySet<string> = new Set<DigestNeeds>(["confirm", "answer", "none"]);
const isIndex = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 1;

/** Một khối của tin tổng hợp. Thiếu `child_id`/`index`/`title`/`text` → bỏ khối (lớp phòng thủ — thân đi qua
 *  `parseTicketView` thì không xảy ra). `kind` lạ → như kết quả; `needs` lạ → `none` (không mở ô nhập cho thứ không hiểu). */
function toDigestItem(raw: unknown): DigestItem | null {
  if (!isRecord(raw)) return null;
  const { child_id, index, title, text } = raw;
  if (typeof child_id !== "string" || !child_id || !isIndex(index) || typeof title !== "string" || typeof text !== "string") {
    return null;
  }
  const kind = ITEM_KINDS.has(String(raw.kind)) ? (raw.kind as DigestItemKind) : "result";
  const needs = NEEDS.has(String(raw.needs)) ? (raw.needs as DigestNeeds) : "none";
  return { child_id, index, title, kind, text, needs };
}

/** Dòng của một khối trong `text` của tin — đúng mẫu `compose_digest` (backend/app/domain/messages.py). */
export const digestLine = (item: Pick<DigestItem, "index" | "title" | "text">) => `Ý ${item.index} – ${item.title}: ${item.text}`;

/** Câu tổng kết = phần `text` SAU các dòng khối, CHỈ khi phần đầu khớp từng ký tự và phần sau là đúng một dòng không rỗng
 *  (Q-fe-48). Lệch (mẫu backend đổi, khối bị bỏ…) → không hiện thêm gì — không đoán. */
export function digestSummary(text: string, items: readonly DigestItem[]): string | undefined {
  const head = `${items.map(digestLine).join("\n")}\n`;
  if (items.length === 0 || !text.startsWith(head)) return undefined;
  const rest = text.slice(head.length);
  return rest.trim() && !rest.includes("\n") ? rest : undefined;
}

/** `round` nguyên ≥ 1 + ít nhất một khối; sắp theo `index` (giữ thứ tự server trong cùng một ý — một con có thể có nhiều
 *  khối, chỉ một khối cần trả lời: api/tickets.ts). Câu tổng kết tính trên thứ tự server gửi. */
function toDigest(raw: Record<string, unknown>): Digest | null {
  if (!isIndex(raw.round) || !Array.isArray(raw.items)) return null;
  const items = raw.items.map(toDigestItem).filter((i): i is DigestItem => i !== null);
  if (items.length === 0) return null;
  const summary = items.length === raw.items.length ? digestSummary(toText(raw.text), items) : undefined;
  const sorted = [...items].sort((a, b) => a.index - b.index); // sort ổn định: cùng ý giữ thứ tự server
  return summary === undefined ? { round: raw.round, items: sorted } : { round: raw.round, items: sorted, summary };
}

export function normalizeMessage(raw: unknown): Message | null {
  if (!isRecord(raw)) return null;
  const role = raw.role === "user" ? "user" : "assistant";
  const kind = role === "user" ? "user" : typeof raw.kind === "string" ? raw.kind : "text";
  if (kind === "digest") {
    const digest = toDigest(raw);
    if (digest) return { role, kind, text: toText(raw.text), sources: [], digest };
  }
  const sources = kind === "answer" ? toSources(raw.sources) : [];
  const text = kind === "answer" ? stripSourcesBlock(toText(raw.text), sources) : toText(raw.text);
  if (!text.trim() && sources.length === 0) return null;
  return { role, kind, text, sources };
}

export function normalizeConversation(raw: unknown): Message[] {
  return Array.isArray(raw) ? raw.map(normalizeMessage).filter((m): m is Message => m !== null) : [];
}
