// D-99 (Tuấn Anh chốt 17/11/2026: phần 1–5, L3 = Trưởng bộ phận IT) — vòng xử lý sau khi chuyển IT ở giao diện:
// nhận ca, chuyển lên cấp 3, lời nhắn người gửi khi đóng ca, hàng đợi cấp 3 (`tier=3`), huy hiệu quá hạn; thông báo 2 loại mới;
// màn chat của nhân viên hiện bước xử lý của bộ phận IT.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseNotificationPage } from "../../api/notifications.ts";
import { queuePath, requestClose } from "../../api/escalations.ts";
import type { EscalationCloseIn, HandlingView, Me } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { STAFF_NAV } from "../../auth/permissions.ts";
import { finalNoteOf, handlingText, HANDLING_TEXT, pollDelay, POLL_HANDLING_MS } from "../employee/status.ts";
import { EscalationDetailRoute } from "./EscalationDetail.tsx";
import { EscalationQueue } from "./EscalationQueue.tsx";
import { CLAIM_CONFLICT_TEXT, RAISE_DONE_TEXT } from "./queue.ts";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const c of clients.splice(0)) c.clear();
  vi.unstubAllGlobals();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
type Call = { method: string; url: string; body: string | null };

const NOW = "2026-11-17T05:00:00Z";
function item(over: Record<string, unknown> = {}) {
  return {
    escalation_id: 7, ticket_id: "tk-7", exit_code: "E5", priority: 5, label: "Cao", reason_detail: "llm_high_risk", is_deny_case: true,
    handoff_note: { request: "Đặt lại mật khẩu cho sếp", done_so_far: "x", why_escalated: "Lý do chuyển: x. Mức ưu tiên: Cao.", next_for_l2: "y" },
    assigned_to: null, created_at: NOW, closed_at: null, close_result: null, closed_by: null, close_note: null,
    assigned_at: null, tier: 2, raised_at: null, raised_by: null, raise_target: null, raise_note: null, user_message: null,
    new_ticket_id: null, due_at: "2026-11-17T13:00:00Z", overdue: false,
    ...over,
  };
}

/** Fetch giả: hàng đợi trả `items` theo `tier` trong URL; POST trả theo bảng `posts` (mặc định 200). */
function serve(byTier: Record<"2" | "3", unknown[]>, posts: Record<string, () => Response> = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({ method, url, body: typeof init.body === "string" ? init.body : null });
      if (method === "GET" && url.startsWith("/api/escalations/queue")) {
        const tier = new URL(url, "http://x").searchParams.get("tier") === "3" ? "3" : "2";
        return json(200, { items: byTier[tier], next_cursor: null });
      }
      if (method === "POST") {
        const action = /\/(claim|raise|close)$/.exec(url)?.[1] ?? "";
        return (posts[action] ?? (() => json(200, {})))();
      }
      if (url.startsWith("/api/tickets/")) {
        return json(200, { ticket_id: "tk-7", status: "S_ESCALATED", waiting_for: null, conversation: [], exit_code: "E5", close_reason: null, final_state: "S_ESCALATED", created_at: NOW, closed_at: null });
      }
      return json(404, { detail: "not_found" });
    }),
  );
  return calls;
}

const me: Me = { user_id: "l2_01", role: "l2", permissions: ["escalation:handle", "ticket:read:any"] };
const auth = { state: { status: "signedIn", me } } as unknown as AuthValue;

