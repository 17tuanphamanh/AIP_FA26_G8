// F6 — yêu cầu nhiều ý (D-31) phía nhân viên: dải tiến độ (t66, t67), tin tổng hợp + một nút gửi (t68–t73), ticket thường
// không đổi (t74). Hợp đồng là [Đề xuất F6 — T20] (PLAN-fe mục 8). Không gọi backend: fetch giả trả đúng hình đề xuất;
// t73 chạy CHÍNH handler MSW (mocks/handlers/employee-multi.ts) qua `getResponse` làm "máy chủ" để đi trọn chuỗi
// round 1 → round 2 → đóng.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { getResponse } from "msw";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { NOTE_MAX, TEXT_MAX } from "../../api/tickets.ts";
import type { DigestItem, Me, TicketView } from "../../api/types.ts";
import { normalizeConversation } from "../../components/messages.ts";
import { ProgressStrip } from "../../components/ProgressStrip.tsx";
import { multiHandlers, resetMultiTickets } from "../../mocks/handlers/employee-multi.ts";
import { ChatRoute } from "./ChatPage.tsx";
import {
  checkDigest,
  digestFieldErrors,
  digestReplyBody,
  EMPTY_DRAFT,
  itemLabel,
  latestRound,
  normalizeProgress,
  PARENT_DONE,
  PARENT_FINAL_NOTE,
  PARENT_PROCESSING,
  PARENT_REPLY,
  parentStatusLabel,
  progressLabel,
  progressTone,
  REPLY_ANSWER_TOO_LONG,
  REPLY_INVALID,
  REPLY_MISSING_ANSWER,
  REPLY_MISSING_CHOICE,
  REPLY_MISSING_CONFIRM,
  REPLY_NOTE_TOO_LONG,
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
  {
    child_id: C2,
    index: 2,
    title: "Cài Visio",
    kind: "question",
    needs: "answer",
    text: "Bạn muốn cài lên máy nào?",
    options: ["LAP-0342", "PC-1107"],
  },
  { child_id: C3, index: 3, title: "Quyền thư mục Kế toán", kind: "rejection", needs: "none", text: "Lý do: cần Trưởng phòng xác nhận." },
];
const DIGEST = { role: "assistant", kind: "digest", round: 1, text: "Ý 1 … Ý 2 … Ý 3 …", items: ITEMS };
const PROGRESS = [
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
  children_progress: PROGRESS as TicketView["children_progress"],
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

// ------------------------------------------------------------------------------------------------ t66

describe("t66: nhãn tiến độ từng ý (P1 §8.3) — đủ giá trị, giá trị lạ, ý bị chặn trung tính", () => {
  it.each([
    ["processing", null, "Đang xử lý", "processing"],
    ["pending_approval", null, "Chờ IT duyệt", "waiting"],
    ["ready", null, "Đã có kết quả — chờ tổng hợp", "processing"],
    ["needs_user", null, "Cần bạn phản hồi", "waiting"],
    ["closed", "resolved", "Đã xong", "done"],
    ["closed", "escalated", "Đã chuyển kỹ thuật viên", "closed"],
    ["closed", "rejected", "Không được duyệt", "closed"],
    ["closed", "blocked", "Không thể xử lý tự động", "closed"],
  ])("%s / %s → \"%s\" (chấm %s)", (progress, outcome, label, tone) => {
    expect(progressLabel({ progress, outcome })).toBe(label);
    expect(progressTone({ progress, outcome })).toBe(tone);
  });

  it.each([
    ["progress lạ", "S_EXECUTING", null],
    ["progress rỗng", "", null],
    ["closed thiếu outcome", "closed", null],
    ["closed outcome lạ", "closed", "timeout"],
    ["outcome lạ + progress lạ", "archived", "weird"],
  ])("%s → \"Đang xử lý\" (không vỡ, không lộ giá trị)", (_name, progress, outcome) => {
    expect(progressLabel({ progress, outcome })).toBe("Đang xử lý");
    expect(progressTone({ progress, outcome })).toBe("processing");
  });

  it("pending_approval KHÔNG BAO GIỜ là 'Đã xong'; dải hiện đủ nhãn, không câu gợi ý tấn công, không mã S_*", () => {
    expect(progressLabel({ progress: "pending_approval", outcome: null })).not.toBe("Đã xong");
    const items = [
      ...PROGRESS,
      { child_id: "x-4", index: 4, title: "VPN", progress: "pending_approval", outcome: null },
      { child_id: "x-5", index: 5, title: "Máy in", progress: "closed", outcome: "blocked" },
      { child_id: "x-6", index: 6, title: "Email", progress: "S_EXECUTING", outcome: null },
    ];
    render(<ProgressStrip items={normalizeProgress(items)!} />);
    const strip = screen.getByRole("group", { name: "Tiến độ từng việc" });
    const texts = [...strip.querySelectorAll('[data-testid="progress-item"]')].map((el) => el.textContent);
    expect(texts).toStrictEqual([
      "Mật khẩu email· Cần bạn phản hồi",
      "Cài Visio· Cần bạn phản hồi",
      "Quyền thư mục Kế toán· Không được duyệt",
      "VPN· Chờ IT duyệt",
      "Máy in· Không thể xử lý tự động",
      "Email· Đang xử lý",
    ]);
    expect(strip.textContent).not.toMatch(LEAK);
    expect(strip.closest('[role="log"]')).toBeNull(); // không phải tin nhắn (P1 §8.3)
  });

  it("nhãn ticket cha (12b Q-fe-34): chờ con → 'Đang xử lý các ý'; chờ trả lời → 'Cần bạn phản hồi'; đóng có ý không xong → không nói 'Đã hoàn tất'", () => {
    const progress = normalizeProgress(PROGRESS)!;
    expect(parentStatusLabel({ final_state: null, waiting_for: null }, progress)).toBe(PARENT_PROCESSING);
    expect(parentStatusLabel({ final_state: null, waiting_for: "reply" }, progress)).toBe(PARENT_REPLY);
    const mixed = normalizeProgress([
      { ...PROGRESS[0], progress: "closed", outcome: "resolved" },
      { ...PROGRESS[1], progress: "closed", outcome: "resolved" },
      PROGRESS[2],
    ])!;
    expect(parentStatusLabel({ final_state: "S_RESOLVED", waiting_for: null }, mixed)).toBe(PARENT_DONE);
    const allDone = normalizeProgress(PROGRESS.map((p) => ({ ...p, progress: "closed", outcome: "resolved" })))!;
    expect(parentStatusLabel({ final_state: "S_RESOLVED", waiting_for: null }, allDone)).toBe("Đã hoàn tất");
    expect(parentStatusLabel({ final_state: "S_ESCALATED", waiting_for: null }, mixed)).toBe("Đã chuyển kỹ thuật viên hỗ trợ");
  });
});

// ------------------------------------------------------------------------------------------------ t67

describe("t67: kiểm dạng children_progress + tin digest (dữ liệu hỏng không làm vỡ màn)", () => {
  it("normalizeProgress: không phải mảng / rỗng → null; phần tử hỏng hoặc trùng bị bỏ; sắp theo index", () => {
    expect(normalizeProgress(undefined)).toBeNull();
    expect(normalizeProgress(null)).toBeNull();
    expect(normalizeProgress({})).toBeNull();
    expect(normalizeProgress([])).toBeNull();
    expect(normalizeProgress([null, "x", { child_id: "", index: 1, title: "A" }])).toBeNull();
    const got = normalizeProgress([
      { child_id: "b", index: 2, title: "B", progress: "ready", outcome: null },
      { child_id: "a", index: 1, title: "A", progress: 7, outcome: 3 },
      { child_id: "a", index: 3, title: "A trùng", progress: "ready", outcome: null },
      { child_id: "c", index: 0, title: "C", progress: "ready", outcome: null },
      { child_id: "d", index: 1.5, title: "D", progress: "ready", outcome: null },
      { child_id: "e", index: 4, progress: "ready", outcome: null },
    ]);
    expect(got).toStrictEqual([
      { child_id: "a", index: 1, title: "A", progress: "", outcome: null },
      { child_id: "b", index: 2, title: "B", progress: "ready", outcome: null },
    ]);
  });

  it("digest đúng dạng → khối theo index; kind/needs lạ → kết quả / không hỏi; options chỉ với answer; nguồn kiểm dạng", () => {
    const [m] = normalizeConversation([
      {
        role: "assistant",
        kind: "digest",
        round: 2,
        text: "chữ thuần",
        items: [
          { child_id: "k-2", index: 2, title: "Hai", kind: "weird", needs: "maybe", text: "b", options: ["x"] },
          { child_id: "k-1", index: 1, title: "Một", kind: "question", needs: "answer", text: "a", options: ["LAP-0342", 5, "", "LAP-0342"] },
          { child_id: "k-3", index: 3, kind: "result", needs: "none", text: "thiếu title" },
          { child_id: "k-1", index: 4, title: "Trùng", kind: "result", needs: "none", text: "c" },
          {
            child_id: "k-5",
            index: 5,
            title: "Năm",
            kind: "result",
            needs: "confirm",
            text: "Xong.\n\nNguồn:\n- VPN › Cổng",
            sources: [{ chunk_id: "KB-VPN-001#v1#1", title: "VPN", heading_path: "Cổng" }, { bad: 1 }],
          },
        ],
      },
    ]);
    expect(m?.digest).toStrictEqual({
      round: 2,
      items: [
        { child_id: "k-1", index: 1, title: "Một", kind: "question", needs: "answer", text: "a", options: ["LAP-0342"] },
        { child_id: "k-2", index: 2, title: "Hai", kind: "result", needs: "none", text: "b" },
        {
          child_id: "k-5",
          index: 5,
          title: "Năm",
          kind: "result",
          needs: "confirm",
          text: "Xong.",
          sources: [{ chunk_id: "KB-VPN-001#v1#1", title: "VPN", heading_path: "Cổng" }],
        },
      ],
    });
  });

  it.each([
    ["round 0", { round: 0, items: ITEMS }],
    ["round chuỗi", { round: "1", items: ITEMS }],
    ["items không phải mảng", { round: 1, items: {} }],
    ["không khối nào hợp lệ", { round: 1, items: [{ index: 1 }] }],
  ])("%s → không có digest, hiện `text` như tin thường (Q-fe-2)", (_name, rest) => {
    const [m] = normalizeConversation([{ role: "assistant", kind: "digest", text: "Bản chữ thuần của tin tổng hợp", ...rest }]);
    expect(m?.digest).toBeUndefined();
    expect(m?.text).toBe("Bản chữ thuần của tin tổng hợp");
    expect(normalizeConversation([{ role: "assistant", kind: "digest", round: 0, items: [] }])).toStrictEqual([]);
  });

  it("latestRound = round lớn nhất trong các tin digest hợp lệ; không có → null", () => {
    const messages = normalizeConversation([
      { ...DIGEST, round: 1 },
      { role: "user", text: "Ý 1: Đã ổn" },
      { ...DIGEST, round: 3 },
      { ...DIGEST, round: 2 },
      { role: "assistant", kind: "digest", round: 9, text: "hỏng", items: [] },
    ]);
    expect(latestRound(messages)).toBe(3);
    expect(latestRound(normalizeConversation([{ role: "assistant", kind: "answer", text: "x" }]))).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t68

describe("t68: thiếu trả lời → lỗi NGAY dưới đúng khối, 0 POST", () => {
  it("bấm 'Gửi phản hồi' khi chưa chọn gì → ý 1 'Chọn Đã ổn hoặc Chưa ổn', ý 2 'Cần chọn một máy…', ý 3 không lỗi; 0 POST", async () => {
    const calls = stubApi(() => view());
    renderChat();
    fireEvent.click(await sendButton());
    expect(blockError(C1)).toBe(REPLY_MISSING_CONFIRM);
    expect(blockError(C2)).toBe(REPLY_MISSING_CHOICE);
    expect(REPLY_MISSING_CHOICE).toBe("Cần chọn một máy trước khi gửi.");
    expect(blockError(C3)).toBeNull();
    // Lỗi gắn đúng ô (aria-describedby trỏ tới câu lỗi của CHÍNH khối đó).
    const answer = within(block(C2)).getByLabelText("Trả lời ý 2");
    expect(answer.getAttribute("aria-invalid")).toBe("true");
    expect(document.getElementById(answer.getAttribute("aria-describedby")!)?.textContent).toBe(REPLY_MISSING_CHOICE);

    // Chọn ý 1 → lỗi ý 1 biến mất ngay; ý 2 vẫn thiếu → bấm lại vẫn 0 POST.
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    expect(blockError(C1)).toBeNull();
    fireEvent.click(await sendButton());
    expect(blockError(C2)).toBe(REPLY_MISSING_CHOICE);
    // Câu trả lời chỉ khoảng trắng = chưa trả lời.
    fireEvent.change(within(block(C2)).getByLabelText("Trả lời ý 2"), { target: { value: "  \n " } });
    fireEvent.click(await sendButton());
    expect(blockError(C2)).toBe(REPLY_MISSING_CHOICE);
    await settle();
    expect(replies(calls)).toHaveLength(0);
  });

  it("checkDigest: không có options → 'Cần trả lời trước khi gửi.'; quá dài → câu giới hạn; ý needs=none không bao giờ lỗi", () => {
    const plain: DigestItem = { ...ITEMS[1]!, options: undefined };
    delete plain.options;
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
  it("Đã ổn + bấm gợi ý LAP-0342 → đúng 1 POST, body {items:{ý1:{confirmed:true}, ý2:{answer:'LAP-0342'}}} — không có ý bị từ chối", async () => {
    const calls = stubApi(() => view());
    renderChat();
    await sendButton();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    fireEvent.click(within(block(C2)).getByRole("button", { name: "LAP-0342" }));
    expect((within(block(C2)).getByLabelText("Trả lời ý 2") as HTMLTextAreaElement).value).toBe("LAP-0342");
    expect(within(block(C2)).getByRole("button", { name: "LAP-0342" }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(await sendButton());
    await waitFor(() => expect(replies(calls)).toHaveLength(1));
    expect(JSON.parse(replies(calls)[0]!.body!)).toStrictEqual({ items: { [C1]: { confirmed: true }, [C2]: { answer: "LAP-0342" } } });
  });

  it("digestReplyBody: Chưa ổn + ghi chú (trim) · Chưa ổn ghi chú rỗng → không khoá note · đổi sang Đã ổn → bỏ ghi chú · sửa tay sau gợi ý", () => {
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

  it("màn: Chưa ổn → hiện ô ghi chú (không bắt buộc), gửi kèm note; sửa tay câu trả lời sau khi bấm gợi ý → gửi chữ đã sửa", async () => {
    const calls = stubApi(() => view());
    renderChat();
    await sendButton();
    expect(within(block(C1)).queryByLabelText(/Ghi chú cho ý 1/)).toBeNull();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Chưa ổn" }));
    fireEvent.change(within(block(C1)).getByLabelText(/Ghi chú cho ý 1/), { target: { value: " vẫn không vào được " } });
    fireEvent.click(within(block(C2)).getByRole("button", { name: "PC-1107" }));
    fireEvent.change(within(block(C2)).getByLabelText("Trả lời ý 2"), { target: { value: "PC-1107 và LAP-0342" } });
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
    fireEvent.click(within(block(C2)).getByRole("button", { name: "LAP-0342" }));
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

describe("t71: 409 (trả muộn) → câu chung + tải lại ticket", () => {
  it("409 → câu của server dưới nút, GET ticket thêm lần nữa, không khối nào đỏ", async () => {
    const calls = stubApi(() => view(), () => json(409, { detail: "Yêu cầu đã chuyển sang bước khác" }));
    renderChat();
    await sendButton();
    fireEvent.click(within(block(C1)).getByRole("button", { name: "Đã ổn" }));
    fireEvent.click(within(block(C2)).getByRole("button", { name: "PC-1107" }));
    const before = gets(calls).length;
    fireEvent.click(await sendButton());
    expect((await screen.findByTestId("digest-error")).textContent).toBe("Yêu cầu đã chuyển sang bước khác");
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
    fireEvent.click(within(block(C2)).getByRole("button", { name: "LAP-0342" }));
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
      "Mật khẩu email· Đã có kết quả — chờ tổng hợp",
      "Cài Visio· Chờ IT duyệt",
      "Quyền thư mục Kế toán· Đang xử lý",
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
    fireEvent.click(within(block(c(2))).getByRole("button", { name: "LAP-0342" }));
    fireEvent.click(await sendButton());
    await waitFor(() => expect(replies(calls)).toHaveLength(1));
    expect(Object.keys(JSON.parse(replies(calls)[0]!.body!).items)).toStrictEqual([c(1), c(2)]);

    // Sau 202: tin người dùng (Q-fe-33), ý 2 chạy tiếp; round 1 thành chỉ đọc.
    await screen.findByText("Ý 1: Đã ổn · Ý 2: LAP-0342");
    expect(stripTexts()).toStrictEqual(["Mật khẩu email· Đã xong", "Cài Visio· Đang xử lý", "Quyền thư mục Kế toán· Không được duyệt"]);

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
    expect(screen.getAllByRole("button", { name: "Gửi phản hồi" })).toHaveLength(1);
    fireEvent.click(within(round2!).getByRole("button", { name: "Đã ổn" }));
    fireEvent.click(within(round2!).getByRole("button", { name: "Gửi phản hồi" }));
    await waitFor(() => expect(replies(calls)).toHaveLength(2));
    expect(JSON.parse(replies(calls)[1]!.body!)).toStrictEqual({ items: { [c(2)]: { confirmed: true } } });

    // Cha đóng: dải đủ outcome, câu cuối KHÔNG nói "đã hoàn tất" (có ý không được duyệt), không còn form nào.
    expect((await screen.findByTestId("final-note")).textContent).toContain(PARENT_FINAL_NOTE);
    expect(screen.getByTestId("final-note").textContent).not.toContain(FINAL_NOTE.S_RESOLVED!);
    expect(stripTexts()).toStrictEqual(["Mật khẩu email· Đã xong", "Cài Visio· Đã xong", "Quyền thư mục Kế toán· Không được duyệt"]);
    expect(pill()).toContain(PARENT_DONE);
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
    { child_id: "constructor", index: 1, title: "Cài Visio", kind: "question", needs: "answer", text: "Máy nào?", options: ["LAP-0342"] },
    { child_id: "__proto__", index: 2, title: "Mật khẩu email", kind: "result", needs: "confirm", text: "Đã gửi đường dẫn." },
    { child_id: "toString", index: 3, title: "Máy in", kind: "question", needs: "answer", text: "Tầng mấy?" },
  ];
  const ids = ODD.map((i) => i.child_id);
  /** Object có khoá RIÊNG "__proto__" (viết literal `{"__proto__": …}` trong mã JS là đổi prototype). */
  const own = <T,>(raw: string) => JSON.parse(raw) as Record<string, T>;
  const oddView = (items: DigestItem[]) =>
    view({
      conversation: [{ ...DIGEST, items }],
      children_progress: items.map((i) => ({ child_id: i.child_id, index: i.index, title: i.title, progress: "needs_user", outcome: null })) as TicketView["children_progress"],
    });
  const childErrors = () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    return () => spy.mock.calls.filter((args) => args.some((a) => String(a).includes("React child")));
  };

  it("itemLabel: kind prototype → nhãn 'Đã xử lý' như kind lạ; kind hợp lệ giữ nhãn", () => {
    for (const kind of ["__proto__", "constructor", "toString"]) {
      expect(itemLabel({ kind: kind as DigestItem["kind"] }, null)).toBe("Đã xử lý");
    }
    expect(itemLabel({ kind: "question" }, null)).toBe("Cần bạn trả lời");
  });

  it("checkDigest: chưa trả lời → lỗi ở ĐỦ 3 khoá riêng (lỗi '__proto__' không bị nuốt); nháp đủ → không lỗi", () => {
    const errors = checkDigest(ODD, {});
    expect(Object.keys(errors)).toStrictEqual(ids);
    expect(errors).toStrictEqual(
      own(`{"constructor": "${REPLY_MISSING_CHOICE}", "__proto__": "${REPLY_MISSING_CONFIRM}", "toString": "${REPLY_MISSING_ANSWER}"}`),
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
    const calls = stubApi(() => oddView(ODD));
    renderChat();
    fireEvent.click(await sendButton());
    expect(ids.map(blockError)).toStrictEqual([REPLY_MISSING_CHOICE, REPLY_MISSING_CONFIRM, REPLY_MISSING_ANSWER]);
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
    expect(replies(calls)).toHaveLength(0);

    fireEvent.click(await sendButton());
    await waitFor(() => expect(replies(calls)).toHaveLength(1));
    expect(replies(calls)[0]!.body).toBe(
      '{"items":{"constructor":{"answer":"LAP-0342 tầng 2"},"__proto__":{"confirmed":true},"toString":{"answer":"Tầng 3"}}}',
    );
    expect(errors()).toHaveLength(0);
    expect(document.body.textContent).not.toMatch(/function |\[object /);
  });

  it("màn: khối 'constructor' xác nhận — 'Chưa ổn' không ghi chú → body {confirmed:false} (nháp đủ trường, không lấy từ prototype)", async () => {
    const calls = stubApi(() => oddView([{ ...ODD[1]!, child_id: "constructor", index: 1 }]));
    renderChat();
    await sendButton();
    fireEvent.click(within(block("constructor")).getByRole("button", { name: "Chưa ổn" }));
    expect((within(block("constructor")).getByLabelText(/Ghi chú cho ý 1/) as HTMLTextAreaElement).value).toBe("");
    fireEvent.click(await sendButton());
    await waitFor(() => expect(replies(calls)).toHaveLength(1));
    expect(replies(calls)[0]!.body).toBe('{"items":{"constructor":{"confirmed":false}}}');
  });

  it("khối hợp lệ (child_id thường) vẫn như cũ", () => {
    expect(checkDigest([ITEMS[0]!], {})).toStrictEqual({ [C1]: REPLY_MISSING_CONFIRM });
  });
});
