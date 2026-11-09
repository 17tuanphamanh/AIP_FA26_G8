// Ticket cha nhiều ý MINH HOẠ (D-31) — route thật T20b 5df24c7; MSW chỉ giữ để minh hoạ ca lỗi khó tạo trên stack (422 tại
// một ý, 409 trả muộn). Hình dạng ĐÚNG hợp đồng thật (api/contracts-tam.ts khối T20b): tiêu đề kiểu `child_title`, chữ
// khối kiểu mẫu B18/B11/B16, `text` của tin = các dòng "Ý i – title: text" (+ câu tổng kết bảng 5.2.5 khi mọi ý đã
// kết thúc; vòng cuối không còn notice → `items: []`); KHÔNG `options`/`sources`/`blocked`. Máy trạng thái trong bộ nhớ
// (mất khi tải lại trang):
//   working1 (GET đầu: cha S_CLASSIFYING, 3 ý ở 3 trạng thái khác nhau)
//   → round1 (S_CONFIRMING, reply): ý 1 kết quả cần xác nhận · ý 2 câu hỏi · ý 3 bị từ chối
//   → reply 2 khoá → working2 (ý 1 đóng, ý 2 chạy tiếp) → round2: CHỈ ý 2 kết quả cần xác nhận
//   → reply 1 khoá → closed (cha đóng theo bảng 5.2.5) + tin vòng cuối chỉ có câu tổng kết.
// Câu trả lời ghi thành một tin `{role:"user", text}` như `reply_text` — server thật che qua privacy guard; ở đây không.
// Xoá khi: không còn cần minh hoạ ca lỗi (xoá cùng mocks/handlers/employee-multi.ts).
import type { ChildOutcome, ChildProgressState, DigestItem, ParentReplyItem, TicketView } from "../../api/types.ts";

export const MULTI_DEMO_PREFIX = "tkt-demo-multi-";
/** `-1`, `-2`: luồng đủ · `-422`: reply đúng hình vẫn 422 tại ý 2 · `-409`: reply luôn 409 (trả muộn). */
export const MULTI_DEMO_IDS: readonly string[] = ["1", "2", "422", "409"].map((s) => `${MULTI_DEMO_PREFIX}${s}`);

type Phase = "working1" | "round1" | "working2" | "round2" | "closed";
type Child = { progress: ChildProgressState; outcome: ChildOutcome | null };
export type Need = "answer" | "confirm";

export type MultiTicket = {
  id: string;
  phase: Phase;
  /** Số lần GET trong pha hiện tại — pha "đang xử lý" chuyển tiếp ở lần GET thứ hai (một nhịp polling). */
  reads: number;
  created_at: string;
  closed_at: string | null;
  final_state: string | null;
  conversation: unknown[];
  children: Child[];
  device: string | null;
};

const TITLES = ["Đặt lại mật khẩu", "Cài đặt phần mềm", "Cấp quyền truy cập"]; // `child_title`: nhãn hành động, chữ đầu hoa
const DEVICE_ID = /^[A-Z]{2,4}-\d{3,5}$/; // = DEVICE_ID của backend/app/domain/messages.py (định danh qua mẫu mới vào tin)
export const childId = (id: string, index: number) => `${id}-${index}`;

export function createMulti(id: string, base: number): MultiTicket {
  return {
    id,
    phase: "working1",
    reads: 0,
    created_at: new Date(base).toISOString(),
    closed_at: null,
    final_state: null,
    conversation: [],
    children: [
      { progress: "ready", outcome: null },
      { progress: "pending_approval", outcome: null },
      { progress: "processing", outcome: null },
    ],
    device: null,
  };
}

/** Câu tổng kết theo bảng 5.2.5 (backend/app/domain/children.py `SUMMARY`). */
export function summaryText(outcomes: readonly (ChildOutcome | null)[]): string {
  const n = outcomes.length;
  const r = outcomes.filter((o) => o === "resolved").length;
  const esc = outcomes.filter((o) => o === "escalated").length;
  const rej = outcomes.filter((o) => o === "rejected").length;
  if (r === n) return `Cả ${n} yêu cầu đã hoàn tất.`;
  if (esc === n) return "Các yêu cầu đã được chuyển kỹ thuật viên.";
  if (rej === n) return "Các yêu cầu không được duyệt.";
  if (r === 0) return "Các yêu cầu không xử lý tự động được (chuyển kỹ thuật viên hoặc không được duyệt).";
  return esc ? `Đã xong ${r}/${n} yêu cầu; phần còn lại đã chuyển kỹ thuật viên.` : `Đã xong ${r}/${n} yêu cầu; có yêu cầu không được duyệt.`;
}

function digest(round: number, items: DigestItem[], summary?: string) {
  const lines = items.map((i) => `Ý ${i.index} – ${i.title}: ${i.text}`);
  if (summary) lines.push(summary);
  return { role: "assistant", kind: "digest", round, text: lines.join("\n"), items };
}

function item(id: string, index: number, rest: Omit<DigestItem, "child_id" | "index" | "title">): DigestItem {
  return { child_id: childId(id, index), index, title: TITLES[index - 1] ?? "", ...rest };
}