function renderAt(path: string) {
  const client = new QueryClient();
  clients.push(client);
  render(
    <AuthContext.Provider value={auth}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/escalations" element={<EscalationQueue />} />
            <Route path="/escalations/:escalationId" element={<EscalationDetailRoute submit={(id: number, b: EscalationCloseIn) => requestClose(id, b)} />} />
            <Route path="/escalations-l3" element={<EscalationQueue tier={3} />} />
            <Route path="/escalations-l3/:escalationId" element={<EscalationDetailRoute tier={3} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </AuthContext.Provider>,
  );
}

const posted = (calls: Call[], action: string) => calls.filter((c) => c.method === "POST" && c.url.endsWith(`/${action}`));

describe("D-99 hàng đợi theo cấp", () => {
  it("cấp 3: gọi tier=3, tiêu đề riêng, huy hiệu nơi chuyển + quá hạn, link sang /escalations-l3", async () => {
    const calls = serve({ "2": [], "3": [item({ tier: 3, raise_target: "vendor", raised_by: "l2_01", raised_at: NOW, overdue: true })] });
    renderAt("/escalations-l3");
    await screen.findByText("Ca chuyển lên Trưởng IT");
    await waitFor(() => expect(document.querySelector('[data-testid="queue-row"]')).not.toBeNull());
    expect(calls.some((c) => c.url.includes("tier=3"))).toBe(true);
    expect(screen.getByTestId("raised-badge").textContent).toContain("nhà cung cấp");
    expect(screen.getByTestId("overdue-badge").textContent).toBe("Quá hạn");
    expect(document.querySelector('[data-testid="queue-row"]')!.getAttribute("href")).toBe("/escalations-l3/7");
    expect(screen.getByText(/Trưởng IT chưa nhận/)).toBeTruthy();
  });

  it("queuePath: cấp 2 giữ URL cũ (không tham số tier), cấp 3 thêm tier=3", () => {
    expect(queuePath("open", null)).toBe("/api/escalations/queue?status=open&limit=50");
    expect(queuePath("closed", "c1", 3)).toBe("/api/escalations/queue?status=closed&limit=50&tier=3&after=c1");
  });

  it("trang Trưởng IT nằm trong điều hướng theo quyền riêng escalation:handle:l3", () => {
    expect(STAFF_NAV.find((n) => n.to === "/escalations-l3")?.perm).toBe("escalation:handle:l3");
  });
});

describe("D-99 nhận ca / chuyển lên cấp cao hơn", () => {
  it("Nhận ca → POST /claim, hiện 'Bạn đang xử lý'", async () => {
    const calls = serve({ "2": [item()], "3": [] });
    renderAt("/escalations/7");
    fireEvent.click(await screen.findByTestId("claim-button"));
    await screen.findByTestId("claim-done");
    expect(posted(calls, "claim")).toHaveLength(1);
    expect(screen.getByTestId("holder-text").textContent).toBe("Bạn đang xử lý ca này");
  });

  it("409 already_claimed → câu báo người khác đã nhận", async () => {
    serve({ "2": [item()], "3": [] }, { claim: () => json(409, { detail: "already_claimed" }) });
    renderAt("/escalations/7");
    fireEvent.click(await screen.findByTestId("claim-button"));
    expect((await screen.findByTestId("handling-error")).textContent).toBe(CLAIM_CONFLICT_TEXT);
  });

  it("ca người khác giữ → không nút Nhận ca, không form chuyển cấp", async () => {
    serve({ "2": [item({ assigned_to: "ha.lt", assigned_at: NOW })], "3": [] });
    renderAt("/escalations/7");
    await screen.findByTestId("handling-actions");
    expect(screen.queryByTestId("claim-button")).toBeNull();
    expect(screen.queryByTestId("raise-open")).toBeNull();
    expect(screen.getByTestId("holder-text").textContent).toBe("ha.lt đang xử lý");
  });

  it("chuyển lên: bắt chọn nơi + ghi lý do; gửi đúng thân; xong → câu báo", async () => {
    const calls = serve({ "2": [item()], "3": [] });
    renderAt("/escalations/7");
    fireEvent.click(await screen.findByTestId("raise-open"));
    fireEvent.click(screen.getByRole("button", { name: "Chuyển" }));
    expect(screen.getByTestId("raise-problem").textContent).toBe("Chọn nơi chuyển.");
    fireEvent.click(screen.getByRole("radio", { name: /Trưởng bộ phận IT/ }));
    fireEvent.change(screen.getByTestId("raise-note"), { target: { value: "  Cần ngoại lệ chính sách  " } });
    fireEvent.click(screen.getByRole("button", { name: "Chuyển" }));
    expect((await screen.findByTestId("raise-done")).textContent).toBe(RAISE_DONE_TEXT);
    const [raise] = posted(calls, "raise");
    expect(JSON.parse(raise!.body!)).toEqual({ target: "it_manager", note: "Cần ngoại lệ chính sách" });
  });

  it("màn cấp 3: không có form chuyển cấp (đã ở cấp cao nhất)", async () => {
    serve({ "2": [], "3": [item({ tier: 3, raise_target: "it_manager", raised_by: "l2_01", raised_at: NOW, raise_note: "Cần quyết định" })] });
    renderAt("/escalations-l3/7");
    await screen.findByTestId("handling-actions");
    expect(screen.queryByTestId("raise-open")).toBeNull();
    expect(screen.getByTestId("raise-note-view").textContent).toContain("Cần quyết định");
  });
});

describe("D-99 lời nhắn người gửi khi đóng ca", () => {
  it("có lời nhắn → thân có user_message (đã cắt khoảng trắng); để trống → không có khoá", async () => {
    const calls = serve({ "2": [item({ is_deny_case: false, exit_code: "E1", priority: 6, label: "Thường" })], "3": [] });
    renderAt("/escalations/7");
    fireEvent.click(await screen.findByRole("radio", { name: /Đã hoàn tất/ }));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "Đã cấp lại" } });
    fireEvent.change(screen.getByTestId("close-user-message"), { target: { value: "  Bạn đăng nhập lại nhé.  " } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));
    await waitFor(() => expect(posted(calls, "close")).toHaveLength(1));
    expect(JSON.parse(posted(calls, "close")[0]!.body!)).toEqual({ close_result: "completed", note: "Đã cấp lại", user_message: "Bạn đăng nhập lại nhé." });
  });

  it("422 user_message → lỗi đúng chỗ, giữ form", async () => {
    serve({ "2": [item({ is_deny_case: false, exit_code: "E1" })], "3": [] }, { close: () => json(422, { error: "invalid_request", fields: ["user_message"] }) });
    renderAt("/escalations/7");
    fireEvent.click(await screen.findByRole("radio", { name: /Đã hoàn tất/ }));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "x" } });
    fireEvent.change(screen.getByTestId("close-user-message"), { target: { value: "y" } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));
    expect((await screen.findByTestId("close-message-error")).textContent).toContain("Lời nhắn chưa gửi được");
  });
});

