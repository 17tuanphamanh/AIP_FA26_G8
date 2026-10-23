// F6 — yêu cầu nhiều ý (D-31) phía nhân viên: dải tiến độ (t66, t67), tin tổng hợp + một nút gửi (t68–t73), ticket thường
// không đổi (t74); N-T20 (hợp đồng thật T20b 5df24c7): t129–t134. Không gọi backend: fetch giả trả đúng hình hợp đồng;
// t73 chạy CHÍNH handler MSW (mocks/handlers/employee-multi.ts) qua `getResponse` làm "máy chủ" để đi trọn chuỗi
// round 1 → round 2 → đóng.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { getResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NOTE_MAX, TEXT_MAX } from "../../api/tickets.ts";
import type { ChildProgress, DigestItem, Me, ParentReplyIn, TicketView } from "../../api/types.ts";
import { DigestMessage } from "../../components/DigestMessage.tsx";
import { digestSummary, normalizeConversation } from "../../components/messages.ts";
import { ProgressStrip } from "../../components/ProgressStrip.tsx";
import { TicketConversation } from "../../components/TicketConversation.tsx";
import { multiHandlers, resetMultiTickets } from "../../mocks/handlers/employee-multi.ts";
import { ChatRoute } from "./ChatPage.tsx";
import {
  checkDigest,
  childHeading,
  digestFieldErrors,
  digestReplyBody,
  EMPTY_DRAFT,
  itemLabel,
  latestRound,
  PARENT_DONE,
  PARENT_FINAL_NOTE,
  PARENT_PROCESSING,
  PARENT_REPLY,
  parentStatusLabel,
  progressItems,
  progressLabel,
  progressTone,
  REPLY_ANSWER_TOO_LONG,
  REPLY_INVALID,
  REPLY_MISSING_ANSWER,
  REPLY_MISSING_CONFIRM,
  REPLY_NOTE_TOO_LONG,
  REPLY_STALE,
  UNKNOWN_OUTCOME_LABEL,
} from "./multi.ts";
import { FINAL_NOTE } from "./status.ts";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear(); // dừng polling trước khi gỡ fetch giả
  resetMultiTickets();
});

// Câu không bao giờ được hiện cho nhân viên (KH 4.2 #3 [Chốt 7.1], P10 §3.1) + mã trạng thái nội bộ.
const LEAK = /tấn công|injection|phát hiện|độc hại|bị chặn|S_[A-Z]{3,}/i;

const PARENT = "5b0e6c1a-2f4d-4e8b-9a7c-1d2e3f4a5b6c";
const C1 = `${PARENT}-1`;
const C2 = `${PARENT}-2`;
const C3 = `${PARENT}-3`;

const ITEMS: DigestItem[] = [
  { child_id: C1, index: 1, title: "Mật khẩu email", kind: "result", needs: "confirm", text: "Đã gửi đường dẫn đặt lại. Bạn đặt lại được chưa?" },
  { child_id: C2, index: 2, title: "Cài Visio", kind: "question", needs: "answer", text: "Bạn muốn cài lên máy nào?" },
  { child_id: C3, index: 3, title: "Quyền thư mục Kế toán", kind: "rejection", needs: "none", text: "Lý do: cần Trưởng phòng xác nhận." },
];
const DIGEST = { role: "assistant", kind: "digest", round: 1, text: "Ý 1 … Ý 2 … Ý 3 …", items: ITEMS };
const PROGRESS: ChildProgress[] = [
  { child_id: C1, index: 1, title: "Mật khẩu email", progress: "needs_user", outcome: null },
  { child_id: C2, index: 2, title: "Cài Visio", progress: "needs_user", outcome: null },
  { child_id: C3, index: 3, title: "Quyền thư mục Kế toán", progress: "closed", outcome: "rejected" },
];

const view = (over: Partial<TicketView> = {}): TicketView => ({
  ticket_id: PARENT,
  status: "S_CONFIRMING",
  waiting_for: "reply",
  conversation: [DIGEST],
  exit_code: null,
  close_reason: null,
  final_state: null,
  created_at: "2026-10-01T08:00:00Z",
  closed_at: null,
  children_progress: PROGRESS,
  ...over,
});

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

type Call = { method: string; url: string; body: string | null };

/** fetch giả: GET ticket → `getView()`; POST /reply → `onReply(body)`. Ghi mọi lời gọi. */
function stubApi(getView: () => TicketView, onReply: (body: unknown) => Response | Promise<Response> = () => json(202, accepted)) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      const body = typeof init.body === "string" ? init.body : null;
      calls.push({ method, url, body });
      if (method === "GET" && url === `/api/tickets/${PARENT}`) return json(200, getView());
      if (method === "POST" && url === `/api/tickets/${PARENT}/reply`) return onReply(body === null ? null : JSON.parse(body));
      return json(404, { detail: "not_found" });
    }),
  );
  return calls;
}
const accepted = { ticket_id: PARENT, status: "S_CONFIRMING", notices: [] };
const replies = (calls: Call[]) => calls.filter((c) => c.method === "POST" && c.url.endsWith("/reply"));
const gets = (calls: Call[]) => calls.filter((c) => c.method === "GET");

