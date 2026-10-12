// Yêu cầu nhiều ý (D-31) phía nhân viên — hàm thuần. Hợp đồng là [Đề xuất F6 — chốt ở T20] (PLAN-fe mục 8):
// `children_progress` trên GET ticket cha, tin `kind:"digest"`, `POST /api/tickets/{cha}/reply`.
// Nhân viên KHÔNG thấy mã `S_*`; ý bị chặn chỉ có câu trung tính [Chốt 7.1].
import { ApiError, errorMessage } from "../../api/errors.ts";
import { NOTE_MAX, TEXT_MAX } from "../../api/tickets.ts";
import type { ChildOutcome, ChildProgressState, DigestItem, ParentReplyIn, ParentReplyItem, TicketView } from "../../api/types.ts";
import type { Message } from "../../components/messages.ts";
import { ownEntry } from "../../lib/lookup.ts";
import { statusLabel, type Tone } from "./status.ts";

// ---------------------------------------------------------------- dải tiến độ (P1 §8.3 — không phải tin nhắn)

/** Một ý trên dải tiến độ sau khi kiểm dạng. `progress`/`outcome` giữ nguyên chuỗi server gửi — nhãn tự xử lý giá trị lạ. */
export type ProgressView = { child_id: string; index: number; title: string; progress: string; outcome: string | null };

/** `closed` không có ở đây — đọc theo `outcome`. */
export const PROGRESS_LABEL: Readonly<Record<Exclude<ChildProgressState, "closed">, string>> = {
  processing: "Đang xử lý",
  pending_approval: "Chờ IT duyệt",
  ready: "Đã có kết quả — chờ tổng hợp", // đúng chữ P1 §8.3
  needs_user: "Cần bạn phản hồi",
};

export const OUTCOME_LABEL: Readonly<Record<ChildOutcome, string>> = {
  resolved: "Đã xong",
  escalated: "Đã chuyển kỹ thuật viên",
  rejected: "Không được duyệt",
  blocked: "Không thể xử lý tự động", // trung tính như E0 [Chốt 7.1]
};

/** progress/outcome lạ (backend thêm sau) → câu chung, không vỡ màn, không lộ giá trị. */
export const UNKNOWN_PROGRESS_LABEL = "Đang xử lý";

const has = <T extends string>(table: Readonly<Record<T, string>>, key: string | null): key is T =>
  key !== null && Object.prototype.hasOwnProperty.call(table, key);

export function progressLabel(p: Pick<ProgressView, "progress" | "outcome">): string {
  if (p.progress === "closed") return has(OUTCOME_LABEL, p.outcome) ? OUTCOME_LABEL[p.outcome] : UNKNOWN_PROGRESS_LABEL;
  return has(PROGRESS_LABEL, p.progress) ? PROGRESS_LABEL[p.progress] : UNKNOWN_PROGRESS_LABEL;
}

/** Màu chấm theo KH mục 5: cam = chờ con người (IT duyệt / bạn phản hồi), xanh lá = xong, xám = chuyển / không xử lý. */
export function progressTone(p: Pick<ProgressView, "progress" | "outcome">): Tone {
  if (p.progress === "pending_approval" || p.progress === "needs_user") return "waiting";
  if (p.progress === "closed" && has(OUTCOME_LABEL, p.outcome)) return p.outcome === "resolved" ? "done" : "closed";
  return "processing";
}

/** `children_progress`: không phải mảng / rỗng → null (ticket thường). Phần tử thiếu `child_id`/`index`/`title` → bỏ. */
export function normalizeProgress(raw: unknown): ProgressView[] | null {
  if (!Array.isArray(raw)) return null;
  const seen = new Set<string>();
  const items: ProgressView[] = [];
  for (const entry of raw) {
    if (entry === null || typeof entry !== "object" || Array.isArray(entry)) continue;
    const { child_id, index, title, progress, outcome } = entry as Record<string, unknown>;
    if (typeof child_id !== "string" || !child_id || seen.has(child_id)) continue;
    if (typeof index !== "number" || !Number.isInteger(index) || index < 1 || typeof title !== "string") continue;
    seen.add(child_id);
    items.push({
      child_id,
      index,
      title,
      progress: typeof progress === "string" ? progress : "",
      outcome: typeof outcome === "string" ? outcome : null,
    });
  }
  items.sort((a, b) => a.index - b.index);
  return items.length > 0 ? items : null;
}

