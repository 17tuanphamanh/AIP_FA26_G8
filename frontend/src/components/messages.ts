// Kiểm dạng `conversation` (list[dict], không có schema — contracts-tam.ts TicketView). Phần tử hỏng bị bỏ, không làm
// vỡ màn; `kind` lạ giữ nguyên để hiện như tin thường (12b Q-fe-2).
import type { Source } from "../api/types.ts";

export type Message = { role: "user" | "assistant"; kind: string; text: string; sources: Source[] };

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

export function normalizeMessage(raw: unknown): Message | null {
  if (!isRecord(raw)) return null;
  const role = raw.role === "user" ? "user" : "assistant";
  const kind = role === "user" ? "user" : typeof raw.kind === "string" ? raw.kind : "text";
  const sources = kind === "answer" ? toSources(raw.sources) : [];
  const text = kind === "answer" ? stripSourcesBlock(toText(raw.text), sources) : toText(raw.text);
  if (!text.trim() && sources.length === 0) return null;
  return { role, kind, text, sources };
}

export function normalizeConversation(raw: unknown): Message[] {
  return Array.isArray(raw) ? raw.map(normalizeMessage).filter((m): m is Message => m !== null) : [];
}
