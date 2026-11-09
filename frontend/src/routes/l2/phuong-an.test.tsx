// N-PA P5 — hàng đợi L2 theo hợp đồng chốt ĐP 26/10 17:30 §4: lọc Mở / Đã đóng, `{items, next_cursor}` + "Tải thêm", đóng
// ca (200 / 409 / 422), ca đã đóng chỉ đọc. Fetch giả dùng CHÍNH kho + hàm trang của handler MSW (cùng hình dạng).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { FlashNotice } from "../../components/FlashNotice.tsx";
import type { Me } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { STAFF_NAV } from "../../auth/permissions.ts";
import { RequirePerm } from "../../auth/RequireAuth.tsx";
import { afterEach, describe, expect, it, vi } from "vitest";
import { queueQuery, requestClose } from "../../api/escalations.ts";
import type { EscalationCloseIn } from "../../api/types.ts";
import { createEscalationStore, type EscalationStore } from "../../mocks/fixtures/escalations.ts";
import { closeOutcome } from "../../mocks/handlers/escalation-close.ts";
import { queuePage } from "../../mocks/handlers/escalation-queue.ts";
import { EscalationDetailRoute } from "./EscalationDetail.tsx";
import { EscalationQueue } from "./EscalationQueue.tsx";
import { ALREADY_CLOSED_TEXT, CLOSED_TEXT, REOPENED_TEXT } from "./queue.ts";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const c of clients.splice(0)) c.clear();
  vi.unstubAllGlobals();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
type Call = { method: string; url: string; body: string | null };

/** Fetch giả = server minh hoạ: hàng đợi theo `queuePage`, đóng ca theo `closeOutcome`; `closeOverride` thay trả lời /close. */
function serve(store: EscalationStore, { closeOverride, delayAfter }: { closeOverride?: () => Response; delayAfter?: Promise<void> } = {}) {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({ method, url, body: typeof init.body === "string" ? init.body : null });
      if (method === "GET" && url.startsWith("/api/escalations/queue")) {
        if (delayAfter && url.includes("after=")) await delayAfter;
        const page = queuePage(store, new URL(url, "http://x"));
        return "fields" in page ? json(422, { error: "invalid_request", fields: page.fields }) : json(200, page.body);
      }
      const close = /^\/api\/escalations\/(\d+)\/close$/.exec(url);
      if (method === "POST" && close) {
        if (closeOverride) return closeOverride();
        const out = closeOutcome(store, Number(close[1]), JSON.parse(String(init.body)), "long.nh");
        return json(out.status, out.body);
      }
      if (url.startsWith("/api/tickets/")) {
        return json(200, { ticket_id: "x", status: "S_ESCALATED", waiting_for: null, conversation: [], exit_code: "E3", close_reason: null, final_state: null, created_at: "2026-10-26T01:00:00Z", closed_at: null });
      }
      return json(404, { detail: "not_found" });
    }),
  );
  return calls;
}

/** Đóng ca qua client THẬT (như route thật đã bật) — vitest không bật MSW nên `closeEscalation` mặc định luôn chặn. */
const viaClient = (id: number, body: EscalationCloseIn) => requestClose(id, body);

/** Đường dẫn hiện tại (kiểm điều hướng sau 409). */
function Where() {
  const { pathname, search } = useLocation();
  return <span data-testid="where" hidden>{pathname + search}</span>;
}

