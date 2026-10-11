// Kiểm dạng `conversation` (list[dict], không có schema — contracts-tam.ts TicketView). Phần tử hỏng bị bỏ, không làm
// vỡ màn; `kind` lạ giữ nguyên để hiện như tin thường (12b Q-fe-2). `kind:"digest"` (tin tổng hợp nhiều ý, D-31 — Đề xuất
// F6, PLAN-fe mục 8): `round` + `items` đúng dạng → `digest`; hỏng → hiện `text` như tin thường.
import type { DigestItem, DigestItemKind, DigestNeeds, Source } from "../api/types.ts";

export type Digest = { round: number; items: DigestItem[] };
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

/** Một khối của tin tổng hợp. Thiếu `child_id`/`index`/`title`/`text` → bỏ khối. `kind` lạ → như kết quả; `needs` lạ →
 *  `none` (không mở ô nhập cho thứ không hiểu); `options` chỉ với `needs:"answer"`. Khối "Nguồn:" cắt như tin answer. */
function toDigestItem(raw: unknown): DigestItem | null {
  if (!isRecord(raw)) return null;
  const { child_id, index, title, text } = raw;
  if (typeof child_id !== "string" || !child_id || !isIndex(index) || typeof title !== "string" || typeof text !== "string") {
    return null;
  }
  const kind = ITEM_KINDS.has(String(raw.kind)) ? (raw.kind as DigestItemKind) : "result";
  const needs = NEEDS.has(String(raw.needs)) ? (raw.needs as DigestNeeds) : "none";
  const sources = toSources(raw.sources);
  const options =
    needs === "answer" && Array.isArray(raw.options)
      ? [...new Set(raw.options.filter((o): o is string => typeof o === "string" && o.trim() !== ""))]
      : [];
  const item: DigestItem = { child_id, index, title, kind, text: stripSourcesBlock(text, sources), needs };
  if (options.length > 0) item.options = options;
  if (sources.length > 0) item.sources = sources;
  return item;
}

/** `round` nguyên ≥ 1 + ít nhất một khối hợp lệ; trùng `child_id` → giữ khối đầu; sắp theo `index`. */
function toDigest(raw: Record<string, unknown>): Digest | null {
  if (!isIndex(raw.round) || !Array.isArray(raw.items)) return null;
  const seen = new Set<string>();
  const items: DigestItem[] = [];
  for (const item of raw.items.map(toDigestItem)) {
    if (item === null || seen.has(item.child_id)) continue;
    seen.add(item.child_id);
    items.push(item);
  }
  items.sort((a, b) => a.index - b.index);
  return items.length > 0 ? { round: raw.round, items } : null;
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