// ---------------------------------------------------------------- nhãn ticket cha (12b Q-fe-34 — chỉ khi có children_progress)

// Cha ở `S_CLASSIFYING` khi chờ các con, `S_CONFIRMING` khi chờ trả lời tin tổng hợp (P1 §8) — nhãn ticket thường của hai
// trạng thái đó ("Đang tiếp nhận yêu cầu", "Chờ bạn xác nhận kết quả") sai nghĩa với cha. Cha `S_RESOLVED` kể cả khi có ý
// bị chuyển / không duyệt (bảng B5) → không nói "đã hoàn tất" chung chung.
export const PARENT_PROCESSING = "Đang xử lý các ý";
export const PARENT_REPLY = "Cần bạn phản hồi";
export const PARENT_DONE = "Các ý đã có kết quả";
export const PARENT_FINAL_NOTE = "Các ý đã có kết quả — xem từng ý ở trên.";

export function parentStatusLabel(view: Pick<TicketView, "final_state" | "waiting_for">, progress: readonly ProgressView[]): string {
  if (view.final_state) {
    const allResolved = progress.every((p) => p.progress === "closed" && p.outcome === "resolved");
    return view.final_state === "S_RESOLVED" && !allResolved ? PARENT_DONE : statusLabel(view.final_state);
  }
  return view.waiting_for === "reply" ? PARENT_REPLY : PARENT_PROCESSING;
}

// ---------------------------------------------------------------- tin tổng hợp

/** Round lớn nhất trong các tin digest hợp lệ — tin duy nhất được có form khi `waiting_for = "reply"`. */
export function latestRound(messages: readonly Message[]): number | null {
  let round: number | null = null;
  for (const m of messages) if (m.digest && (round === null || m.digest.round > round)) round = m.digest.round;
  return round;
}

export const digestLead = (count: number, active: boolean) =>
  active ? `Kết quả cho ${count} việc của bạn — phản hồi rồi gửi một lần.` : `Kết quả cho ${count} việc của bạn.`;

const ITEM_LABEL: Readonly<Record<DigestItem["kind"], string>> = {
  result: "Đã xử lý",
  question: "Cần bạn trả lời",
  rejection: "IT chưa duyệt",
  escalation: "Đã chuyển kỹ thuật viên",
};

/** Nhãn góc phải của khối (Bản 4). Ý có `outcome:"blocked"` → câu trung tính, bất kể `kind` [Chốt 7.1]. */
export function itemLabel(item: Pick<DigestItem, "kind">, outcome: string | null | undefined): string {
  if (outcome === "blocked") return OUTCOME_LABEL.blocked;
  return ownEntry(ITEM_LABEL, item.kind, ITEM_LABEL.result);
}

// ---------------------------------------------------------------- form trả lời

/** Nháp của một khối: `choice` cho xác nhận (null = chưa chọn), `answer` cho câu hỏi, `note` khi "Chưa ổn". */
export type DraftItem = { choice: boolean | null; note: string; answer: string };
export type Drafts = Readonly<Record<string, DraftItem>>;
export const EMPTY_DRAFT: DraftItem = { choice: null, note: "", answer: "" };

// 12b Q-fe-35.
export const REPLY_MISSING_CHOICE = "Cần chọn một máy trước khi gửi.";
export const REPLY_MISSING_ANSWER = "Cần trả lời trước khi gửi.";
export const REPLY_MISSING_CONFIRM = "Chọn Đã ổn hoặc Chưa ổn";
export const REPLY_ANSWER_TOO_LONG = `Câu trả lời tối đa ${TEXT_MAX} ký tự.`;
export const REPLY_NOTE_TOO_LONG = `Ghi chú tối đa ${NOTE_MAX} ký tự.`;
export const REPLY_INVALID = "Phản hồi cho ý này chưa hợp lệ — kiểm tra lại.";

/** Nháp của một khối theo `child_id` (khoá server) — khoá RIÊNG: id "constructor" / "__proto__" không ra hàm/object
 *  của prototype. Các hàm dưới GHI theo `child_id` qua `Object.fromEntries` (tạo khoá riêng; gán `obj["__proto__"] = …` là
 *  đổi prototype — khoá mất khỏi lỗi và khỏi body JSON). */