function renderAt(path: string) {
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <FlashNotice />
        <Where />
        <Routes>
          <Route path="/escalations" element={<EscalationQueue />} />
          <Route path="/escalations/:escalationId" element={<EscalationDetailRoute />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return client;
}

const queueCalls = (calls: Call[]) => calls.filter((c) => c.method === "GET" && c.url.startsWith("/api/escalations/queue")).map((c) => c.url);
const rowIds = () => [...document.querySelectorAll<HTMLElement>('[data-testid="queue-row"]')].map((r) => Number(r.dataset.escalationId));
const count = () => screen.getByTestId("queue-count").textContent;
/** Mở mọi nhóm + đi hết các trang trong nhóm → danh sách id theo thứ tự hiển thị (đủ ca đã tải). */
function allLoadedIds(): number[] {
  const out: number[] = [];
  for (const g of document.querySelectorAll<HTMLElement>('[data-testid="queue-group"]')) {
    for (;;) {
      out.push(...[...g.querySelectorAll<HTMLElement>('[data-testid="queue-row"]')].map((r) => Number(r.dataset.escalationId)));
      const next = [...g.querySelectorAll<HTMLButtonElement>('[data-testid="queue-pager"] button')].find((b) => b.textContent === "Sau");
      if (!next || next.disabled) break;
      fireEvent.click(next);
    }
  }
  return out;
}

// ------------------------------------------------------------------------------------------------ t174

describe("t174: lọc 'Mở' (mặc định) / 'Đã đóng' → status=open|closed; ca đã đóng hiện kết quả + lúc đóng, link ?status=closed", () => {
  it("mặc định Mở; đổi sang Đã đóng gọi status=closed, giữ thứ tự server", async () => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const calls = serve(store);
    renderAt("/escalations");
    await screen.findByTestId("queue-count");
    expect(screen.getByRole("tab", { name: "Mở" }).getAttribute("aria-selected")).toBe("true");
    expect(queueCalls(calls)).toStrictEqual(["/api/escalations/queue?status=open&limit=50"]);
    expect(count()).toBe("Đã tải 8 ca");

    fireEvent.click(screen.getByRole("tab", { name: "Đã đóng" }));
    await waitFor(() => expect(queueCalls(calls)).toContain("/api/escalations/queue?status=closed&limit=50"));
    await waitFor(() => expect(rowIds()).toStrictEqual(store.list("closed").map((i) => i.escalation_id)));
    const first = document.querySelector<HTMLElement>('[data-testid="queue-row"]')!;
    expect(first.getAttribute("href")).toBe(`/escalations/${store.list("closed")[0]!.escalation_id}?status=closed`);
    expect(first.textContent).toMatch(/Đã đóng · Đã hoàn tất · \d{2}:\d{2}:\d{2} \d{2}\/\d{2}\/\d{4}/);
    expect(screen.queryByTestId("queue-more")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t175

describe("t175: 'Tải thêm' theo next_cursor — after nối đúng, thêm cuối, thứ tự server; aria-disabled (không disabled), giữ tiêu điểm", () => {
  it("62 ca / 50 mỗi trang: bấm → after=cur-50; đủ 62 ca đúng thứ tự; hết cursor → mất nút", async () => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 62);
    let release: () => void = () => {};
    const gate = new Promise<void>((r) => (release = r));
    const calls = serve(store, { delayAfter: gate });
    renderAt("/escalations");
    await screen.findByTestId("queue-count");
    expect(count()).toBe("Đã tải 50 ca · còn ca chưa tải");
    const more = screen.getByTestId("queue-more");
    more.focus();
    fireEvent.click(more);
    fireEvent.click(more); // bấm 2 lần trong lúc đang tải → vẫn 1 lời gọi
    await waitFor(() => expect(more.getAttribute("aria-disabled")).toBe("true"));
    expect(more.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(more);
    expect(more.textContent).toBe("Đang tải…");
    release();
    await waitFor(() => expect(count()).toBe("Đã tải 62 ca"));
    expect(queueCalls(calls)).toStrictEqual(["/api/escalations/queue?status=open&limit=50", "/api/escalations/queue?status=open&limit=50&after=cur-50"]);
    expect(allLoadedIds()).toStrictEqual(store.list("open").map((i) => i.escalation_id));
    expect(screen.queryByTestId("queue-more")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t176

describe("t176: ca tới bằng 'Tải thêm' KHÔNG bị báo là ca mới ở nhóm đang khuất", () => {
  it("chọn thẻ 'An ninh' → Tải thêm (trang 2 toàn nhóm khác) → không dòng 'Có N ca mới…'", async () => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 62);
    serve(store);
    renderAt("/escalations");
    await screen.findByTestId("queue-count");
    fireEvent.click(within(screen.getByTestId("queue-tabs")).getByRole("tab", { name: /^An ninh/ }));
    fireEvent.click(screen.getByTestId("queue-more"));
    await waitFor(() => expect(count()).toBe("Đã tải 62 ca"));
    expect(screen.queryByTestId("queue-missed")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t177

describe("t177: tự tải lại (15 s) với 2 trang đã tải → tải lại CẢ 2 trang, cursor nối đúng, vẫn đủ ca", () => {
  it("refetch: trang đầu + after=cur-50 lần nữa", async () => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 62);
    const calls = serve(store);
    const client = renderAt("/escalations");
    await screen.findByTestId("queue-count");
    fireEvent.click(screen.getByTestId("queue-more"));
    await waitFor(() => expect(count()).toBe("Đã tải 62 ca"));
    const before = queueCalls(calls).length;
    await act(async () => {
      await client.refetchQueries({ queryKey: queueQuery("open").queryKey });
    });
    expect(queueCalls(calls).slice(before)).toStrictEqual(["/api/escalations/queue?status=open&limit=50", "/api/escalations/queue?status=open&limit=50&after=cur-50"]);
    expect(count()).toBe("Đã tải 62 ca");
  });
});

// ------------------------------------------------------------------------------------------------ t178

describe("t178: Đóng ca 200 → POST đúng thân; ca rời danh sách Mở; câu báo; không còn chữ 'Minh hoạ'", () => {
  it("xác nhận từ chối + ghi chú → 200 → 'Đã đóng ca…'; hàng đợi tải lại không còn ca đó", async () => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const target = store.list("open").find((i) => i.exit_code === "E3")!;
    const calls = serve(store);
    const client = renderAt(`/escalations/${target.escalation_id}`);
    await screen.findByText("Ghi chú bàn giao");
    expect(document.body.textContent).not.toMatch(/Minh hoạ — chưa ghi|Phase 7/);
    fireEvent.click(screen.getByRole("radio", { name: /Xác nhận từ chối/ }));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "  Đã gọi người gửi.  " } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));
    expect((await screen.findByTestId("close-done")).textContent).toBe(CLOSED_TEXT);
    const post = calls.find((c) => c.method === "POST")!;
    expect([post.url, JSON.parse(post.body!)]).toStrictEqual([
      `/api/escalations/${target.escalation_id}/close`,
      { close_result: "confirmed_denial", note: "Đã gọi người gửi." },
    ]);
    await waitFor(() => {
      const data = client.getQueryData(queueQuery("open").queryKey);
      expect(data?.pages.flatMap((p) => p.items).some((i) => i.escalation_id === target.escalation_id)).toBe(false);
    });
    expect(screen.queryByRole("button", { name: "Đóng ca" })).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t179

describe("t179: 409 already_closed → 'Ca này đã được đóng trước đó.' + chuyển ?status=closed (chỉ đọc); 422 → lỗi đúng chỗ; completed khoá E5/E6", () => {
  it("409: ca đã bị người khác đóng → câu báo + sang ?status=closed, xem ca chỉ đọc (kết quả, người đóng, lúc đóng); không còn 'Không tìm thấy ca'", async () => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const target = store.list("open").find((i) => i.exit_code === "E3")!;
    const calls = serve(store);
    renderAt(`/escalations/${target.escalation_id}`);
    await screen.findByText("Ghi chú bàn giao");
    store.close(target.escalation_id, "completed", "người khác", "khac", Date.now());
    const before = queueCalls(calls).length;
    fireEvent.click(screen.getByRole("radio", { name: /Đã hoàn tất/ }));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "xong" } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));
    expect(ALREADY_CLOSED_TEXT).toBe("Ca này đã được đóng trước đó.");
    expect((await screen.findByTestId("flash")).textContent).toBe(ALREADY_CLOSED_TEXT);
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe(`/escalations/${target.escalation_id}?status=closed`));
    await waitFor(() => expect(queueCalls(calls).length).toBeGreaterThan(before));
    await waitFor(() => expect(queueCalls(calls)).toContain("/api/escalations/queue?status=closed&limit=50"));
    // chế độ chỉ đọc: kết quả + người đóng, không form, không câu "không tìm thấy"
    await screen.findByText("Đã hoàn tất");
    expect(document.body.textContent).toContain("người khác");
    expect(screen.queryByRole("button", { name: "Đóng ca" })).toBeNull();
    expect(document.body.textContent).not.toMatch(/Không tìm thấy ca|Ca đã đóng hoặc không còn/);
  });

  it.each([
    ["fields note → dưới ô ghi chú", { error: "invalid_request", fields: ["note"] }, "close-note-error"],
    ["fields close_result → dưới nhóm kết quả", { error: "invalid_request", fields: ["close_result"] }, "close-choice-error"],
    ["deny_case_cannot_complete → dưới nhóm kết quả", { detail: "deny_case_cannot_complete" }, "close-choice-error"],
  ])("422 %s; giữ lựa chọn + ghi chú; câu không chứa ghi chú", async (_n, body, testId) => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const target = store.list("open").find((i) => i.exit_code === "E3")!;
    serve(store, { closeOverride: () => json(422, body) });
    renderAt(`/escalations/${target.escalation_id}`);
    await screen.findByText("Ghi chú bàn giao");
    fireEvent.click(screen.getByRole("radio", { name: /Mở yêu cầu mới/ }));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "GHI-CHU-RIENG" } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));
    const err = await screen.findByTestId(testId);
    expect(err.textContent).not.toContain("GHI-CHU-RIENG");
    expect(screen.getByRole("radio", { name: /Mở yêu cầu mới/ }).getAttribute("aria-checked")).toBe("true");
    expect((screen.getByLabelText("Ghi chú đóng") as HTMLTextAreaElement).value).toBe("GHI-CHU-RIENG");
  });

  it.each([["E5"], ["E6"]])("%s: 'Đã hoàn tất' aria-disabled, bấm không chọn", async (code) => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const target = store.list("open").find((i) => i.exit_code === code)!;
    serve(store);
    renderAt(`/escalations/${target.escalation_id}`);
    await screen.findByText("Ghi chú bàn giao");
    const completed = screen.getByRole("radio", { name: /Đã hoàn tất/ });
    expect(completed.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(completed);
    expect(completed.getAttribute("aria-checked")).toBe("false");
  });
});

// ------------------------------------------------------------------------------------------------ t180

describe("t180: ca đã đóng (?status=closed) → chỉ đọc: kết quả, ghi chú (thiếu → '—'), người đóng, lúc đóng; không form", () => {
  it.each([
    [0, "Đã bổ sung tài liệu KB và xác nhận với người dùng (minh hoạ).", "Đã hoàn tất"],
    [1, "—", "Xác nhận từ chối"],
  ])("ca đã đóng thứ %i", async (idx, note, result) => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const target = store.list("closed")[idx]!;
    const calls = serve(store);
    renderAt(`/escalations/${target.escalation_id}?status=closed`);
    const info = await screen.findByTestId("closed-info");
    expect(within(info).getByTestId("closed-result").textContent).toBe(result);
    expect(within(info).getByTestId("closed-note").textContent).toBe(note);
    expect(within(info).getByTestId("closed-by").textContent).toBe("long.nh");
    expect(within(info).getByTestId("closed-at").textContent).toMatch(/^\d{2}:\d{2}:\d{2} \d{2}\/\d{2}\/\d{4}$/);
    expect(screen.queryByRole("button", { name: "Đóng ca" })).toBeNull();
    expect(screen.queryByRole("radiogroup", { name: "Kết quả đóng" })).toBeNull();
    expect(queueCalls(calls)).toStrictEqual(["/api/escalations/queue?status=closed&limit=50"]);
  });
});