function renderChat(id = PARENT) {
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/chat/${id}`]}>
        <Routes>
          <Route path="/chat" element={<p>Trang tạo yêu cầu</p>} />
          <Route path="/chat/:ticketId" element={<ChatRoute />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

const block = (childId: string) => document.querySelector<HTMLElement>(`[data-testid="digest-item"][data-child="${childId}"]`)!;
const blockError = (childId: string) => block(childId).querySelector('[data-testid="digest-item-error"]')?.textContent ?? null;
const sendButton = () => screen.findByRole("button", { name: "Gửi phản hồi" });
const settle = () => new Promise((r) => setTimeout(r, 30));
/** Nhãn trạng thái ở header (có thể có `role=status` khác trong trang: notices, mất kết nối…). */
const pill = () => document.querySelector('header [role="status"]')?.textContent ?? "";
const answerBox = (childId: string, index: number) => within(block(childId)).getByLabelText(`Trả lời ý ${index}`) as HTMLTextAreaElement;
const typeAnswer = (childId: string, index: number, value: string) => fireEvent.change(answerBox(childId, index), { target: { value } });

// ------------------------------------------------------------------------------------------------ t66

describe("t66: nhãn tiến độ từng ý (P1 §8.3) — đủ giá trị, giá trị lạ", () => {
  it.each([
    ["processing", null, "Đang xử lý", "processing"],
    ["pending_approval", null, "Chờ IT duyệt", "waiting"],
    ["ready", null, "Đã có kết quả — chờ tổng hợp", "processing"],
    ["needs_user", null, "Cần bạn phản hồi", "waiting"],
    ["closed", "resolved", "Đã xong", "done"],
    ["closed", "escalated", "Đã chuyển kỹ thuật viên", "closed"],
    ["closed", "rejected", "Không được duyệt", "closed"],
  ])("%s / %s → \"%s\" (chấm %s)", (progress, outcome, label, tone) => {
    expect(progressLabel({ progress, outcome })).toBe(label);
    expect(progressTone({ progress, outcome })).toBe(tone);
  });

  it.each([
    ["progress lạ", "S_EXECUTING", null],
    ["progress rỗng", "", null],
    ["outcome lạ + progress lạ", "archived", "weird"],
  ])("%s → \"Đang xử lý\" (không vỡ, không lộ giá trị)", (_name, progress, outcome) => {
    expect(progressLabel({ progress, outcome })).toBe("Đang xử lý");
    expect(progressTone({ progress, outcome })).toBe("processing");
  });

  it.each([
    ["closed thiếu outcome", null],
    ["closed outcome lạ", "timeout"],
    ["closed outcome 'blocked' (FE cũ — con không bao giờ S_BLOCKED)", "blocked"],
    ["closed outcome prototype", "__proto__"],
  ])("%s → \"Đã kết thúc\", chấm xám — KHÔNG 'Đang xử lý' (Q-fe-47)", (_name, outcome) => {
    expect(progressLabel({ progress: "closed", outcome })).toBe(UNKNOWN_OUTCOME_LABEL);
    expect(UNKNOWN_OUTCOME_LABEL).toBe("Đã kết thúc");
    expect(progressTone({ progress: "closed", outcome })).toBe("closed");
  });

  it("pending_approval KHÔNG BAO GIỜ là 'Đã xong'; dải hiện đủ nhãn, không câu gợi ý tấn công, không mã S_*", () => {
    expect(progressLabel({ progress: "pending_approval", outcome: null })).not.toBe("Đã xong");
    const items = [
      ...PROGRESS,
      { child_id: `${PARENT}-4`, index: 4, title: "VPN", progress: "pending_approval", outcome: null },
      { child_id: `${PARENT}-5`, index: 5, title: "Máy in", progress: "closed", outcome: "blocked" },
      { child_id: `${PARENT}-6`, index: 6, title: "Email", progress: "S_EXECUTING", outcome: null },
    ];
    render(<ProgressStrip items={progressItems(items)!} />);
    const strip = screen.getByRole("group", { name: "Tiến độ từng việc" });
    const texts = [...strip.querySelectorAll('[data-testid="progress-item"]')].map((el) => el.textContent);
    expect(texts).toStrictEqual([
      "Mật khẩu email· Cần bạn phản hồi",
      "Cài Visio· Cần bạn phản hồi",
      "Quyền thư mục Kế toán· Không được duyệt",
      "VPN· Chờ IT duyệt",
      "Máy in· Đã kết thúc",
      "Email· Đang xử lý",
    ]);
    expect(strip.textContent).not.toMatch(LEAK);
    expect(strip.closest('[role="log"]')).toBeNull(); // không phải tin nhắn (P1 §8.3)
  });

  it("nhãn ticket cha (12b Q-fe-34): chờ con → 'Đang xử lý các ý'; chờ trả lời → 'Cần bạn phản hồi'; đóng có ý không xong → không nói 'Đã hoàn tất'", () => {
    const progress = progressItems(PROGRESS)!;
    expect(parentStatusLabel({ final_state: null, waiting_for: null }, progress)).toBe(PARENT_PROCESSING);
    expect(parentStatusLabel({ final_state: null, waiting_for: "reply" }, progress)).toBe(PARENT_REPLY);
    const mixed = progressItems([
      { ...PROGRESS[0]!, progress: "closed", outcome: "resolved" },
      { ...PROGRESS[1]!, progress: "closed", outcome: "resolved" },
      PROGRESS[2]!,
    ])!;
    expect(parentStatusLabel({ final_state: "S_RESOLVED", waiting_for: null }, mixed)).toBe(PARENT_DONE);
    const allDone = progressItems(PROGRESS.map((p) => ({ ...p, progress: "closed", outcome: "resolved" })))!;
    expect(parentStatusLabel({ final_state: "S_RESOLVED", waiting_for: null }, allDone)).toBe("Đã hoàn tất");
    expect(parentStatusLabel({ final_state: "S_ESCALATED", waiting_for: null }, mixed)).toBe("Đã chuyển kỹ thuật viên hỗ trợ");
  });
});

// ------------------------------------------------------------------------------------------------ t67

describe("t67: chuẩn hoá children_progress + tin digest (hình dạng đã kiểm ở api/tickets.ts — t127, t128)", () => {
  it("progressItems: thiếu / null / rỗng → null (ticket thường); có → sắp theo index, không đổi giá trị", () => {
    expect(progressItems(undefined)).toBeNull();
    expect(progressItems(null)).toBeNull();
    expect(progressItems([])).toBeNull();
    const [a, b] = PROGRESS;
    expect(progressItems([b!, a!])).toStrictEqual([a, b]);
  });

  it("digest → khối theo index; kind/needs lạ → kết quả / không hỏi; KHÔNG options/sources (hợp đồng thật); cùng ý nhiều khối giữ đủ, đúng thứ tự", () => {
    const [m] = normalizeConversation([
      {
        role: "assistant",
        kind: "digest",
        round: 2,
        text: "chữ thuần",
        items: [
          { child_id: "k-2", index: 2, title: "Hai", kind: "weird", needs: "maybe", text: "b", options: ["x"] },
          { child_id: "k-1", index: 1, title: "Một", kind: "question", needs: "answer", text: "a", sources: [{ chunk_id: "c", title: "t", heading_path: "h" }] },
          { child_id: "k-3", index: 3, kind: "result", needs: "none", text: "thiếu title" },
          { child_id: "k-2", index: 2, title: "Hai", kind: "result", needs: "confirm", text: "c" },
        ],
      },
    ]);
    expect(m?.digest).toStrictEqual({
      round: 2,
      items: [
        { child_id: "k-1", index: 1, title: "Một", kind: "question", needs: "answer", text: "a" },
        { child_id: "k-2", index: 2, title: "Hai", kind: "result", needs: "none", text: "b" },
        { child_id: "k-2", index: 2, title: "Hai", kind: "result", needs: "confirm", text: "c" },
      ],
    });
  });

  it.each([
    ["round 0", { round: 0, items: ITEMS }],
    ["round chuỗi", { round: "1", items: ITEMS }],
    ["items không phải mảng", { round: 1, items: {} }],
    ["không khối nào hợp lệ", { round: 1, items: [{ index: 1 }] }],
    ["items rỗng (vòng cuối chỉ có câu tổng kết)", { round: 3, items: [] }],
  ])("%s → không có digest, hiện `text` như tin thường (Q-fe-2)", (_name, rest) => {
    const [m] = normalizeConversation([{ role: "assistant", kind: "digest", text: "Bản chữ thuần của tin tổng hợp", ...rest }]);
    expect(m?.digest).toBeUndefined();
    expect(m?.text).toBe("Bản chữ thuần của tin tổng hợp");
    expect(normalizeConversation([{ role: "assistant", kind: "digest", round: 0, items: [] }])).toStrictEqual([]);
  });

  it("latestRound = round lớn nhất trong các tin digest có khối; không có → null", () => {
    const messages = normalizeConversation([
      { ...DIGEST, round: 1 },
      { role: "user", text: "Ý 1: Đã ổn" },
      { ...DIGEST, round: 3 },
      { ...DIGEST, round: 2 },
      { role: "assistant", kind: "digest", round: 9, text: "Cả 3 yêu cầu đã hoàn tất.", items: [] },
    ]);
    expect(latestRound(messages)).toBe(3);
    expect(latestRound(normalizeConversation([{ role: "assistant", kind: "answer", text: "x" }]))).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t68

describe("t68: thiếu trả lời → lỗi NGAY dưới đúng khối, 0 POST", () => {
  it("bấm 'Gửi phản hồi' khi chưa chọn gì → ý 1 'Chọn Đã ổn hoặc Chưa ổn', ý 2 'Cần trả lời…', ý 3 không lỗi; 0 POST", async () => {
    const calls = stubApi(() => view());
    renderChat();
    fireEvent.click(await sendButton());
    expect(blockError(C1)).toBe(REPLY_MISSING_CONFIRM);
    expect(blockError(C2)).toBe(REPLY_MISSING_ANSWER);
    expect(REPLY_MISSING_ANSWER).toBe("Cần trả lời trước khi gửi.");
    expect(blockError(C3)).toBeNull();
    // Lỗi gắn đúng ô (aria-describedby trỏ tới câu lỗi của CHÍNH khối đó).
    const answer = within(block(C2)).getByLabelText("Trả lời ý 2");
    expect(answer.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(answer.getAttribute("aria-describedby")!)?.textContent).toBe(REPLY_MISSING_ANSWER);

    // Chọn ý 1 → lỗi ý 1 biến mất ngay; ý 2 vẫn thiếu → bấm lại vẫn 0 POST.
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    expect(blockError(C1)).toBeNull();
    fireEvent.click(await sendButton());
    expect(blockError(C2)).toBe(REPLY_MISSING_ANSWER);
    // Câu trả lời chỉ khoảng trắng = chưa trả lời.
    fireEvent.change(within(block(C2)).getByLabelText("Trả lời ý 2"), { target: { value: "  \n " } });
    fireEvent.click(await sendButton());
    expect(blockError(C2)).toBe(REPLY_MISSING_ANSWER);
    expect(within(block(C2)).queryByRole("group", { name: /Gợi ý/ })).toBeNull(); // không còn nút gợi ý (không có `options`)
    await settle();
    expect(replies(calls)).toHaveLength(0);
  });

  it("checkDigest: chưa trả lời → 'Cần trả lời trước khi gửi.'; quá dài → câu giới hạn; ý needs=none không bao giờ lỗi", () => {
    const plain: DigestItem = ITEMS[1]!;
    expect(checkDigest([plain], {})).toStrictEqual({ [C2]: REPLY_MISSING_ANSWER });
    expect(REPLY_MISSING_ANSWER).toBe("Cần trả lời trước khi gửi.");
    expect(checkDigest([plain], { [C2]: { ...EMPTY_DRAFT, answer: "x".repeat(TEXT_MAX + 1) } })).toStrictEqual({ [C2]: REPLY_ANSWER_TOO_LONG });
    expect(checkDigest([ITEMS[0]!], { [C1]: { choice: false, note: "y".repeat(NOTE_MAX + 1), answer: "" } })).toStrictEqual({
      [C1]: REPLY_NOTE_TOO_LONG,
    });
    expect(checkDigest([ITEMS[2]!], {})).toStrictEqual({});
  });
});

// ------------------------------------------------------------------------------------------------ t69

describe("t69: body /reply CHỈ có khối needs≠none, đúng hình {answer} / {confirmed[, note]}", () => {
  it("Đã ổn + gõ ' LAP-0342 ' → đúng 1 POST, body {items:{ý1:{confirmed:true}, ý2:{answer:'LAP-0342'}}} — không có ý bị từ chối", async () => {
    const calls = stubApi(() => view());
    renderChat();
    await sendButton();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    typeAnswer(C2, 2, " LAP-0342 ");
    fireEvent.click(await sendButton());
    await waitFor(() => expect(replies(calls)).toHaveLength(1));
    expect(JSON.parse(replies(calls)[0]!.body!)).toStrictEqual({ items: { [C1]: { confirmed: true }, [C2]: { answer: "LAP-0342" } } });
  });

  it("digestReplyBody: Chưa ổn + ghi chú (trim) · Chưa ổn ghi chú rỗng → không khoá note · đổi sang Đã ổn → bỏ ghi chú", () => {
    const items = ITEMS;
    expect(digestReplyBody(items, { [C1]: { choice: false, note: "  vẫn lỗi  ", answer: "" }, [C2]: { ...EMPTY_DRAFT, answer: " PC-1107 " } })).toStrictEqual({
      items: { [C1]: { confirmed: false, note: "vẫn lỗi" }, [C2]: { answer: "PC-1107" } },
    });
    expect(digestReplyBody(items, { [C1]: { choice: false, note: "   ", answer: "" }, [C2]: { ...EMPTY_DRAFT, answer: "Máy ở nhà" } })).toStrictEqual({
      items: { [C1]: { confirmed: false }, [C2]: { answer: "Máy ở nhà" } },
    });
    expect(digestReplyBody(items, { [C1]: { choice: true, note: "ghi chú cũ", answer: "" }, [C2]: { ...EMPTY_DRAFT, answer: "x" } }).items[C1]).toStrictEqual({
      confirmed: true,
    });
    expect(Object.keys(digestReplyBody(items, {}).items)).toStrictEqual([C1, C2]);
  });

  it("màn: Chưa ổn → hiện ô ghi chú (không bắt buộc), gửi kèm note; câu trả lời gõ tay gửi đúng chữ (đã trim)", async () => {
    const calls = stubApi(() => view());
    renderChat();
    await sendButton();
    expect(within(block(C1)).queryByLabelText(/Ghi chú cho ý 1/)).toBeNull();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Chưa ổn" }));
    fireEvent.change(within(block(C1)).getByLabelText(/Ghi chú cho ý 1/), { target: { value: " vẫn không vào được " } });
    typeAnswer(C2, 2, "PC-1107 và LAP-0342");
    fireEvent.click(await sendButton());
    await waitFor(() => expect(replies(calls)).toHaveLength(1));
    expect(JSON.parse(replies(calls)[0]!.body!)).toStrictEqual({
      items: { [C1]: { confirmed: false, note: "vẫn không vào được" }, [C2]: { answer: "PC-1107 và LAP-0342" } },
    });
  });
});

// ------------------------------------------------------------------------------------------------ t70

describe("t70: 422 fields → lỗi tại ĐÚNG khối theo child_id; field không thuộc khối → lỗi chung dưới nút", () => {
  async function fillAndSend() {
    await sendButton();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    typeAnswer(C2, 2, "LAP-0342");
    fireEvent.click(await sendButton());
  }

  it("fields ['body.items.<ý 2>.answer'] → lỗi CHỈ dưới ý 2; ý 1, ý 3 không lỗi; không lỗi chung", async () => {
    stubApi(() => view(), () => json(422, { error: "invalid_request", fields: [`body.items.${C2}.answer`] }));
    renderChat();
    await fillAndSend();
    await waitFor(() => expect(blockError(C2)).toBe(REPLY_INVALID));
    expect(blockError(C1)).toBeNull();
    expect(blockError(C3)).toBeNull();
    expect(screen.queryByTestId("digest-error")).toBeNull();
  });

  it("fields ['body.items.<ý 1>.note'] → câu giới hạn ghi chú dưới ý 1", async () => {
    stubApi(() => view(), () => json(422, { error: "invalid_request", fields: [`body.items.${C1}.note`] }));
    renderChat();
    await fillAndSend();
    await waitFor(() => expect(blockError(C1)).toBe(REPLY_NOTE_TOO_LONG));
    expect(blockError(C2)).toBeNull();
  });

  it("fields ['body.items.<extra>'] (không map được) → lỗi chung dưới nút, không khối nào đỏ", async () => {
    stubApi(() => view(), () => json(422, { error: "invalid_request", fields: ["body.items.<extra>"] }));
    renderChat();
    await fillAndSend();
    expect((await screen.findByTestId("digest-error")).textContent).toBe("Dữ liệu chưa hợp lệ — kiểm tra lại các ô được đánh dấu.");
    for (const id of [C1, C2, C3]) expect(blockError(id)).toBeNull();
  });

  it("digestFieldErrors: khớp đúng ranh giới child_id (x-1 ≠ x-10), field lạ → general", () => {
    expect(digestFieldErrors(["items.x-10.answer"], ["x-1", "x-10"])).toStrictEqual({ byChild: { "x-10": REPLY_INVALID }, general: false });
    expect(digestFieldErrors(["items.x-1"], ["x-1", "x-10"])).toStrictEqual({ byChild: { "x-1": REPLY_INVALID }, general: false });
    expect(digestFieldErrors(["items", "items.x-2.answer"], ["x-1"])).toStrictEqual({ byChild: {}, general: true });
    expect(digestFieldErrors([], ["x-1"])).toStrictEqual({ byChild: {}, general: true });
  });
});

// ------------------------------------------------------------------------------------------------ t71

describe("t71 / t131: 409 (trả muộn) → câu 'đã quá hạn/đã thay đổi' của giao diện + tải lại ticket", () => {
  it("409 → REPLY_STALE dưới nút (KHÔNG chữ server), GET ticket thêm lần nữa, không khối nào đỏ", async () => {
    const calls = stubApi(() => view(), () => json(409, { detail: "Yêu cầu đã chuyển sang bước khác" }));
    renderChat();
    await sendButton();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    typeAnswer(C2, 2, "PC-1107");
    const before = gets(calls).length;
    fireEvent.click(await sendButton());
    expect((await screen.findByTestId("digest-error")).textContent).toBe(REPLY_STALE);
    expect(REPLY_STALE).toBe("Phản hồi này đã quá hạn hoặc yêu cầu đã thay đổi — đang tải lại nội dung mới.");
    expect(document.body.textContent).not.toContain("Yêu cầu đã chuyển sang bước khác");
    await waitFor(() => expect(gets(calls).length).toBeGreaterThan(before));
    for (const id of [C1, C2, C3]) expect(blockError(id)).toBeNull();
    expect(replies(calls)).toHaveLength(1);
  });
});

// ------------------------------------------------------------------------------------------------ t72

describe("t72: bấm 'Gửi phản hồi' nhiều lần trong một nhịp → đúng 1 POST", () => {
  it("click ×3 khi request đang bay → 1 POST", async () => {
    const calls = stubApi(
      () => view(),
      () => new Promise((resolve) => setTimeout(() => resolve(json(202, accepted)), 30)),
    );
    renderChat();
    await sendButton();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    typeAnswer(C2, 2, "LAP-0342");
    const send = await sendButton();
    fireEvent.click(send);
    fireEvent.click(send);
    fireEvent.click(send);
    await new Promise((r) => setTimeout(r, 80));
    expect(replies(calls)).toHaveLength(1);
  });
});

// ------------------------------------------------------------------------------------------------ t73

const EMPLOYEE: Me = { user_id: "nv001", role: "employee", permissions: ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"] };
const DEMO = "tkt-demo-multi-1";

/** "Máy chủ" = CHÍNH handler MSW nhiều ý (máy trạng thái P1 §8.2); `/api/auth/me` (handler gọi qua bypass) → nhân viên. */
function stubMultiServer() {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string | Request, init: RequestInit = {}) => {
      const request = typeof input === "string" ? new Request(new URL(input, location.href), init) : input;
      const path = new URL(request.url).pathname;
      if (path === "/api/auth/me") return json(200, EMPLOYEE);
      calls.push({ method: request.method, url: path, body: typeof init.body === "string" ? init.body : null });
      return (await getResponse(multiHandlers, request)) ?? json(404, { detail: "Not Found" });
    }),
  );
  return calls;
}

const digests = () => [...document.querySelectorAll<HTMLElement>('[data-testid="digest"]')];
const stripTexts = () => [...document.querySelectorAll('[data-testid="progress-item"]')].map((el) => el.textContent);

describe("t73: chuỗi round 1 (2 khoá) → round 2 (1 khối, round 1 chỉ đọc) → 1 khoá → cha đóng", () => {
  it("dải tiến độ cập nhật theo từng lượt; chỉ tin round lớn nhất có form; câu cuối theo Q-fe-34", async () => {
    const calls = stubMultiServer();
    const client = renderChat(DEMO);
    const refetch = () => client.invalidateQueries({ queryKey: ["ticket", DEMO] }); // thay một nhịp polling

    // GET đầu: cha đang chờ các ý — dải 3 trạng thái khác nhau, chưa có tin nào, không form.
    await screen.findByRole("group", { name: "Tiến độ từng việc" });
    expect(stripTexts()).toStrictEqual([
      "Đặt lại mật khẩu· Đã có kết quả — chờ tổng hợp",
      "Cài đặt phần mềm· Chờ IT duyệt",
      "Cấp quyền truy cập· Đang xử lý",
    ]);
    expect(pill()).toContain(PARENT_PROCESSING);
    expect(digests()).toHaveLength(0);

    // Round 1: một tin, 3 khối, một nút.
    await refetch();
    await sendButton();
    expect(screen.getAllByRole("button", { name: "Gửi phản hồi" })).toHaveLength(1);
    expect(digests()).toHaveLength(1);
    expect(pill()).toContain(PARENT_REPLY);
    const c = (n: number) => `${DEMO}-${n}`;
    fireEvent.click(within(block(c(1))).getByRole("button", { name: "Đã ổn" }));
    typeAnswer(c(2), 2, "LAP-0342");
    fireEvent.click(await sendButton());
    await waitFor(() => expect(replies(calls)).toHaveLength(1));
    expect(Object.keys(JSON.parse(replies(calls)[0]!.body!).items)).toStrictEqual([c(1), c(2)]);

    // Sau 202: tin người dùng (Q-fe-33), ý 2 chạy tiếp; round 1 thành chỉ đọc.
    await screen.findByText("Ý 1: Đã ổn · Ý 2: LAP-0342");
    expect(stripTexts()).toStrictEqual(["Đặt lại mật khẩu· Đã xong", "Cài đặt phần mềm· Đang xử lý", "Cấp quyền truy cập· Không được duyệt"]);

    // Round 2: CHỈ ý 2 cần xác nhận; tin round 1 vẫn còn nhưng chỉ đọc.
    await refetch();
    await waitFor(() => expect(digests()).toHaveLength(2));
    const [round1, round2] = digests();
    expect(round1!.dataset.active).toBe("false");
    expect(within(round1!).queryAllByRole("button")).toHaveLength(0);
    expect(within(round1!).queryByRole("textbox")).toBeNull();
    expect(within(round1!).getByRole("link", { name: "Tạo yêu cầu mới" }).getAttribute("href")).toBe("/chat");
    expect(round2!.dataset.active).toBe("true");
    expect(within(round2!).getAllByTestId("digest-item").map((el) => el.dataset.child)).toStrictEqual([c(2)]);
    expect(within(round2!).getByTestId("digest-item").textContent).toContain("Đã cài Microsoft Visio lên máy LAP-0342.");
    expect(screen.getAllByRole("button", { name: "Gửi phản hồi" })).toHaveLength(1);
    fireEvent.click(within(round2!).getByRole("button", { name: "Đã ổn" }));
    fireEvent.click(within(round2!).getByRole("button", { name: "Gửi phản hồi" }));
    await waitFor(() => expect(replies(calls)).toHaveLength(2));
    expect(JSON.parse(replies(calls)[1]!.body!)).toStrictEqual({ items: { [c(2)]: { confirmed: true } } });

    // Cha đóng: dải đủ outcome, câu cuối KHÔNG nói "đã hoàn tất" (có ý không được duyệt), không còn form nào.
    expect((await screen.findByTestId("final-note")).textContent).toContain(PARENT_FINAL_NOTE);
    expect(screen.getByTestId("final-note").textContent).not.toContain(FINAL_NOTE.S_RESOLVED!);
    expect(stripTexts()).toStrictEqual(["Đặt lại mật khẩu· Đã xong", "Cài đặt phần mềm· Đã xong", "Cấp quyền truy cập· Không được duyệt"]);
    expect(pill()).toContain(PARENT_DONE);
    // Vòng cuối không còn khối → tin `items: []` chỉ có câu tổng kết (bảng 5.2.5) — hiện như tin thường, không form.
    expect(screen.getByText("Đã xong 2/3 yêu cầu; có yêu cầu không được duyệt.")).toBeTruthy();
    expect(digests()).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "Gửi phản hồi" })).toBeNull();
    expect(document.body.textContent).not.toMatch(LEAK);
  });

  it("waiting_for ≠ reply (đang xử lý / đã đóng) → tin digest chỉ đọc dù là round lớn nhất", async () => {
    stubApi(() => view({ status: "S_CLASSIFYING", waiting_for: null }));
    renderChat();
    await screen.findByTestId("digest");
    expect(screen.queryByRole("button", { name: "Gửi phản hồi" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Đã ổn" })).toBeNull();
    expect(screen.queryByLabelText("Trả lời ý 2")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t74

describe("t74: ticket thường (không children_progress) — hành vi F2 không đổi", () => {
  const plain = (over: Partial<TicketView>): TicketView => {
    const v = view({ conversation: [{ role: "assistant", kind: "answer", text: "VPN dùng cổng 443." }], ...over });
    delete v.children_progress;
    return v;
  };

  it.each([
    ["thiếu khoá", undefined],
    ["null", null],
    ["mảng rỗng", []],
  ])("children_progress %s → không dải tiến độ; chờ xác nhận → nhãn + nút + ô ghi chú như F2", async (_name, progress) => {
    const v = plain({ status: "S_CONFIRMING", waiting_for: "confirm" });
    if (progress !== undefined) v.children_progress = progress as TicketView["children_progress"];
    stubApi(() => v);
    renderChat();
    await screen.findByText("Vấn đề của bạn đã được giải quyết chưa?");
    expect(screen.queryByTestId("progress-strip")).toBeNull();
    expect(pill()).toContain("Chờ bạn xác nhận kết quả");
    expect(screen.getByRole("button", { name: "Đã ổn" })).toBeTruthy();
    expect((screen.getByLabelText("Ghi chú nếu chưa ổn") as HTMLTextAreaElement).disabled).toBe(false);
    expect(screen.queryByTestId("digest")).toBeNull();
  });

  it("đang xử lý / đã xong → câu ticket thường (không 'các ý'); kind lạ hiện như tin thường", async () => {
    let v = plain({ status: "S_RETRIEVING", waiting_for: null, conversation: [{ role: "assistant", kind: "rejection", text: "IT chưa duyệt." }] });
    stubApi(() => v);
    const client = renderChat();
    expect((await screen.findByTestId("processing")).textContent).toBe("Đang tra cứu hướng dẫn… Bạn không cần làm gì.");
    expect(screen.getByText("IT chưa duyệt.")).toBeTruthy();
    v = plain({ status: "S_RESOLVED", waiting_for: null, final_state: "S_RESOLVED" });
    await client.invalidateQueries({ queryKey: ["ticket", PARENT] });
    expect((await screen.findByTestId("final-note")).textContent).toContain(FINAL_NOTE.S_RESOLVED!);
    expect(pill()).toContain("Đã hoàn tất");
    expect(document.body.textContent).not.toContain("các ý");
  });
});

// ------------------------------------------------------------------------------------------------ t125 (N-PROTO P3)

describe("t125: child_id / kind '__proto__' / 'constructor' / 'toString' — khoá riêng khi đọc VÀ khi ghi", () => {
  const ODD: DigestItem[] = [
    { child_id: "constructor", index: 1, title: "Cài Visio", kind: "question", needs: "answer", text: "Máy nào?" },
    { child_id: "__proto__", index: 2, title: "Mật khẩu email", kind: "result", needs: "confirm", text: "Đã gửi đường dẫn." },
    { child_id: "toString", index: 3, title: "Máy in", kind: "question", needs: "answer", text: "Tầng mấy?" },
  ];
  const ids = ODD.map((i) => i.child_id);
  /** Object có khoá RIÊNG "__proto__" (viết literal `{"__proto__": …}` trong mã JS là đổi prototype). */
  const own = <T,>(raw: string) => JSON.parse(raw) as Record<string, T>;
  /** id prototype KHÔNG đúng dạng "<cha>-<index>" → không bao giờ qua `parseTicketView` (t129); lớp DigestMessage vẫn phải an
   *  toàn với khoá đó → vẽ THẲNG DigestMessage (không qua ChatPage), "máy chủ" = `onSend`. */
  function renderOdd(items: DigestItem[]) {
    const sent: ParentReplyIn[] = [];
    const onSend = async (body: ParentReplyIn) => {
      sent.push(body);
      return { ok: true } as const;
    };
    render(
      <MemoryRouter>
        <DigestMessage digest={{ round: 1, items }} form={{ sending: false, onSend }} />
      </MemoryRouter>,
    );
    return sent;
  }
  const childErrors = () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    return () => spy.mock.calls.filter((args) => args.some((a) => String(a).includes("React child")));
  };

  it("itemLabel: kind prototype → nhãn 'Đã xử lý' như kind lạ; kind hợp lệ giữ nhãn", () => {
    for (const kind of ["__proto__", "constructor", "toString"]) {
      expect(itemLabel({ kind: kind as DigestItem["kind"] })).toBe("Đã xử lý");
    }
    expect(itemLabel({ kind: "question" })).toBe("Cần bạn trả lời");
  });

  it("checkDigest: chưa trả lời → lỗi ở ĐỦ 3 khoá riêng (lỗi '__proto__' không bị nuốt); nháp đủ → không lỗi", () => {
    const errors = checkDigest(ODD, {});
    expect(Object.keys(errors)).toStrictEqual(ids);
    expect(errors).toStrictEqual(
      own(`{"constructor": "${REPLY_MISSING_ANSWER}", "__proto__": "${REPLY_MISSING_CONFIRM}", "toString": "${REPLY_MISSING_ANSWER}"}`),
    );
    const drafts = own<typeof EMPTY_DRAFT>(
      '{"constructor": {"choice": null, "note": "", "answer": "LAP-0342"}, "__proto__": {"choice": true, "note": "", "answer": ""},' +
        ' "toString": {"choice": null, "note": "", "answer": "Tầng 3"}}',
    );
    expect(checkDigest(ODD, drafts)).toStrictEqual({});
  });

  it("digestReplyBody: body JSON có đủ 3 khoá, đúng giá trị; nháp thiếu → nháp rỗng (không đọc prototype)", () => {
    const drafts = own<typeof EMPTY_DRAFT>(
      '{"constructor": {"choice": null, "note": "", "answer": " LAP-0342 "}, "__proto__": {"choice": false, "note": " vẫn lỗi ", "answer": ""}}',
    );
    expect(JSON.stringify(digestReplyBody(ODD, drafts))).toBe(
      '{"items":{"constructor":{"answer":"LAP-0342"},"__proto__":{"confirmed":false,"note":"vẫn lỗi"},"toString":{"answer":""}}}',
    );
    expect(JSON.stringify(digestReplyBody(ODD, {}))).toBe('{"items":{"constructor":{"answer":""},"__proto__":{"confirmed":false},"toString":{"answer":""}}}');
  });

  it("digestFieldErrors: 422 fields theo 3 khoá → lỗi ở đúng 3 khoá riêng", () => {
    const { byChild, general } = digestFieldErrors(["items.__proto__.note", "items.constructor", "items.toString.answer"], ids);
    expect(general).toBe(false);
    expect(byChild).toStrictEqual(own(`{"__proto__": "${REPLY_NOTE_TOO_LONG}", "constructor": "${REPLY_INVALID}", "toString": "${REPLY_INVALID}"}`));
  });

  it("màn: gửi trống → lỗi dưới đủ 3 khối, 0 POST; gõ/chọn → lỗi khối đó mất; gửi → body đúng 3 khoá", async () => {
    const errors = childErrors();
    const sent = renderOdd(ODD);
    fireEvent.click(await sendButton());
    expect(ids.map(blockError)).toStrictEqual([REPLY_MISSING_ANSWER, REPLY_MISSING_CONFIRM, REPLY_MISSING_ANSWER]);
    expect(ids.map((id) => block(id).querySelector("span.shrink-0")?.textContent)).toStrictEqual(["Cần bạn trả lời", "Đã xử lý", "Cần bạn trả lời"]);

    const first = within(block("constructor")).getByLabelText("Trả lời ý 1") as HTMLTextAreaElement;
    fireEvent.change(first, { target: { value: "LAP-0342 tầng 2" } });
    expect(first.value).toBe("LAP-0342 tầng 2");
    expect(blockError("constructor")).toBeNull();
    fireEvent.click(within(block("__proto__")).getByRole("button", { name: "Đã ổn" }));
    expect(blockError("__proto__")).toBeNull();
    fireEvent.change(within(block("toString")).getByLabelText("Trả lời ý 3"), { target: { value: " Tầng 3 " } });
    expect(blockError("toString")).toBeNull();
    await settle();
    expect(sent).toHaveLength(0);

    fireEvent.click(await sendButton());
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(JSON.stringify(sent[0])).toBe(
      '{"items":{"constructor":{"answer":"LAP-0342 tầng 2"},"__proto__":{"confirmed":true},"toString":{"answer":"Tầng 3"}}}',
    );
    expect(errors()).toHaveLength(0);
    expect(document.body.textContent).not.toMatch(/function |\[object /);
  });

  it("màn: khối 'constructor' xác nhận — 'Chưa ổn' không ghi chú → body {confirmed:false} (nháp đủ trường, không lấy từ prototype)", async () => {
    const sent = renderOdd([{ ...ODD[1]!, child_id: "constructor", index: 1 }]);
    await sendButton();
    fireEvent.click(within(block("constructor")).getByRole("button", { name: "Chưa ổn" }));
    expect((within(block("constructor")).getByLabelText(/Ghi chú cho ý 1/) as HTMLTextAreaElement).value).toBe("");
    fireEvent.click(await sendButton());
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(JSON.stringify(sent[0])).toBe('{"items":{"constructor":{"confirmed":false}}}');
  });

  it("khối hợp lệ (child_id thường) vẫn như cũ", () => {
    expect(checkDigest([ITEMS[0]!], {})).toStrictEqual({ [C1]: REPLY_MISSING_CONFIRM });
  });
});

// ------------------------------------------------------------------------------------------------ t129 (N-T20 P2, Q-fe-46)

const DATA_ERROR = "Chưa đọc được dữ liệu của yêu cầu này. Vui lòng tải lại trang.";

describe("t129: thân ticket sai hình dạng → lỗi dữ liệu chung, KHÔNG vẽ một phần (Q-fe-46 = A)", () => {
  it("lần tải đầu hỏng (1 phần tử children_progress sai child_id) → 'Chưa tải được yêu cầu.' + câu lỗi dữ liệu; không dải, không khối, không nút", async () => {
    const broken = view({ children_progress: [PROGRESS[0]!, { ...PROGRESS[1]!, child_id: `${PARENT}-9` }, PROGRESS[2]!] });
    stubApi(() => broken);
    renderChat();
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Chưa tải được yêu cầu.");
    expect(screen.getByText(DATA_ERROR)).toBeTruthy();
    expect(screen.queryByTestId("progress-strip")).toBeNull();
    expect(screen.queryByTestId("digest")).toBeNull();
    expect(screen.queryByRole("button", { name: "Gửi phản hồi" })).toBeNull();
  });

  it("đang polling mà thân mới hỏng (digest có 2 khối cùng con cần trả lời) → giữ bản hợp lệ cũ + dòng lỗi dữ liệu (không 'mất kết nối')", async () => {
    let current = view();
    stubApi(() => current);
    const client = renderChat();
    await sendButton();
    current = view({ conversation: [{ ...DIGEST, items: [...ITEMS, { ...ITEMS[0]!, kind: "question", needs: "answer" }] }] });
    await client.invalidateQueries({ queryKey: ["ticket", PARENT] });
    expect(await screen.findByText(DATA_ERROR)).toBeTruthy();
    expect(screen.queryByText(/Tạm mất kết nối/)).toBeNull();
    expect(document.querySelectorAll('[data-testid="digest-item"]')).toHaveLength(3); // bản cũ, đủ khối
    expect(screen.getAllByTestId("progress-item")).toHaveLength(3);
  });

  it("màn IT chỉ đọc (TicketConversation) → 'Chưa tải được hội thoại: <câu lỗi dữ liệu>', không khối nào", async () => {
    stubApi(() => view({ conversation: [{ ...DIGEST, items: [{ ...ITEMS[0]!, child_id: "constructor" }] }] }));
    const client = new QueryClient();
    clients.push(client);
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <TicketConversation ticketId={PARENT} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect((await screen.findByRole("alert")).textContent).toBe(`Chưa tải được hội thoại: ${DATA_ERROR}`);
    expect(screen.queryByTestId("digest")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t130

describe("t130: title '' (child_title không có seed) → 'Ý n', không dấu '–' thừa", () => {
  it("childHeading + dải tiến độ + khối", async () => {
    expect(childHeading({ index: 2, title: "" })).toBe("Ý 2");
    expect(childHeading({ index: 2, title: "Cài Visio" })).toBe("Ý 2 – Cài Visio");
    stubApi(() =>
      view({
        conversation: [{ ...DIGEST, items: ITEMS.map((i) => (i.index === 1 ? { ...i, title: "" } : i)) }],
        children_progress: PROGRESS.map((p) => (p.index === 1 ? { ...p, title: "" } : p)),
      }),
    );
    renderChat();
    await sendButton();
    expect(stripTexts()[0]).toBe("Ý 1· Cần bạn phản hồi");
    expect(block(C1).querySelector("h3")?.textContent).toBe("Ý 1");
    expect(block(C2).querySelector("h3")?.textContent).toBe("Ý 2 – Cài Visio");
  });
});

// ------------------------------------------------------------------------------------------------ t132 (P3 — dạng field THẬT)

describe("t132: 422 với dạng field thật của T20b — vị trí chung / Pydantic / ranh giới uuid-1 ≠ uuid-10", () => {
  const C10 = `${PARENT}-10`;

  it("digestFieldErrors: 'items' (đã bỏ body.) → chung; Pydantic items.<cid>.ReplyAnswer.answer → đúng ý; ReplyConfirm.note → câu ghi chú; uuid-1 ≠ uuid-10", () => {
    expect(digestFieldErrors(["items"], [C1, C2])).toStrictEqual({ byChild: {}, general: true });
    expect(digestFieldErrors([`items.${C1}.ReplyAnswer.answer`, `items.${C1}.ReplyConfirm.confirmed`], [C1, C10])).toStrictEqual({
      byChild: { [C1]: REPLY_INVALID },
      general: false,
    });
    expect(digestFieldErrors([`items.${C1}.ReplyAnswer.answer`, `items.${C1}.ReplyConfirm.note`], [C1])).toStrictEqual({
      byChild: { [C1]: REPLY_NOTE_TOO_LONG },
      general: false,
    });
    expect(digestFieldErrors([`items.${C10}`], [C1, C10])).toStrictEqual({ byChild: { [C10]: REPLY_INVALID }, general: false });
    expect(digestFieldErrors([`items.${C10}.ReplyAnswer.answer`], [C1])).toStrictEqual({ byChild: {}, general: true });
    expect(digestFieldErrors([`items.${C1}0`], [C1])).toStrictEqual({ byChild: {}, general: true });
  });

  it("màn: 422 fields ['body.items'] (khoá sai dạng — vị trí CHUNG) → lỗi chung dưới nút, không khối nào đỏ", async () => {
    stubApi(() => view(), () => json(422, { error: "invalid_request", fields: ["body.items"] }));
    renderChat();
    await sendButton();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    typeAnswer(C2, 2, "30");
    fireEvent.click(await sendButton());
    expect((await screen.findByTestId("digest-error")).textContent).toBe("Dữ liệu chưa hợp lệ — kiểm tra lại các ô được đánh dấu.");
    for (const id of [C1, C2, C3]) expect(blockError(id)).toBeNull();
  });

  it("màn: 422 fields ['body.items.<uuid>-1'] khi có ý 10 → lỗi CHỈ dưới ý 1", async () => {
    const ten: DigestItem = { child_id: C10, index: 10, title: "VPN", kind: "result", needs: "confirm", text: "Đã gia hạn." };
    stubApi(
      () => view({ conversation: [{ ...DIGEST, items: [...ITEMS, ten] }], children_progress: [...PROGRESS, { child_id: C10, index: 10, title: "VPN", progress: "needs_user", outcome: null }] }),
      () => json(422, { error: "invalid_request", fields: [`body.items.${C1}`] }),
    );
    renderChat();
    await sendButton();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    fireEvent.click(within(block(C10)).getByRole("button", { name: "Đã ổn" }));
    typeAnswer(C2, 2, "30");
    fireEvent.click(await sendButton());
    await waitFor(() => expect(blockError(C1)).toBe(REPLY_INVALID));
    expect(blockError(C10)).toBeNull();
    expect(blockError(C2)).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t134 (Q-fe-48, Q-fe-49)

describe("t134: câu tổng kết vòng cuối còn khối (khớp từng ký tự) · một con 2 khối (none + confirm)", () => {
  const last: DigestItem = { child_id: C2, index: 2, title: "Cài Visio", kind: "rejection", needs: "none", text: "Yêu cầu chưa được duyệt." };
  const SUMMARY = "Đã xong 1/2 yêu cầu; có yêu cầu không được duyệt.";
  const line = "Ý 2 – Cài Visio: Yêu cầu chưa được duyệt.";

  it("digestSummary: khớp → câu tổng kết; thiếu câu / lệch một ký tự / thêm 2 dòng / không khối → undefined", () => {
    expect(digestSummary(`${line}\n${SUMMARY}`, [last])).toBe(SUMMARY);
    expect(digestSummary(line, [last])).toBeUndefined();
    expect(digestSummary(`Ý 2 - Cài Visio: Yêu cầu chưa được duyệt.\n${SUMMARY}`, [last])).toBeUndefined();
    expect(digestSummary(`${line}\n${SUMMARY}\nthêm`, [last])).toBeUndefined();
    expect(digestSummary(`${line}\n   `, [last])).toBeUndefined();
    expect(digestSummary(SUMMARY, [])).toBeUndefined();
  });

  it("màn: vòng cuối (cha đã đóng) có khối + câu tổng kết → câu hiện dưới khối (chữ thường); lệch → không hiện thêm", async () => {
    const closed = (text: string) =>
      view({
        status: "S_RESOLVED",
        final_state: "S_RESOLVED",
        waiting_for: null,
        conversation: [{ role: "assistant", kind: "digest", round: 2, text, items: [last] }],
        children_progress: PROGRESS.slice(0, 2).map((p) => ({ ...p, progress: "closed", outcome: p.index === 1 ? "resolved" : "rejected" })),
      });
    let current = closed(`${line}\n${SUMMARY}`);
    stubApi(() => current);
    const client = renderChat();
    expect((await screen.findByTestId("digest-summary")).textContent).toBe(SUMMARY);
    current = closed(`${line}\n<b>${SUMMARY}</b>\nthêm`);
    await client.invalidateQueries({ queryKey: ["ticket", PARENT] });
    await waitFor(() => expect(screen.queryByTestId("digest-summary")).toBeNull());
    expect(document.querySelector("b")).toBeNull();
  });

  it("một con có khối escalation (none) + khối result (confirm) → vẽ đủ 2 khối; lỗi CHỈ dưới khối cần trả lời; body 1 khoá cho con đó", async () => {
    const twice: DigestItem[] = [
      { child_id: C1, index: 1, title: "Mật khẩu email", kind: "escalation", needs: "none", text: "Đã chuyển kỹ thuật viên một phần." },
      { child_id: C1, index: 1, title: "Mật khẩu email", kind: "result", needs: "confirm", text: "Đã đặt lại mật khẩu." },
      ITEMS[1]!,
    ];
    const calls = stubApi(() => view({ conversation: [{ ...DIGEST, items: twice }], children_progress: PROGRESS.slice(0, 2) }));
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    renderChat();
    fireEvent.click(await sendButton());
    const blocks = [...document.querySelectorAll<HTMLElement>('[data-testid="digest-item"]')];
    expect(blocks.map((b) => b.dataset.child)).toStrictEqual([C1, C1, C2]);
    expect(blocks.map((b) => b.querySelector('[data-testid="digest-item-error"]')?.textContent ?? null)).toStrictEqual([
      null,
      REPLY_MISSING_CONFIRM,
      REPLY_MISSING_ANSWER,
    ]);
    fireEvent.click(within(blocks[1]!).getByRole("button", { name: "Đã ổn" }));
    typeAnswer(C2, 2, "PC-1107");
    fireEvent.click(await sendButton());
    await waitFor(() => expect(replies(calls)).toHaveLength(1));
    expect(JSON.parse(replies(calls)[0]!.body!)).toStrictEqual({ items: { [C1]: { confirmed: true }, [C2]: { answer: "PC-1107" } } });
    expect(errors.mock.calls.filter((a) => a.some((x) => String(x).includes("same key")))).toHaveLength(0); // khoá React không trùng
  });
});