/** Pha "đang xử lý" → pha chờ người dùng: cha gửi MỘT tin tổng hợp (P1 §8.2). */
function advance(t: MultiTicket) {
  if (t.phase === "working1") {
    t.conversation.push(
      digest(1, [
        item(t.id, 1, {
          kind: "result",
          needs: "confirm",
          text: "Đã đặt lại mật khẩu tài khoản email của bạn. Mật khẩu tạm đã gửi qua SMS; cần đổi ở lần đăng nhập tới. Bạn đăng nhập thử rồi xác nhận giúp mình nhé.",
        }),
        item(t.id, 2, { kind: "question", needs: "answer", text: "Bạn muốn cài Microsoft Visio lên máy nào?" }),
        item(t.id, 3, {
          kind: "rejection",
          needs: "none",
          text: "Yêu cầu cấp quyền truy cập cho thư mục finance/ke-toan-chung chưa được duyệt. Lý do: không đủ thẩm quyền.",
        }),
      ]),
    );
    t.children = [
      { progress: "needs_user", outcome: null },
      { progress: "needs_user", outcome: null },
      { progress: "closed", outcome: "rejected" },
    ];
    t.phase = "round1";
  } else if (t.phase === "working2") {
    const target = t.device && DEVICE_ID.test(t.device) ? `máy ${t.device}` : "máy của bạn";
    t.conversation.push(
      digest(2, [item(t.id, 2, { kind: "result", needs: "confirm", text: `Đã cài Microsoft Visio lên ${target}. Bạn mở thử rồi xác nhận giúp mình nhé.` })]),
    );
    t.children[1] = { progress: "needs_user", outcome: null };
    t.phase = "round2";
  } else {
    return;
  }
  t.reads = 0;
}

const STATUS: Record<Exclude<Phase, "closed">, string> = {
  working1: "S_CLASSIFYING",
  round1: "S_CONFIRMING",
  working2: "S_CLASSIFYING",
  round2: "S_CONFIRMING",
};

export function viewOf(t: MultiTicket): TicketView {
  return {
    ticket_id: t.id,
    status: t.final_state ?? STATUS[t.phase as Exclude<Phase, "closed">],
    waiting_for: t.phase === "round1" || t.phase === "round2" ? "reply" : null,
    conversation: structuredClone(t.conversation),
    exit_code: null, // cha không có exit_code (D-30)
    close_reason: null, // cha: close_reason NULL (D-30)
    final_state: t.final_state,
    created_at: t.created_at,
    closed_at: t.closed_at,
    children_progress: t.children.map((c, i) => ({
      child_id: childId(t.id, i + 1),
      index: i + 1,
      title: TITLES[i] ?? "",
      progress: c.progress,
      outcome: c.outcome,
    })),
  };
}

/** GET: pha "đang xử lý" giữ nguyên ở lần GET đầu của pha, sang pha chờ người dùng từ lần GET thứ hai. */
export function readMulti(t: MultiTicket): TicketView {
  if ((t.phase === "working1" || t.phase === "working2") && t.reads >= 1) advance(t);
  t.reads += 1;
  return viewOf(t);
}

/** Các ý cha đang chờ (`awaiting`, P1 §8.2) — null khi cha không ở `parent_reply_wait`. */
export function awaitingOf(t: MultiTicket): Record<string, Need> | null {
  if (t.phase === "round1") return { [childId(t.id, 1)]: "confirm", [childId(t.id, 2)]: "answer" };
  if (t.phase === "round2") return { [childId(t.id, 2)]: "confirm" };
  return null;
}

/** Bảng 5.2.5 (`aggregate_children`): có ý `resolved` → S_RESOLVED (ALL_RESOLVED / PARTIALLY_*); không có: toàn escalated →
 *  S_ESCALATED, toàn rejected → S_REJECTED, trộn → S_ESCALATED (MIXED). */
export function aggregate(outcomes: readonly (ChildOutcome | null)[]): string {
  if (outcomes.includes("resolved")) return "S_RESOLVED";
  if (outcomes.every((o) => o === "rejected")) return "S_REJECTED";
  return "S_ESCALATED";
}

const confirmed = (v: ParentReplyItem): v is { confirmed: boolean; note?: string } => "confirmed" in v;

function answerText(v: ParentReplyItem): string {
  if (!confirmed(v)) return v.answer.trim();
  const note = v.note?.trim();
  return v.confirmed ? "Đã ổn" : note ? `Chưa ổn — ${note}` : "Chưa ổn";
}

/** Áp câu trả lời ĐÃ KIỂM (khoá = đúng `awaitingOf`). Ghi tin user như `reply_text` (theo index, nối " · "), chuyển xuống
 *  từng ý: xác nhận → ý đóng (Chưa ổn = E8, `escalated`), trả lời → ý chạy tiếp. Mọi ý đã đóng → cha đóng theo bảng 5.2.5
 *  + tin vòng cuối CHỈ có câu tổng kết (`items: []`). */
export function applyReply(t: MultiTicket, items: Record<string, ParentReplyItem>, now: number) {
  const entries = Object.entries(items)
    .map(([cid, v]) => [Number(cid.slice(t.id.length + 1)), v] as const)
    .sort(([a], [b]) => a - b);
  t.conversation.push({ role: "user", text: entries.map(([index, v]) => `Ý ${index}: ${answerText(v)}`).join(" · ") });
  for (const [n, v] of entries) {
    const index = n - 1;
    if (confirmed(v)) {
      t.children[index] = { progress: "closed", outcome: v.confirmed ? "resolved" : "escalated" };
    } else {
      t.children[index] = { progress: "processing", outcome: null };
      t.device = v.answer.trim();
    }
  }
  t.reads = 0;
  if (t.children.every((c) => c.progress === "closed")) {
    t.phase = "closed";
    const outcomes = t.children.map((c) => c.outcome);
    t.final_state = aggregate(outcomes);
    t.closed_at = new Date(now).toISOString();
    const rounds = t.conversation.filter((m) => (m as { kind?: unknown }).kind === "digest").length;
    t.conversation.push(digest(rounds + 1, [], summaryText(outcomes)));
  } else {
    t.phase = "working2";
  }
}