// ------------------------------------------------------------------------------------------------ t189, t190 (hợp đồng sửa 21:15/21:30)

describe("t189: đóng ca 200 — 'Mở yêu cầu mới' → đúng câu REOPENED_TEXT, KHÔNG mã / link ticket mới (kể cả server lỡ trả mã); kết quả khác giữ CLOSED_TEXT", () => {
  async function closeWith(result: RegExp, override?: () => Response) {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const target = store.list("open").find((i) => i.exit_code === "E3")!;
    serve(store, override ? { closeOverride: override } : {});
    renderAt(`/escalations/${target.escalation_id}`);
    await screen.findByText("Ghi chú bàn giao");
    fireEvent.click(screen.getByRole("radio", { name: result }));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "xong" } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));
    return { done: await screen.findByTestId("close-done"), target };
  }
  it("reopened_as_new (MSW: new_ticket_id null) → 'Đã ghi. Nhân viên sẽ được báo gửi yêu cầu mới.'", async () => {
    const { done } = await closeWith(/Mở yêu cầu mới/);
    expect(REOPENED_TEXT).toBe("Đã ghi. Nhân viên sẽ được báo gửi yêu cầu mới.");
    expect(done.textContent).toBe(REOPENED_TEXT);
    expect(done.querySelector("a")).toBeNull();
  });
  it("reopened_as_new mà server lỡ trả mã → vẫn đúng câu, mã KHÔNG xuất hiện ở đâu trên màn (không chữ, không link)", async () => {
    const leaked = "tkt-lo-ma-999";
    const { done } = await closeWith(/Mở yêu cầu mới/, () => json(200, { escalation_id: 1, close_result: "reopened_as_new", new_ticket_id: leaked }));
    expect(done.textContent).toBe(REOPENED_TEXT);
    expect(document.body.textContent).not.toContain(leaked);
    expect([...document.querySelectorAll("a")].some((a) => a.getAttribute("href")?.includes(leaked))).toBe(false);
    expect(document.body.textContent).not.toMatch(/Đã tạo yêu cầu mới/);
  });
  it("completed → câu cũ CLOSED_TEXT (không câu 'Nhân viên sẽ được báo')", async () => {
    const { done } = await closeWith(/Đã hoàn tất/);
    expect(done.textContent).toBe(CLOSED_TEXT);
  });
  it("confirmed_denial → câu cũ CLOSED_TEXT", async () => {
    const { done } = await closeWith(/Xác nhận từ chối/);
    expect(done.textContent).toBe(CLOSED_TEXT);
  });
  it("404 not_found → câu lỗi chung, form giữ nguyên", async () => {
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const target = store.list("open").find((i) => i.exit_code === "E3")!;
    serve(store, { closeOverride: () => json(404, { detail: "not_found" }) });
    renderAt(`/escalations/${target.escalation_id}`);
    await screen.findByText("Ghi chú bàn giao");
    fireEvent.click(screen.getByRole("radio", { name: /Mở yêu cầu mới/ }));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "xong" } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));
    expect((await screen.findByText("Không tìm thấy.")).getAttribute("role")).toBe("alert");
    expect(screen.queryByTestId("close-done")).toBeNull();
  });
});