describe("D-99 thông báo + màn chat nhân viên", () => {
  const base = { ticket_id: "t1", text: "x", new_ticket_id: null, created_at: NOW };
  it("parser nhận escalation_claimed / escalation_raised đúng cặp kind–result–id; sai cặp → 502", () => {
    const ok = parseNotificationPage({
      items: [
        { ...base, id: "escc:1", kind: "escalation_claimed", result: "in_progress" },
        { ...base, id: "escr:1", kind: "escalation_raised", result: "raised" },
        { ...base, id: "esc:1", kind: "escalation_closed", result: "reopened_as_new", new_ticket_id: "n1" },
      ],
      next_cursor: null,
    });
    expect(ok.items).toHaveLength(3);
    for (const bad of [
      { ...base, id: "esc:1", kind: "escalation_claimed", result: "in_progress" },
      { ...base, id: "escr:1", kind: "escalation_raised", result: "completed" },
      { ...base, id: "escx:1", kind: "escalation_other", result: "raised" },
    ]) {
      expect(() => parseNotificationPage({ items: [bad], next_cursor: null })).toThrow();
    }
  });

  const h = (over: Partial<HandlingView>): HandlingView => ({
    ticket_id: "t1", stage: "waiting", tier: 2, raise_target: null, close_result: null, user_message: null, new_ticket_id: null, updated_at: NOW, ...over,
  });
  it("câu theo từng bước; lời nhắn chỉ nối khi đã đóng", () => {
    expect(handlingText(h({}))).toBe(HANDLING_TEXT.waiting);
    expect(handlingText(h({ stage: "claimed", tier: 3 }))).toBe(HANDLING_TEXT.claimed3);
    expect(handlingText(h({ stage: "raised", tier: 3, raise_target: "vendor" }))).toBe(HANDLING_TEXT.raised_vendor);
    expect(handlingText(h({ stage: "closed", close_result: "completed", user_message: "Đã xong." }))).toBe(`${HANDLING_TEXT.completed} Lời nhắn từ bộ phận IT: Đã xong.`);
    expect(handlingText(h({ stage: "closed", close_result: "reopened_as_new", new_ticket_id: "n" }))).toBe(HANDLING_TEXT.reopened_new);
    expect(handlingText(h({ stage: "claimed", user_message: "không hiện" }))).toBe(HANDLING_TEXT.claimed2);
  });

  it("finalNoteOf dùng bước xử lý khi có; hỏi lại 30 s khi IT chưa xong, dừng khi đã đóng", () => {
    const view = { final_state: "S_ESCALATED", close_reason: null, waiting_for: null };
    expect(finalNoteOf({ ...view, handling: [h({ stage: "raised", tier: 3, raise_target: "it_manager" })] })).toBe(HANDLING_TEXT.raised_it_manager);
    expect(finalNoteOf({ ...view, handling: null })).toBe("Kỹ thuật viên sẽ liên hệ bạn để hỗ trợ tiếp.");
    expect(pollDelay({ ...view, handling: [h({ stage: "claimed" })] })).toBe(POLL_HANDLING_MS);
    expect(pollDelay({ ...view, handling: [h({ stage: "closed", close_result: "completed" })] })).toBe(false);
    expect(pollDelay({ ...view, handling: null })).toBe(false);
  });
});