export const draftOf = (drafts: Drafts, childId: string): DraftItem => ownEntry(drafts, childId, EMPTY_DRAFT);

/** Chỉ các khối cần người dùng (`needs ≠ "none"`) — đúng tập `awaiting` của cha (P1 §8.2). */
export const awaitingItems = (items: readonly DigestItem[]) => items.filter((i) => i.needs !== "none");

/** Kiểm PHÍA MÁY KHÁCH trước khi gửi: mọi khối cần người dùng phải có lựa chọn / câu trả lời. Trả lỗi theo `child_id`
 *  (rỗng = gửi được). Server vẫn kiểm (422). */
export function checkDigest(items: readonly DigestItem[], drafts: Drafts): Record<string, string> {
  const errors: [string, string][] = [];
  for (const item of awaitingItems(items)) {
    const draft = draftOf(drafts, item.child_id);
    const fail = (message: string) => errors.push([item.child_id, message]);
    if (item.needs === "confirm") {
      if (draft.choice === null) fail(REPLY_MISSING_CONFIRM);
      else if (draft.choice === false && draft.note.trim().length > NOTE_MAX) fail(REPLY_NOTE_TOO_LONG);
    } else {
      const answer = draft.answer.trim();
      if (!answer) fail(item.options?.length ? REPLY_MISSING_CHOICE : REPLY_MISSING_ANSWER);
      else if (answer.length > TEXT_MAX) fail(REPLY_ANSWER_TOO_LONG);
    }
  }
  return Object.fromEntries(errors);
}

/** Body `/reply`: CHỈ khối `needs ≠ "none"` (ý bị từ chối / đã chuyển không có mặt). Câu trả lời đã trim; ghi chú chỉ khi
 *  "Chưa ổn" và không rỗng (rỗng → bỏ hẳn khoá, như `/confirm`). Gọi sau `checkDigest` rỗng. */
export function digestReplyBody(items: readonly DigestItem[], drafts: Drafts): ParentReplyIn {
  const body = awaitingItems(items).map((item): [string, ParentReplyItem] => {
    const draft = draftOf(drafts, item.child_id);
    if (item.needs === "answer") return [item.child_id, { answer: draft.answer.trim() }];
    const note = draft.choice === false ? draft.note.trim() : "";
    return [item.child_id, note ? { confirmed: false, note } : { confirmed: draft.choice === true }];
  });
  return { items: Object.fromEntries(body) };
}

/** 422 `fields` (đã bỏ `body.`, errors.ts) → lỗi tại ĐÚNG khối theo `child_id` (`items.<cid>` hoặc `items.<cid>.…`).
 *  Field không thuộc khối nào (`items`, `items.<extra>`, `body`…) → `general`. */
export function digestFieldErrors(fields: readonly string[], childIds: readonly string[]) {
  const byChild: [string, string][] = [];
  let general = fields.length === 0;
  for (const field of fields) {
    const cid = childIds.find((id) => field === `items.${id}` || field.startsWith(`items.${id}.`));
    if (cid === undefined) {
      general = true;
      continue;
    }
    const rest = field.slice(`items.${cid}`.length).split(".");
    byChild.push([cid, rest.includes("note") ? REPLY_NOTE_TOO_LONG : REPLY_INVALID]);
  }
  return { byChild: Object.fromEntries(byChild), general };
}

/** Lỗi của `/reply` → lỗi theo khối + câu chung (dưới nút "Gửi phản hồi"). 422 có `fields` → đúng khối, field không
 *  thuộc khối nào (hoặc 422 `{detail}`) → câu chung; 409 trả muộn → câu của server / câu chung (màn tự tải lại ticket);
 *  413 → "Nội dung quá dài."; lỗi khác → errors.ts. Không bao giờ in lại nội dung người dùng gửi. */
export function replyErrorView(error: unknown, childIds: readonly string[]): { byChild: Record<string, string>; general: string | null } {
  if (!(error instanceof ApiError)) return { byChild: {}, general: errorMessage(null) };
  if (error.status === 422) {
    const { byChild, general } = digestFieldErrors(error.fields, childIds);
    return { byChild, general: general ? errorMessage(error) : null };
  }
  if (error.status === 413) return { byChild: {}, general: "Nội dung quá dài." };
  return { byChild: {}, general: errorMessage(error) };
}