describe("t190: quyền đóng ca = escalation:handle (L1 + L2) — L1 thấy form đóng qua cổng quyền của route", () => {
  const P = ["ticket:create", "ticket:read:own"];
  const L1: Me = { user_id: "ha.lt", role: "l1", permissions: [...P, "ticket:read:any", "approval:decide", "decision:override", "escalation:handle"] };
  const L2: Me = { user_id: "long.nh", role: "l2", permissions: [...P, "ticket:read:any", "escalation:handle"] };
  const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });
  const perm = STAFF_NAV.find((i) => i.to === "/escalations")!.perm;
  it.each([["L1", L1], ["L2", L2]])("%s: form + nút 'Đóng ca'", async (_n, me) => {
    expect(perm).toBe("escalation:handle");
    const store = createEscalationStore(Date.parse("2026-10-26T05:00:00Z"), 8);
    const target = store.list("open").find((i) => i.exit_code === "E3")!;
    serve(store);
    const client = new QueryClient();
    clients.push(client);
    render(
      <QueryClientProvider client={client}>
        <AuthContext value={signedIn(me)}>
          <MemoryRouter initialEntries={[`/escalations/${target.escalation_id}`]}>
            <Routes>
              <Route path="/escalations/:escalationId" element={<RequirePerm perm={perm}><EscalationDetailRoute submit={viaClient} /></RequirePerm>} />
            </Routes>
          </MemoryRouter>
        </AuthContext>
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("radiogroup", { name: "Kết quả đóng" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Đóng ca" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
