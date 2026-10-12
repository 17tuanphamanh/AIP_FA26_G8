// Ticket cha nhiều ý MINH HOẠ (F6, D-31) — route `/reply` + `children_progress` CHƯA CÓ (Phase 5, T20). Hình dạng theo
// đề xuất PLAN-fe mục 8 (P1 §8.2, B03-B05 §5.4.1, B19 §5.1). Máy trạng thái trong bộ nhớ (mất khi tải lại trang), bám
// vòng của cha ở P1 §8.2 (chốt DỪNG 1 F6, 01/10):
//   working1 (GET đầu: cha S_CLASSIFYING, 3 ý ở 3 trạng thái khác nhau)
//   → round1 (S_CONFIRMING, reply): ý 1 kết quả cần xác nhận · ý 2 câu hỏi có gợi ý · ý 3 bị từ chối
//   → reply 2 khoá → working2 (ý 1 đóng, ý 2 chạy tiếp) → round2: CHỈ ý 2 kết quả cần xác nhận
//   → reply 1 khoá → closed (cha đóng theo bảng B5).
// Câu trả lời ghi thành một tin `{role:"user", text}` (12b Q-fe-33) — server thật sẽ che qua privacy guard; ở đây không.
// Xoá khi: T20 merge — xoá cùng mocks/handlers/employee-multi.ts.
import type { ChildOutcome, ChildProgressState, DigestItem, ParentReplyItem, TicketView } from "../../api/types.ts";

export const MULTI_DEMO_PREFIX = "tkt-demo-multi-";
/** `-1`, `-2`: luồng đủ · `-422`: reply hợp lệ vẫn 422 tại ý 2 · `-409`: reply luôn 409 (trả muộn). */
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

const TITLES = ["Mật khẩu email", "Cài Visio", "Quyền thư mục Kế toán"];
const DEVICES = ["LAP-0342", "PC-1107"];
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

function digest(round: number, items: DigestItem[]) {
  const text = items.map((i) => `Ý ${i.index} – ${i.title}: ${i.text}`).join("\n");
  return { role: "assistant", kind: "digest", round, text, items };
}

function item(id: string, index: number, rest: Omit<DigestItem, "child_id" | "index" | "title">): DigestItem {
  return { child_id: childId(id, index), index, title: TITLES[index - 1] ?? `Ý ${index}`, ...rest };
}

/** Pha "đang xử lý" → pha chờ người dùng: cha gửi MỘT tin tổng hợp (P1 §8.2). */
function advance(t: MultiTicket) {
  if (t.phase === "working1") {
    t.conversation.push(
      digest(1, [
        item(t.id, 1, {
          kind: "result",
          needs: "confirm",
          text: "Đã gửi đường dẫn đặt lại mật khẩu email về số điện thoại đã đăng ký. Bạn đặt lại được chưa?",
          sources: [{ chunk_id: "KB-PWD-002#v1#1", title: "Đặt lại mật khẩu email", heading_path: "Tự đặt lại qua SMS" }],
        }),
        item(t.id, 2, { kind: "question", needs: "answer", text: "Bạn muốn cài Microsoft Visio lên máy nào?", options: [...DEVICES] }),
        item(t.id, 3, {
          kind: "rejection",
          needs: "none",
          text: "Lý do: cần Trưởng phòng Kế toán xác nhận nhu cầu truy cập thư mục Kế toán chung.",
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
    const target = t.device && DEVICES.includes(t.device) ? t.device : "máy bạn đã nêu";
    t.conversation.push(
      digest(2, [item(t.id, 2, { kind: "result", needs: "confirm", text: `Đã cài Microsoft Visio lên ${target}. Bạn mở thử được chưa?` })]),
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
      title: TITLES[i] ?? `Ý ${i + 1}`,
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

/** Bảng đóng cha [Chốt B5]: có ý `resolved` → S_RESOLVED (ALL_RESOLVED / PARTIALLY_*); không có: toàn escalated →
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

/** Áp câu trả lời ĐÃ KIỂM (khoá = đúng `awaitingOf`). Ghi tin user, chuyển xuống từng ý: xác nhận → ý đóng (Chưa ổn =
 *  E8, `escalated`), trả lời → ý chạy tiếp. Mọi ý đã đóng → cha đóng theo bảng B5. */
export function applyReply(t: MultiTicket, items: Record<string, ParentReplyItem>, now: number) {
  const entries = Object.entries(items).sort(([a], [b]) => a.localeCompare(b));
  t.conversation.push({ role: "user", text: entries.map(([cid, v]) => `Ý ${cid.slice(t.id.length + 1)}: ${answerText(v)}`).join(" · ") });
  for (const [cid, v] of entries) {
    const index = Number(cid.slice(t.id.length + 1)) - 1;
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
    t.final_state = aggregate(t.children.map((c) => c.outcome));
    t.closed_at = new Date(now).toISOString();
  } else {
    t.phase = "working2";
  }
}
