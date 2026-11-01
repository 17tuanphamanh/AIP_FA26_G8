// F3 — màn L2 (hàng đợi escalate, chi tiết, đóng ca minh hoạ). Không gọi backend: fetch giả trả đúng dạng của
// backend/app/api/escalations.py (list[dict], đã sắp theo priority → created_at → escalation_id) và tickets.py.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorMessage, ApiError } from "../../api/errors.ts";
import { closeEscalation, queueQuery } from "../../api/escalations.ts";
import { api } from "../../api/http.ts";
import type { EscalationCloseIn, EscalationQueueItem, Me, TicketView } from "../../api/types.ts";
import { Sidebar } from "../../components/Sidebar.tsx";
import { createEscalationStore } from "../../mocks/fixtures/escalations.ts";
import { closeOutcome } from "../../mocks/handlers/escalation-close.ts";
import { CloseForm } from "./CloseForm.tsx";
import { EscalationDetailRoute } from "./EscalationDetail.tsx";
import { EscalationQueue } from "./EscalationQueue.tsx";
import {
  clampPage,
  DENY_BANNER,
  EMPTY_NOTE,
  EMPTY_VIEW,
  filterQueue,
  foldText,
  GONE_TEXT,
  groupQueue,
  handoffRows,
  isHidden,
  NO_IDS,
  noMatchPartialText,
  notLoadedText,
  NO_MATCH_TEXT,
  pageCount,
  pruneQueueView,
  type QueueView,
  searchWords,
  trackMissed,
  waitingText,
} from "./queue.ts";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear(); // dừng nhịp 15 s trước khi gỡ fetch giả
});

// Nhãn + hạng đúng seed `exit_code_priority` (backend/app/db/alembic/versions/0001_init_22_bang_role_trigger.py).
const SEED: Record<string, { priority: number; label: string }> = {
  E0: { priority: 2, label: "An ninh" },
  E1: { priority: 6, label: "Thường" },
  E2: { priority: 4, label: "Hạ tầng" },
  E3: { priority: 6, label: "Thường, cần bổ sung KB" },
  E5: { priority: 5, label: "Cao" },
  E6: { priority: 3, label: "Có SLA" },
  E9: { priority: 4, label: "Lỗi hệ thống" },
};

let nextId = 100;
function esc(code: string, over: Partial<EscalationQueueItem> = {}): EscalationQueueItem {
  const id = over.escalation_id ?? nextId++;
  return {
    escalation_id: id,
    ticket_id: `0811f300-6bb8-4cd1-8366-${String(id).padStart(12, "0")}`,
    exit_code: code,
    priority: SEED[code]!.priority,
    label: SEED[code]!.label,
    reason_detail: null,
    is_deny_case: code === "E5",
    handoff_note: {
      request: "đăng ký MFA thế nào",
      done_so_far: "Phân loại: faq.",
      why_escalated: `${code} — lý do.`,
      next_for_l2: "Bổ sung tài liệu KB.",
    },
    assigned_to: null,
    created_at: "2026-09-30T13:00:00Z",
    ...over,
  };
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const ticketView = (id: string): TicketView => ({
  ticket_id: id,
  status: "S_ESCALATED",
  waiting_for: null,
  conversation: [{ role: "assistant", kind: "escalation", text: "Đã chuyển kỹ thuật viên hỗ trợ.", ref: null }],
  exit_code: "E3",
  close_reason: null,
  final_state: "S_ESCALATED",
  created_at: "2026-09-30T13:00:00Z",
  closed_at: "2026-09-30T13:01:00Z",
});

type Call = { method: string; url: string; body: string | null };

function stubApi(queue: EscalationQueueItem[], close?: () => Response): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      calls.push({ method, url, body: typeof init.body === "string" ? init.body : null });
      // Hợp đồng N-PA §4: `{items, next_cursor}`; ca mở theo `status=open` (một trang), "Đã đóng" rỗng.
      if (method === "GET" && url.startsWith("/api/escalations/queue")) {
        return json(200, { items: url.includes("status=closed") ? [] : queue, next_cursor: null });
      }
      if (method === "GET" && url.startsWith("/api/tickets/")) return json(200, ticketView(url.split("/").pop()!));
      if (method === "POST" && /^\/api\/escalations\/\d+\/close$/.test(url) && close) return close();
      return json(404, { detail: "not_found" });
    }),
  );
  return calls;
}

const L2: Me = { user_id: "long.nh", role: "l2", permissions: ["escalation:handle", "ticket:create", "ticket:read:any", "kb:edit"] };
const L1: Me = {
  user_id: "ha.lt",
  role: "l1",
  permissions: ["approval:decide", "decision:override", "escalation:handle", "ticket:create", "ticket:read:any"],
};

function renderAt(path: string, { me }: { me?: Me } = {}) {
  const client = new QueryClient();
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        {me ? <Sidebar me={me} onSignOut={async () => true} /> : null}
        <Routes>
          <Route path="/escalations" element={<EscalationQueue />} />
          <Route path="/escalations/:escalationId" element={<EscalationDetailRoute />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const radio = (name: RegExp) => screen.getByRole("radio", { name });

/** CloseForm dùng QueryClient (tải lại hàng đợi sau khi đóng) → bọc provider khi dựng riêng. */
function withClient(ui: ReactNode) {
  const client = new QueryClient();
  clients.push(client);
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}
const COMPLETED = /^Đã hoàn tất/;
const DENIAL = /^Xác nhận từ chối/;

// ------------------------------------------------------------------------------------------------ t28

describe("t28: hàng đợi giữ nguyên thứ tự server, chỉ gom nhóm liên tiếp theo priority", () => {
  // Server trả đã sắp theo priority (2, 4, 4, 6, 6); trong cùng hạng mã E cố ý KHÔNG theo thứ tự chữ (E9 trước E2,
  // E3 trước E1) — sắp lại theo exit_code sẽ tách E2/E9 và E1/E3 thành nhiều nhóm.
  const server = [esc("E0"), esc("E9"), esc("E2"), esc("E3"), esc("E1")];

  it("groupQueue: 3 nhóm đúng thứ tự xuất hiện; E2 + E9 cùng một nhóm; không sắp lại", () => {
    const groups = groupQueue(server);
    expect(groups.map((g) => [g.priority, g.name, g.items.map((i) => i.exit_code)])).toStrictEqual([
      [2, "An ninh", ["E0"]],
      [4, "Lỗi hệ thống / Hạ tầng", ["E9", "E2"]],
      [6, "Thường", ["E3", "E1"]],
    ]);
    expect(groups.flatMap((g) => g.items)).toStrictEqual(server); // cùng phần tử, cùng thứ tự
  });

  it("màn hàng đợi: gọi status=open&limit=50 (N-PA); 'Đã tải N ca'; nhóm + dòng đúng thứ tự server; E3 có huy hiệu 'Cần bổ sung KB'", async () => {
    const calls = stubApi(server);
    renderAt("/escalations");
    await screen.findByText("Lỗi hệ thống / Hạ tầng");
    const groups = document.querySelectorAll('[data-testid="queue-group"]');
    expect([...groups].map((g) => g.querySelector('[data-testid="queue-group-name"]')?.textContent)).toStrictEqual([
      "An ninh",
      "Lỗi hệ thống / Hạ tầng",
      "Thường",
    ]);
    const rows = [...document.querySelectorAll<HTMLElement>('[data-testid="queue-row"]')];
    expect(rows.map((r) => Number(r.dataset.escalationId))).toStrictEqual(server.map((i) => i.escalation_id));
    const e3 = rows.find((r) => r.dataset.exitCode === "E3")!;
    expect(within(e3).getByText("Cần bổ sung KB")).toBeTruthy();
    expect(within(rows[0]!).queryByText("Cần bổ sung KB")).toBeNull();
    expect(screen.getByTestId("queue-count").textContent).toBe("Đã tải 5 ca");
    expect(calls.filter((c) => c.url.startsWith("/api/escalations/queue")).map((c) => c.url)).toStrictEqual([
      "/api/escalations/queue?status=open&limit=50",
    ]);
    expect(screen.queryByTestId("queue-overflow")).toBeNull();
  });

  it("rỗng → 'Không có ca nào đang chờ'; E5 → huy hiệu deny", async () => {
    stubApi([]);
    renderAt("/escalations");
    expect(await screen.findByText("Không có ca nào đang chờ")).toBeTruthy();
    cleanup();
    stubApi([esc("E5"), esc("E3")]);
    renderAt("/escalations");
    const badge = await screen.findByTestId("deny-badge");
    expect(badge.textContent).toBe("Không thực hiện lại"); // N-NGU: không mã trần
    expect(badge.closest<HTMLElement>('[data-testid="queue-row"]')?.dataset.exitCode).toBe("E5");
  });

  it("bổ sung N-L2Q: nhóm > 10 ca — đi hết các trang của mọi nhóm, ghép lại = đúng danh sách server, không thiếu, không lặp", async () => {
    // Trong cùng hạng mã E cố ý xen kẽ (E9/E2, E3/E1) và id KHÔNG tăng dần → sắp lại kiểu nào cũng lệch.
    const big = [
      ...Array.from({ length: 12 }, () => esc("E0")),
      ...Array.from({ length: 23 }, (_, i) => esc(i % 2 ? "E2" : "E9")),
      ...Array.from({ length: 31 }, (_, i) => esc(i % 3 ? "E1" : "E3")),
    ].reverse();
    big.sort((a, b) => a.priority - b.priority); // sort ổn định: chỉ gom theo hạng, trong hạng giữ thứ tự (id giảm dần)
    await renderQueue(big);
    expect(groupNames()).toStrictEqual(["An ninh", "Lỗi hệ thống / Hạ tầng", "Thường"]);
    expect(idsIn().length).toBe(30); // 10 dòng mỗi nhóm ở trang 1
    expect(walkAllPages()).toStrictEqual(ids(big));
  });
});

// ------------------------------------------------------------------------------------------------ t29

describe("t29: ghi chú bàn giao thiếu khoá / rỗng / có HTML → '(không có)' hoặc chữ thô", () => {
  it("handoffRows: đúng 4 khối, đúng nhãn, đúng thứ tự; hỏng → null", () => {
    expect(handoffRows(null).map((r) => [r.label, r.text])).toStrictEqual([
      ["Yêu cầu (đã che)", null],
      ["Hệ thống đã làm", null],
      ["Lý do chuyển", null],
      ["Việc cần làm", null],
    ]);
    expect(handoffRows({ request: 7, done_so_far: " \n ", why_escalated: "<b>x</b>" }).map((r) => r.text)).toStrictEqual([
      null,
      null,
      "<b>x</b>",
      null,
    ]);
  });

  it("màn chi tiết: '(không có)' cho khoá thiếu/rỗng, HTML hiện thành chữ, giữ xuống dòng, không vỡ", async () => {
    const item = esc("E3", {
      escalation_id: 7,
      handoff_note: { request: "", why_escalated: "<b>x</b>", next_for_l2: "Dòng 1\nDòng 2" } as unknown as EscalationQueueItem["handoff_note"],
    });
    stubApi([item]);
    renderAt("/escalations/7");
    await screen.findByText("Ghi chú bàn giao");
    const rows = [...document.querySelectorAll<HTMLElement>('[data-testid="handoff-row"]')];
    expect(rows.map((r) => r.querySelector("dt")?.textContent)).toStrictEqual([
      "Yêu cầu (đã che)",
      "Hệ thống đã làm",
      "Lý do chuyển",
      "Việc cần làm",
    ]);
    const values = rows.map((r) => r.querySelector("dd")!);
    expect(values.map((v) => v.textContent)).toStrictEqual([EMPTY_NOTE, EMPTY_NOTE, "<b>x</b>", "Dòng 1\nDòng 2"]);
    expect(values[2]!.querySelector("b")).toBeNull(); // không có thẻ HTML nào được dựng
    expect(values[3]!.className).toContain("whitespace-pre-line");
    // Hàng đợi cũng hiện chữ thô ở dòng tóm tắt.
    cleanup();
    stubApi([item]);
    renderAt("/escalations");
    const row = await screen.findByTestId("queue-row");
    expect(row.querySelector("b")).toBeNull();
    expect(row.textContent).toContain("<b>x</b>");
  });

  it("handoff_note null → 4 khối '(không có)', không crash", async () => {
    stubApi([esc("E3", { escalation_id: 8, handoff_note: null as unknown as EscalationQueueItem["handoff_note"] })]);
    renderAt("/escalations/8");
    await screen.findByText("Ghi chú bàn giao");
    const values = [...document.querySelectorAll('[data-testid="handoff-row"] dd')].map((d) => d.textContent);
    expect(values).toStrictEqual([EMPTY_NOTE, EMPTY_NOTE, EMPTY_NOTE, EMPTY_NOTE]);
  });
});

// ------------------------------------------------------------------------------------------------ t30

describe("t30: ca deny → banner + 'Đã hoàn tất' khoá; ca thường → mở", () => {
  it("is_deny_case: banner đúng câu; completed aria-disabled, bấm không chọn; lựa chọn khác vẫn chọn được", async () => {
    stubApi([esc("E5", { escalation_id: 5 })]);
    renderAt("/escalations/5");
    const banner = await screen.findByTestId("deny-banner");
    expect(banner.textContent).toBe(`${DENY_BANNER.strong} ${DENY_BANNER.rest}`);
    expect(banner.textContent).toBe("Ca không đủ điều kiện tự xử lý — không thực hiện lại hành động. Chỉ xác nhận từ chối hoặc mở yêu cầu mới.");
    const completed = radio(COMPLETED);
    expect(completed.getAttribute("aria-disabled")).toBe("true");
    expect(completed.textContent).toContain("Không dùng với ca không đủ điều kiện tự xử lý"); // N-NGU: nhãn thay mã E5
    fireEvent.click(completed);
    expect(completed.getAttribute("aria-checked")).toBe("false");
    fireEvent.click(radio(DENIAL));
    expect(radio(DENIAL).getAttribute("aria-checked")).toBe("true");
  });

  it("không deny (E3) → không banner; completed mở và chọn được", async () => {
    stubApi([esc("E3", { escalation_id: 3 })]);
    renderAt("/escalations/3");
    await screen.findByText("Ghi chú bàn giao");
    expect(screen.queryByTestId("deny-banner")).toBeNull();
    const completed = radio(COMPLETED);
    expect(completed.hasAttribute("aria-disabled")).toBe(false);
    fireEvent.click(completed);
    expect(completed.getAttribute("aria-checked")).toBe("true");
  });

  it("E6 (không deny) → không banner, completed vẫn khoá theo B20 §4.3 / Q2 (12b Q-fe-21)", async () => {
    stubApi([esc("E6", { escalation_id: 6 })]);
    renderAt("/escalations/6");
    await screen.findByText("Ghi chú bàn giao");
    expect(screen.queryByTestId("deny-banner")).toBeNull();
    expect(radio(COMPLETED).getAttribute("aria-disabled")).toBe("true");
    expect(radio(COMPLETED).textContent).toContain("quá hạn chờ duyệt"); // N-NGU: nhãn thay mã E6
  });
});

// ------------------------------------------------------------------------------------------------ t31

describe("t31: ghi chú rỗng / chỉ khoảng trắng → không gửi", () => {
  it("chưa chọn kết quả, ghi chú rỗng, chỉ khoảng trắng → không gọi; hợp lệ → gọi đúng 1 lần, ghi chú đã cắt", async () => {
    const submit = vi.fn<(id: number, body: EscalationCloseIn) => Promise<void>>(async () => {});
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const onClosed = vi.fn();
    render(withClient(<CloseForm item={esc("E3", { escalation_id: 31 })} onSubmit={submit} onClosed={onClosed} />));
    const send = screen.getByRole("button", { name: "Đóng ca" });
    const note = screen.getByLabelText("Ghi chú đóng") as HTMLTextAreaElement;

    fireEvent.change(note, { target: { value: "có ghi chú" } });
    fireEvent.click(send);
    expect(screen.getByRole("alert").textContent).toBe("Chọn một kết quả đóng.");

    fireEvent.click(radio(DENIAL));
    for (const value of ["", "   ", " \n\t "]) {
      fireEvent.change(note, { target: { value } });
      fireEvent.click(send);
      expect(screen.getByRole("alert").textContent).toBe("Nhập ghi chú đóng (bắt buộc).");
    }
    expect(submit).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();

    fireEvent.change(note, { target: { value: "  Đã gọi người gửi.  " } });
    fireEvent.click(send);
    await waitFor(() => expect(onClosed).toHaveBeenCalledTimes(1));
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith(31, { close_result: "confirmed_denial", note: "Đã gọi người gửi." });
  });
});

// ------------------------------------------------------------------------------------------------ t32

describe("t32: 422 deny_case_cannot_complete → câu tiếng Việt rõ ràng, form giữ nguyên", () => {
  it("dữ liệu cũ (ca vừa thành deny) → server từ chối completed → báo lý do, giữ lựa chọn + ghi chú, gửi lại được", async () => {
    const calls = stubApi([], () => json(422, { detail: "deny_case_cannot_complete" }));
    // Đi qua client thật (đọc thân lỗi `{detail}`), chỉ thay fetch.
    const viaClient = async (id: number, body: EscalationCloseIn) => {
      await api.request(`/api/escalations/${id}/close`, { method: "POST", json: body });
    };
    render(withClient(<CloseForm item={esc("E3", { escalation_id: 32 })} onSubmit={viaClient} />));
    fireEvent.click(radio(COMPLETED));
    const note = screen.getByLabelText("Ghi chú đóng") as HTMLTextAreaElement;
    fireEvent.change(note, { target: { value: "Đã cấp lại quyền." } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(new ApiError(422, "deny_case_cannot_complete")));
    expect(alert.textContent).toBe("Không đóng được: ca không đủ điều kiện tự xử lý không được chọn “Đã hoàn tất”. Chỉ xác nhận từ chối hoặc mở yêu cầu mới.");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(JSON.parse(calls.find((c) => c.method === "POST")!.body!)).toStrictEqual({
      close_result: "completed",
      note: "Đã cấp lại quyền.",
    });
    expect(radio(COMPLETED).getAttribute("aria-checked")).toBe("true");
    expect(note.value).toBe("Đã cấp lại quyền.");
    expect(screen.queryByTestId("close-done")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Phase 7|Minh hoạ — chưa ghi/);
    expect((screen.getByRole("button", { name: "Đóng ca" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

// ------------------------------------------------------------------------------------------------ t33

describe("t33: đóng ca đi route thật (ĐP 01/11 16:40 — bỏ cờ CLOSE_AVAILABLE), không còn câu 'chưa bật'", () => {
  it("mặc định (không truyền submit) → nút bật, POST /close đúng thân, 200 → 'Đã đóng ca…'", async () => {
    const calls = stubApi([esc("E3", { escalation_id: 33 })], () => json(200, {}));
    renderAt("/escalations/33");
    await screen.findByText("Ghi chú bàn giao");
    expect(screen.queryByTestId("close-unavailable")).toBeNull();
    expect(document.body.textContent).not.toMatch(/chưa bật|Phase 7|Minh hoạ — chưa ghi/);
    const send = screen.getByRole("button", { name: "Đóng ca" }) as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    fireEvent.click(radio(DENIAL));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "  ghi chú  " } });
    fireEvent.click(send);
    await screen.findByTestId("close-done");
    const posts = calls.filter((c) => c.method === "POST");
    expect(posts.map((c) => c.url)).toStrictEqual(["/api/escalations/33/close"]);
    expect(JSON.parse(posts[0]!.body!)).toStrictEqual({ close_result: "confirmed_denial", note: "ghi chú" });
    expect(closeEscalation).toBeTypeOf("function");
  });

  it("422 fields ['close_result'] cho ca E6 → báo lỗi ở chỗ chọn kết quả, giữ form", async () => {
    const calls = stubApi([esc("E6", { escalation_id: 36 })], () =>
      json(422, { error: "invalid_request", fields: ["close_result"] }), // đúng hình backend InvalidRequest(["close_result"])
    );
    renderAt("/escalations/36");
    await screen.findByText("Ghi chú bàn giao");
    fireEvent.click(radio(DENIAL));
    const note = screen.getByLabelText("Ghi chú đóng") as HTMLTextAreaElement;
    fireEvent.change(note, { target: { value: "ghi chú" } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng ca" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("Kết quả đóng này không dùng được cho ca này.");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(screen.queryByTestId("close-done")).toBeNull();
    expect(radio(DENIAL).getAttribute("aria-checked")).toBe("true");
    expect(note.value).toBe("ghi chú");
  });
});

// ------------------------------------------------------------------------------------------------ t34

describe("t34: không có nút duyệt / đồng ý / phê duyệt ở mọi màn /escalations [Chốt 2.2]", () => {
  const APPROVE = /duyệt|đồng ý|phê duyệt/i;
  function buttonTexts(): string[] {
    return [...document.querySelectorAll("button, [role=button], [role=radio], input[type=submit], input[type=button]")].map(
      (el) => [el.textContent, el.getAttribute("aria-label"), el.getAttribute("title"), el.getAttribute("value")].filter(Boolean).join(" "),
    );
  }

  it.each([
    ["hàng đợi (L2)", "/escalations", L2],
    ["hàng đợi (L1 — thanh bên có mục duyệt dạng link)", "/escalations", L1],
    ["chi tiết ca deny", "/escalations/34", L2],
    ["chi tiết ca E3 (có form đóng ca)", "/escalations/35", L2],
    ["ca không còn", "/escalations/999", L1],
  ])("%s", async (_name, path, me) => {
    stubApi([esc("E5", { escalation_id: 34 }), esc("E3", { escalation_id: 35 })]);
    renderAt(path, { me });
    await waitFor(() => expect(document.querySelector("h1")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText(/^Đang tải/)).toBeNull());
    const texts = buttonTexts();
    expect(texts.length).toBeGreaterThan(0); // có quét thật (ít nhất nút đăng xuất / tải lại)
    expect(texts.filter((t) => APPROVE.test(t))).toStrictEqual([]);
  });
});

// ------------------------------------------------------------------------------------------------ t35

describe("t35: tải lại chi tiết khi ca không còn trong hàng đợi", () => {
  it.each([["999"], ["abc"]])("/escalations/%s → gọi lại queue status=open&limit=50 → 'Ca đã đóng…'", async (id) => {
    const calls = stubApi([esc("E3", { escalation_id: 1 })]);
    renderAt(`/escalations/${id}`);
    expect(await screen.findByRole("heading", { name: GONE_TEXT })).toBeTruthy();
    expect(GONE_TEXT).toBe("Ca đã đóng hoặc không còn trong hàng đợi");
    if (id === "999") expect(calls.map((c) => c.url)).toContain("/api/escalations/queue?status=open&limit=50");
    expect(calls.some((c) => c.url.startsWith("/api/tickets/"))).toBe(false);
    expect(screen.getByRole("link", { name: "‹ Hàng chờ chuyển L2" }).getAttribute("href")).toBe("/escalations");
  });

  it("N-PA: ca không có trong trang đã tải mà còn next_cursor → 'Không tìm thấy ca trong N ca đã tải' + Tải thêm (KHÔNG khẳng định đã đóng)", async () => {
    const first = Array.from({ length: 3 }, (_, i) => esc("E3", { escalation_id: 1000 + i }));
    const target = esc("E3", { escalation_id: 999 });
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        if (url.startsWith("/api/escalations/queue")) {
          return url.includes("after=") ? json(200, { items: [target], next_cursor: null }) : json(200, { items: first, next_cursor: "c/1" });
        }
        if (url.startsWith("/api/tickets/")) return json(200, ticketView(url.split("/").pop()!));
        return json(404, { detail: "not_found" });
      }),
    );
    renderAt("/escalations/999");
    expect(await screen.findByRole("heading", { name: notLoadedText(3) })).toBeTruthy();
    expect(notLoadedText(3)).toBe("Không tìm thấy ca trong 3 ca đã tải");
    expect(screen.queryByRole("heading", { name: GONE_TEXT })).toBeNull();
    fireEvent.click(screen.getByTestId("detail-more"));
    expect(await screen.findByText("Ghi chú bàn giao")).toBeTruthy();
    expect(calls).toContain("/api/escalations/queue?status=open&limit=50&after=c%2F1");
  });

  it("bổ sung N-L2Q: 200 ca một nhóm → 20 trang; đi hết các trang = đúng 200 ca server, đúng thứ tự, không thiếu, không lặp", async () => {
    const full = Array.from({ length: 200 }, (_, i) => esc("E3", { escalation_id: 5000 - i }));
    await renderQueue(full);
    expect(idsIn()).toStrictEqual(ids(full.slice(0, 10)));
    expect(pagerText(6)).toBe("Ca 1–10 / 200 · trang 1/20");
    expect(walkAllPages()).toStrictEqual(ids(full));
    expect(pagerText(6)).toBe("Ca 191–200 / 200 · trang 20/20");
  });

  it("id có trong queue → đọc hội thoại thật GET /api/tickets/{ticket_id}, chỉ đọc (không ô nhập, không nút xác nhận)", async () => {
    const item = esc("E3", { escalation_id: 36 });
    const calls = stubApi([item]);
    renderAt("/escalations/36");
    await screen.findByText("Đã chuyển kỹ thuật viên hỗ trợ.");
    expect(calls.map((c) => c.url)).toContain(`/api/tickets/${item.ticket_id}`);
    expect(document.querySelector('[data-kind="escalation"]')).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Đã ổn|Chưa ổn|Gửi/ })).toBeNull();
    expect(screen.queryByLabelText(/Trả lời|Tin nhắn/)).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t36, t37 (bổ sung)

describe("t36: handler MSW /close — kết quả theo kho minh hoạ (N-PA: 200 / 409 / 404 / 422)", () => {
  it.each([
    ["E5 + completed → 422 fields close_result (hợp đồng sửa 21:30)", "E5", { close_result: "completed", note: "x" }, 422, { error: "invalid_request", fields: ["close_result"] }],
    ["E6 + completed → 422 fields close_result (B20)", "E6", { close_result: "completed", note: "x" }, 422, { error: "invalid_request", fields: ["close_result"] }],
    ["E5 + confirmed_denial → 200", "E5", { close_result: "confirmed_denial", note: "x" }, 200, undefined],
    ["E3 + completed → 200", "E3", { close_result: "completed", note: "x" }, 200, undefined],
    ["ghi chú chỉ khoảng trắng → 422 note", "E3", { close_result: "reopened_as_new", note: "  " }, 422, { error: "invalid_request", fields: ["note"] }],
    ["thừa khoá → 422", "E3", { close_result: "completed", note: "x", force: true }, 422, { error: "invalid_request", fields: ["force"] }],
  ])("%s", (_name, code, body, status, expected) => {
    const store = createEscalationStore(Date.now(), 10);
    const item = store.list("open").find((i) => i.exit_code === code)!;
    const outcome = closeOutcome(store, item.escalation_id, body, "long.nh");
    expect(outcome.status).toBe(status);
    if (expected) expect(outcome.body).toStrictEqual(expected);
  });

  it("200 `new_ticket_id` luôn null kể cả reopened_as_new (hợp đồng sửa lần 3); id lạ → 404 not_found", () => {
    const store = createEscalationStore(Date.now(), 10);
    const [a, b] = store.list("open").filter((i) => i.exit_code === "E3");
    expect(closeOutcome(store, a!.escalation_id, { close_result: "reopened_as_new", note: "x" }, "long.nh").body).toStrictEqual({
      escalation_id: a!.escalation_id,
      close_result: "reopened_as_new",
      new_ticket_id: null,
    });
    expect(closeOutcome(store, b!.escalation_id, { close_result: "completed", note: "x" }, "long.nh").body.new_ticket_id).toBeNull();
    expect(closeOutcome(store, 1, { close_result: "completed", note: "x" }, "long.nh")).toStrictEqual({ status: 404, body: { detail: "not_found" } });
  });

  it("200 → ca rời danh sách mở, sang đã đóng (closed_by, close_note); đóng lại → 409 already_closed; id lạ → 404", () => {
    const store = createEscalationStore(Date.now(), 10);
    const item = store.list("open").find((i) => i.exit_code === "E3")!;
    expect(closeOutcome(store, item.escalation_id, { close_result: "completed", note: " xong " }, "long.nh").status).toBe(200);
    expect(store.list("open").some((i) => i.escalation_id === item.escalation_id)).toBe(false);
    expect(store.list("closed")[0]).toMatchObject({ escalation_id: item.escalation_id, close_result: "completed", closed_by: "long.nh", close_note: "xong" });
    expect(closeOutcome(store, item.escalation_id, { close_result: "completed", note: "x" }, "long.nh")).toStrictEqual({ status: 409, body: { detail: "already_closed" } });
    expect(closeOutcome(store, 1, { close_result: "completed", note: "x" }, "long.nh").status).toBe(404);
  });
});

describe("t37: thời gian chờ tính từ created_at", () => {
  const at = Date.parse("2026-09-30T13:00:00Z");
  it.each([
    [30_000, "chờ dưới 1 phút"],
    [-60_000, "chờ dưới 1 phút"],
    [6 * 60_000, "chờ 6 phút"],
    [61 * 60_000, "chờ 1 giờ"],
    [49 * 3_600_000, "chờ 2 ngày"],
  ])("+%i ms → %s", (delta, text) => {
    expect(waitingText("2026-09-30T13:00:00Z", at + delta)).toBe(text);
  });
});

// ================================================================================================ N-L2Q (t94–t105)
// Tìm ca, thẻ nhóm, thu gọn, phân trang trong nhóm — làm ở trình duyệt, trên các ca ĐÃ tải. Bất biến của chặng: không dòng
// nào bị ẩn mà thiếu con số bên cạnh; không sắp lại thứ tự server; trạng thái chỉ trong bộ nhớ.

const ids = (items: readonly EscalationQueueItem[]) => items.map((i) => i.escalation_id);
const many = (code: string, n: number, over: Partial<EscalationQueueItem> = {}) => Array.from({ length: n }, () => esc(code, over));

type LiveQueue = { queue: EscalationQueueItem[]; calls: Call[]; cursor: string | null; more: EscalationQueueItem[] };

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>;
}

/** Màn hàng đợi với fetch giả đọc `live.queue` lúc gọi → đổi `live.queue` rồi tải lại = server trả dữ liệu mới. */
async function renderQueue(initial: EscalationQueueItem[], { cursor = null, more = [] }: { cursor?: string | null; more?: EscalationQueueItem[] } = {}) {
  const live: LiveQueue = { queue: initial, calls: [], cursor, more };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const method = init.method ?? "GET";
      live.calls.push({ method, url, body: typeof init.body === "string" ? init.body : null });
      if (method === "GET" && url.startsWith("/api/escalations/queue")) {
        // Trang đầu = `live.queue` (+ `live.cursor`); trang sau (`after`) = `live.more`, hết trang.
        return url.includes("after=")
          ? json(200, { items: live.more, next_cursor: null })
          : json(200, { items: live.queue, next_cursor: live.cursor });
      }
      return json(404, { detail: "not_found" });
    }),
  );
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/escalations"]}>
        <Routes>
          <Route
            path="/escalations"
            element={
              <>
                <EscalationQueue />
                <LocationProbe />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByTestId("queue-count");
  /** Nhịp tự tải lại (`refetchInterval` gọi lại đúng truy vấn này) — chờ tới khi màn đã dựng dữ liệu mới. */
  const tick = async (next: EscalationQueueItem[]) => {
    live.queue = next;
    await act(async () => {
      await client.refetchQueries({ queryKey: queueQuery().queryKey });
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(screen.getByTestId("queue-count").textContent).toBe(`Đã tải ${next.length} ca`);
  };
  /** Nút "Tải lại". */
  const reloadButton = async (next: EscalationQueueItem[]) => {
    live.queue = next;
    const before = live.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "Tải lại" }));
    await waitFor(() => {
      expect(live.calls.length).toBe(before + 1);
      expect((screen.getByRole("button", { name: "Tải lại" }) as HTMLButtonElement).disabled).toBe(false);
    });
    expect(screen.getByTestId("queue-count").textContent).toBe(`Đã tải ${next.length} ca`);
  };
  return { live, tick, reloadButton };
}

/** Sau mọi thao tác: URL không đổi (chữ tìm / trang / thẻ không lên URL), không lời gọi mạng nào ngoài GET hàng đợi. */
function expectQuiet(live: LiveQueue) {
  expect(screen.getByTestId("location").textContent).toBe("/escalations");
  expect(live.calls.length).toBeGreaterThan(0);
  expect(live.calls.filter((c) => !(c.method === "GET" && c.url === "/api/escalations/queue?status=open&limit=50"))).toStrictEqual([]);
}

const groupOf = (priority: number) => document.querySelector<HTMLElement>(`[data-testid="queue-group"][data-priority="${priority}"]`);
const groupNames = () => [...document.querySelectorAll('[data-testid="queue-group-name"]')].map((n) => n.textContent);
const idsIn = (root: ParentNode | null = document) =>
  [...(root ?? document).querySelectorAll<HTMLElement>('[data-testid="queue-row"]')].map((r) => Number(r.dataset.escalationId));
const pagerOf = (priority: number) => groupOf(priority)?.querySelector<HTMLElement>('[data-testid="queue-pager"]') ?? null;
const pagerText = (priority: number) => pagerOf(priority)?.querySelector("span")?.textContent ?? null;
const pageButton = (priority: number, name: string) => within(pagerOf(priority)!).getByRole("button", { name }) as HTMLButtonElement;
const toggleOf = (priority: number) => groupOf(priority)!.querySelector<HTMLButtonElement>('[data-testid="queue-group-toggle"]')!;
const countOf = (priority: number) => groupOf(priority)?.querySelector('[data-testid="queue-group-count"]')?.textContent ?? null;
const typeSearch = (value: string) => fireEvent.change(screen.getByTestId("queue-search"), { target: { value } });
const searchCount = () => screen.queryByTestId("queue-search-count")?.textContent ?? null;
const tabOf = (priority: number) => document.querySelector<HTMLButtonElement>(`[data-testid="queue-tab"][data-priority="${priority}"]`)!;
const tabAll = () => screen.getByTestId("queue-tab-all");
const shownPriorities = () => [...document.querySelectorAll<HTMLElement>('[data-testid="queue-group"]')].map((g) => Number(g.dataset.priority));

/** Đi hết các trang của mọi nhóm đang hiện (Đầu → Sau … tới khi Sau khoá), trả id theo thứ tự đã thấy. */
function walkAllPages(): number[] {
  const seen: number[] = [];
  for (const group of document.querySelectorAll<HTMLElement>('[data-testid="queue-group"]')) {
    const priority = Number(group.dataset.priority);
    if (!pagerOf(priority)) {
      seen.push(...idsIn(group));
      continue;
    }
    fireEvent.click(pageButton(priority, "Đầu"));
    for (let guard = 0; guard < 100; guard += 1) {
      seen.push(...idsIn(group));
      const next = pageButton(priority, "Sau");
      if (next.disabled) break;
      fireEvent.click(next);
    }
  }
  return seen;
}

// ------------------------------------------------------------------------------------------------ t94

describe("t94: foldText / searchWords / filterQueue — bỏ dấu, mọi từ phải khớp, giữ thứ tự server", () => {
  it("foldText: chữ hoa → thường, bỏ dấu, đ/Đ → d, cắt khoảng trắng đầu cuối", () => {
    expect(foldText("  An NINH \n")).toBe("an ninh");
    expect(foldText("Từ chối")).toBe("tu choi");
    expect(foldText("Đường truyền đứt")).toBe("duong truyen dut");
    expect(foldText("ĐĂNG KÝ MFA")).toBe("dang ky mfa");
  });

  it("searchWords: tách theo khoảng trắng; toàn khoảng trắng / chỉ dấu kết hợp → [] (không tìm)", () => {
    expect(searchWords("  E3   Hạ  tầng ")).toStrictEqual(["e3", "ha", "tang"]);
    expect(searchWords("")).toStrictEqual([]);
    expect(searchWords(" \t\n ")).toStrictEqual([]);
    expect(searchWords("́̀")).toStrictEqual([]);
  });

  const server = [
    esc("E0", { escalation_id: 905, assigned_to: "long.nh" }),
    esc("E9", { escalation_id: 903, handoff_note: { request: "", done_so_far: "", why_escalated: "Đường truyền đứt", next_for_l2: "" } }),
    esc("E2", { escalation_id: 904 }),
    esc("E3", { escalation_id: 901, assigned_to: "long.nh" }),
    esc("E1", { escalation_id: 902 }),
  ];

  it("ô trống / toàn khoảng trắng → đủ ca, đúng thứ tự server (mảng mới)", () => {
    for (const q of ["", "   ", "\t"]) {
      const out = filterQueue(server, q);
      expect(out).toStrictEqual(server);
      expect(out).not.toBe(server);
    }
  });

  it("nhiều từ = VÀ (mọi từ phải khớp), không phải HOẶC", () => {
    expect(ids(filterQueue(server, "an ninh long.nh"))).toStrictEqual([905]);
    expect(ids(filterQueue(server, "E3 long.nh"))).toStrictEqual([901]);
    expect(ids(filterQueue(server, "E3 an ninh"))).toStrictEqual([]);
  });

  it("tìm theo ticket_id (cả đoạn), '#id', mã E, người đang xử lý, tên nhóm không dấu, lý do có 'đ'", () => {
    expect(ids(filterQueue(server, server[2]!.ticket_id))).toStrictEqual([904]);
    expect(ids(filterQueue(server, server[2]!.ticket_id.slice(-6)))).toStrictEqual([904]);
    // Dựng chuỗi lúc chạy: dấu thăng + 3 chữ số viết trần trong mã nguồn bị check:style coi là mã màu.
    expect(ids(filterQueue(server, `#${server[4]!.escalation_id}`))).toStrictEqual([902]);
    expect(ids(filterQueue(server, "e9"))).toStrictEqual([903]);
    expect(ids(filterQueue(server, "LONG.NH"))).toStrictEqual([905, 901]);
    expect(ids(filterQueue(server, "an ninh"))).toStrictEqual([905]);
    expect(ids(filterQueue(server, "ha tang"))).toStrictEqual([904]);
    expect(ids(filterQueue(server, "duong truyen"))).toStrictEqual([903]);
    expect(ids(filterQueue(server, "Đường"))).toStrictEqual([903]);
  });

  it("kết quả giữ đúng thứ tự server (id không tăng, mã E không theo chữ cái)", () => {
    // "ly do" khớp lý do mặc định "Ex — lý do." của mọi ca trừ 903.
    expect(ids(filterQueue(server, "ly do"))).toStrictEqual([905, 904, 901, 902]);
    expect(ids(filterQueue(server, "#90"))).toStrictEqual([905, 903, 904, 901, 902]);
  });
});

// ------------------------------------------------------------------------------------------------ t95

describe("t95: pageCount / clampPage — 0 ca → 1 trang; trang 0, âm, vượt cuối, NaN, số lẻ", () => {
  it("pageCount", () => {
    expect([0, 1, 10, 11, 20, 25, 200].map((n) => pageCount(n))).toStrictEqual([1, 1, 1, 2, 2, 3, 20]);
    expect(pageCount(Number.NaN)).toBe(1);
  });

  it.each([
    [1, 25, 1],
    [2, 25, 2],
    [3, 25, 3],
    [0, 25, 1],
    [-3, 25, 1],
    [4, 25, 3],
    [99, 25, 3],
    [5, 0, 1],
    [1, 0, 1],
    [Number.NaN, 25, 1],
    [Number.POSITIVE_INFINITY, 25, 1],
    [Number.NEGATIVE_INFINITY, 25, 1],
    [1.5, 25, 1],
    [2.9, 25, 2],
  ])("clampPage(%s, %s) = %s", (page, total, expected) => {
    expect(clampPage(page, total)).toBe(expected);
  });
});

// ------------------------------------------------------------------------------------------------ t96

describe("t96: pruneQueueView — dọn theo danh sách vừa tải; không đổi gì → trả ĐÚNG object cũ (không setState lặp)", () => {
  const list = [...many("E0", 3), ...many("E9", 12), ...many("E3", 25)];
  const view: QueueView = { collapsed: new Set([2, 6]), pages: { 4: 2, 6: 3 }, active: 4 };

  it("không lặp vô hạn: dữ liệu không làm đổi trạng thái → cùng tham chiếu; gọi lại trên kết quả → cùng tham chiếu", () => {
    expect(pruneQueueView(view, list)).toBe(view);
    expect(pruneQueueView(EMPTY_VIEW, list)).toBe(EMPTY_VIEW);
    expect(pruneQueueView(EMPTY_VIEW, [])).toBe(EMPTY_VIEW);
    const shrunk = pruneQueueView(view, [...many("E9", 3), ...many("E3", 5)]);
    expect(shrunk).not.toBe(view);
    expect(pruneQueueView(shrunk, [...many("E9", 3), ...many("E3", 5)])).toBe(shrunk); // điểm dừng sau 1 bước
  });

  it("nhóm hết ca → bỏ khỏi collapsed + pages; thẻ đang chọn không còn → 'Tất cả' (null)", () => {
    const out = pruneQueueView(view, many("E3", 25));
    expect([...out.collapsed]).toStrictEqual([6]);
    expect(out.pages).toStrictEqual({ 6: 3 });
    expect(out.active).toBeNull();
  });

  it("trang vượt trang cuối → LƯU trang hợp lệ gần nhất (nhóm lớn lại không tự nhảy về trang cũ)", () => {
    const out = pruneQueueView(view, [...many("E0", 3), ...many("E9", 12), ...many("E3", 5)]);
    expect(out.pages).toStrictEqual({ 4: 2, 6: 1 });
    expect(pruneQueueView(out, list).pages).toStrictEqual({ 4: 2, 6: 1 });
    expect([...out.collapsed].sort()).toStrictEqual([2, 6]);
    expect(out.active).toBe(4);
  });
});

// ------------------------------------------------------------------------------------------------ t97

describe("t97: phân trang trong nhóm — 10 ca/trang, 'Ca a–b / N · trang p/P', khoá nút ở hai đầu", () => {
  it("nhóm 25 ca: trang 1 → Sau → Cuối → Trước → Đầu; nhãn nav kèm tên nhóm", async () => {
    const group = many("E3", 25);
    const { live } = await renderQueue(group);
    expect(idsIn()).toStrictEqual(ids(group.slice(0, 10)));
    expect(pagerText(6)).toBe("Ca 1–10 / 25 · trang 1/3");
    expect(pagerOf(6)!.getAttribute("aria-label")).toBe("Phân trang trong nhóm Thường");
    expect([pageButton(6, "Đầu").disabled, pageButton(6, "Trước").disabled]).toStrictEqual([true, true]);
    expect([pageButton(6, "Sau").disabled, pageButton(6, "Cuối").disabled]).toStrictEqual([false, false]);

    fireEvent.click(pageButton(6, "Sau"));
    expect(idsIn()).toStrictEqual(ids(group.slice(10, 20)));
    expect(pagerText(6)).toBe("Ca 11–20 / 25 · trang 2/3");
    expect(pageButton(6, "Đầu").disabled || pageButton(6, "Sau").disabled).toBe(false);

    fireEvent.click(pageButton(6, "Cuối"));
    expect(idsIn()).toStrictEqual(ids(group.slice(20)));
    expect(pagerText(6)).toBe("Ca 21–25 / 25 · trang 3/3");
    expect([pageButton(6, "Sau").disabled, pageButton(6, "Cuối").disabled]).toStrictEqual([true, true]);
    expect([pageButton(6, "Đầu").disabled, pageButton(6, "Trước").disabled]).toStrictEqual([false, false]);

    fireEvent.click(pageButton(6, "Trước"));
    expect(pagerText(6)).toBe("Ca 11–20 / 25 · trang 2/3");
    fireEvent.click(pageButton(6, "Đầu"));
    expect(idsIn()).toStrictEqual(ids(group.slice(0, 10)));
    expectQuiet(live);
  });

  it("nhóm ≤ 10 ca → không pager; mỗi nhóm có pager riêng, nhãn riêng", async () => {
    const server = [...many("E0", 10), ...many("E9", 11), ...many("E3", 3)];
    await renderQueue(server);
    expect(pagerOf(2)).toBeNull();
    expect(pagerOf(6)).toBeNull();
    expect(pagerText(4)).toBe("Ca 1–10 / 11 · trang 1/2");
    expect(idsIn()).toStrictEqual(ids([...server.slice(0, 20), ...server.slice(21)]));
    const labels = [...document.querySelectorAll('[data-testid="queue-pager"]')].map((n) => n.getAttribute("aria-label"));
    expect(labels).toStrictEqual(["Phân trang trong nhóm Lỗi hệ thống"]);
  });
});

// ------------------------------------------------------------------------------------------------ t98

describe("t98: thu gọn nhóm — 0 dòng nhưng '· N ca' còn; mở lại → đúng trang cũ", () => {
  it("thu gọn nhóm đang ở trang 2 → aria-expanded=false, 0 dòng, không pager, số ca còn; nhóm khác không đổi; mở lại → trang 2", async () => {
    const server = [...many("E0", 2), ...many("E3", 25)];
    const { live } = await renderQueue(server);
    fireEvent.click(pageButton(6, "Sau"));
    expect(toggleOf(6).getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggleOf(6));
    expect(toggleOf(6).getAttribute("aria-expanded")).toBe("false");
    expect(idsIn(groupOf(6))).toStrictEqual([]);
    expect(countOf(6)).toBe("· 25 ca");
    expect(pagerOf(6)).toBeNull();
    expect(idsIn(groupOf(2))).toStrictEqual(ids(server.slice(0, 2)));
    expect(countOf(2)).toBe("· 2 ca");
    fireEvent.click(toggleOf(6));
    expect(toggleOf(6).getAttribute("aria-expanded")).toBe("true");
    expect(idsIn(groupOf(6))).toStrictEqual(ids(server.slice(12, 22)));
    expect(pagerText(6)).toBe("Ca 11–20 / 25 · trang 2/3");
    expectQuiet(live);
  });
});

// ------------------------------------------------------------------------------------------------ t99

describe("t99: thẻ nhóm — chọn một nhóm chỉ hiện nhóm đó; số trên thẻ đúng; nhóm đang chọn biến mất → 'Tất cả' hẳn", () => {
  const e0 = many("E0", 2);
  const mid = [esc("E9"), esc("E2")];
  const e3 = many("E3", 12);

  it("số trên thẻ; chọn 'Thường' → chỉ nhóm đó (đầu trang không đổi); 'Tất cả' → đủ nhóm", async () => {
    const { live } = await renderQueue([...e0, ...mid, ...e3]);
    expect(tabAll().textContent).toBe("Tất cả · 16");
    expect(tabAll().getAttribute("aria-selected")).toBe("true");
    expect(screen.getByTestId("queue-tabs").getAttribute("role")).toBe("tablist");
    expect([tabOf(2), tabOf(4), tabOf(6)].map((t) => t.textContent)).toStrictEqual([
      "An ninh · 2",
      "Lỗi hệ thống / Hạ tầng · 2",
      "Thường · 12",
    ]);
    fireEvent.click(tabOf(6));
    expect(tabOf(6).getAttribute("aria-selected")).toBe("true");
    expect(tabAll().getAttribute("aria-selected")).toBe("false");
    expect(shownPriorities()).toStrictEqual([6]);
    expect(idsIn()).toStrictEqual(ids(e3.slice(0, 10)));
    expect(screen.getByTestId("queue-count").textContent).toBe("Đã tải 16 ca");
    fireEvent.click(tabAll());
    expect(shownPriorities()).toStrictEqual([2, 4, 6]);
    expectQuiet(live);
  });

  it("đang chọn 'An ninh' → tải lại không còn An ninh → 'Tất cả'; An ninh có lại → VẪN 'Tất cả' (không tự nhảy về thẻ cũ)", async () => {
    const { tick } = await renderQueue([...e0, ...mid, ...e3]);
    fireEvent.click(tabOf(2));
    expect(shownPriorities()).toStrictEqual([2]);
    await tick([...mid, ...e3]);
    expect(tabAll().getAttribute("aria-selected")).toBe("true");
    expect(shownPriorities()).toStrictEqual([4, 6]);
    await tick([esc("E0"), ...mid, ...e3]);
    expect(tabAll().getAttribute("aria-selected")).toBe("true");
    expect(tabOf(2).getAttribute("aria-selected")).toBe("false");
    expect(shownPriorities()).toStrictEqual([2, 4, 6]);
  });
});

// ------------------------------------------------------------------------------------------------ t100

describe("t100: ô tìm — 'Khớp k / N ca', câu không khớp (hết trang / còn trang theo next_cursor), xoá ô; đầu trang tính trên TỔNG", () => {
  it("dưới trần: đếm khớp; tên nhóm theo danh sách chưa lọc, số = số khớp; không khớp → câu ngắn; xoá ô → mất dòng đếm", async () => {
    const server = [...many("E0", 2), esc("E9"), esc("E2"), ...many("E3", 12)];
    const { live } = await renderQueue(server);
    const box = screen.getByTestId("queue-search") as HTMLInputElement;
    expect(box.maxLength).toBe(100);
    expect(searchCount()).toBeNull();

    typeSearch("   ");
    expect(searchCount()).toBeNull(); // toàn khoảng trắng = không tìm
    expect(idsIn().length).toBe(14);

    typeSearch("ha tang");
    expect(searchCount()).toBe("Khớp 1 / 16 ca");
    expect(screen.getByTestId("queue-search-count").getAttribute("role")).toBe("status");
    expect(idsIn()).toStrictEqual([server[3]!.escalation_id]);
    // N4: nhãn không đổi theo chữ gõ — vẫn tên đủ của nhóm; số bên cạnh = số ca khớp.
    expect(groupNames()).toStrictEqual(["Lỗi hệ thống / Hạ tầng"]);
    expect(countOf(4)).toBe("· 1 ca");
    expect(tabOf(4).textContent).toBe("Lỗi hệ thống / Hạ tầng · 1");
    expect(tabAll().textContent).toBe("Tất cả · 1");
    // P5: đầu trang tính trên TỔNG đã tải, không đổi theo ô tìm.
    expect(screen.getByTestId("queue-count").textContent).toBe("Đã tải 16 ca");

    typeSearch("e3");
    expect(searchCount()).toBe("Khớp 12 / 16 ca");
    expect(pagerText(6)).toBe("Ca 1–10 / 12 · trang 1/2");

    typeSearch("khong co ca nay");
    expect(searchCount()).toBe("Khớp 0 / 16 ca");
    expect(screen.getByText(NO_MATCH_TEXT)).toBeTruthy();
    expect(NO_MATCH_TEXT).toBe("Không có ca nào khớp ô tìm");
    expect(screen.queryByText(/Không có ca nào đang chờ/)).toBeNull();
    expect(idsIn()).toStrictEqual([]);

    typeSearch("");
    expect(searchCount()).toBeNull();
    expect(idsIn().length).toBe(14);
    expect(screen.getByTestId("queue-count").textContent).toBe("Đã tải 16 ca");
    expectQuiet(live);
  });

  it("còn next_cursor: dòng đếm thêm 'chỉ tìm trong N ca đã tải'; 0 khớp → câu không khẳng định ca không tồn tại; không còn băng 200", async () => {
    const loaded = [...many("E0", 1), ...many("E3", 29)];
    await renderQueue(loaded, { cursor: "c-2" });
    expect(screen.getByTestId("queue-count").textContent).toBe("Đã tải 30 ca · còn ca chưa tải");
    typeSearch(loaded[15]!.ticket_id);
    expect(searchCount()).toBe("Khớp 1 / 30 ca · chỉ tìm trong 30 ca đã tải");
    expect(idsIn()).toStrictEqual([loaded[15]!.escalation_id]);
    typeSearch("00000000-0000-0000-0000-000000000000");
    expect(searchCount()).toBe("Khớp 0 / 30 ca · chỉ tìm trong 30 ca đã tải");
    expect(screen.getByText(noMatchPartialText(30))).toBeTruthy();
    expect(noMatchPartialText(30)).toBe("Không có ca nào khớp trong 30 ca đã tải — ca cần tìm có thể nằm ngoài danh sách.");
    expect(screen.queryByText(NO_MATCH_TEXT)).toBeNull();
    expect(screen.queryByTestId("queue-overflow")).toBeNull();
  });

  it("hết trang (next_cursor null): dòng đếm KHÔNG có phần 'chỉ tìm trong…', không nút Tải thêm", async () => {
    const server = many("E3", 199);
    await renderQueue(server);
    typeSearch("e3");
    expect(searchCount()).toBe("Khớp 199 / 199 ca");
    expect(screen.queryByTestId("queue-overflow")).toBeNull();
    expect(screen.queryByTestId("queue-more")).toBeNull();
  });

  it("hàng đợi rỗng → không có ô tìm, chỉ 'Không có ca nào đang chờ'", async () => {
    await renderQueue([]);
    expect(await screen.findByText("Không có ca nào đang chờ")).toBeTruthy();
    expect(screen.queryByTestId("queue-search")).toBeNull();
    expect(screen.queryByTestId("queue-tabs")).toBeNull();
  });
});

// ------------------------------------------------------------------------------------------------ t101

describe("t101: tự tải lại / nút 'Tải lại' giữ chữ tìm, nhóm thu gọn, trang, thẻ đang chọn — chỉ trong bộ nhớ", () => {
  it("không tìm: thu gọn + trang + thẻ còn nguyên qua nút 'Tải lại' và qua nhịp tự tải lại", async () => {
    const e0 = many("E0", 3);
    const e9 = many("E9", 12);
    const e3 = many("E3", 25);
    const storage = vi.spyOn(Storage.prototype, "setItem");
    const logs = (["log", "info", "debug", "warn"] as const).map((m) => vi.spyOn(console, m).mockImplementation(() => {}));
    const { live, tick, reloadButton } = await renderQueue([...e0, ...e9, ...e3]);
    fireEvent.click(toggleOf(2));
    fireEvent.click(pageButton(4, "Sau"));
    fireEvent.click(pageButton(6, "Cuối"));

    const more = esc("E3");
    await reloadButton([...e0, ...e9, ...e3, more]);
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("false");
    expect(countOf(2)).toBe("· 3 ca");
    expect(pagerText(4)).toBe("Ca 11–12 / 12 · trang 2/2");
    expect(pagerText(6)).toBe("Ca 21–26 / 26 · trang 3/3");
    expect(idsIn(groupOf(6))).toStrictEqual(ids([...e3.slice(20), more]));

    fireEvent.click(tabOf(4));
    await tick([...e0, ...e9, ...e3, more, esc("E3")]);
    expect(tabOf(4).getAttribute("aria-selected")).toBe("true");
    expect(shownPriorities()).toStrictEqual([4]);
    expect(pagerText(4)).toBe("Ca 11–12 / 12 · trang 2/2");
    fireEvent.click(tabAll());
    expect(pagerText(6)).toBe("Ca 21–27 / 27 · trang 3/3");
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("false");

    expect(storage).not.toHaveBeenCalled();
    for (const spy of logs) expect(spy).not.toHaveBeenCalled();
    expectQuiet(live);
    storage.mockRestore();
    for (const spy of logs) spy.mockRestore();
  });

  it("đang tìm: chữ trong ô, trang + thu gọn CỦA CHẾ ĐỘ TÌM không bị tải lại đặt lại", async () => {
    const e0 = many("E0", 3);
    const e3 = many("E3", 25);
    const { live, tick, reloadButton } = await renderQueue([...e0, ...e3]);
    typeSearch("E3");
    fireEvent.click(pageButton(6, "Sau"));
    expect(pagerText(6)).toBe("Ca 11–20 / 25 · trang 2/3");
    await tick([...e0, ...e3, esc("E3")]);
    expect((screen.getByTestId("queue-search") as HTMLInputElement).value).toBe("E3");
    expect(searchCount()).toBe("Khớp 26 / 29 ca");
    expect(pagerText(6)).toBe("Ca 11–20 / 26 · trang 2/3");
    fireEvent.click(toggleOf(6));
    await reloadButton([...e0, ...e3, esc("E3"), esc("E3")]);
    expect((screen.getByTestId("queue-search") as HTMLInputElement).value).toBe("E3");
    expect(toggleOf(6).getAttribute("aria-expanded")).toBe("false");
    expect(countOf(6)).toBe("· 27 ca");
    fireEvent.click(toggleOf(6));
    expect(pagerText(6)).toBe("Ca 11–20 / 27 · trang 2/3");
    expectQuiet(live);
  });
});

// ------------------------------------------------------------------------------------------------ t102

describe("t102: trang vượt trang cuối sau tải lại → trang hợp lệ gần nhất, không vỡ; nhóm lớn lại không tự nhảy về trang cũ", () => {
  it("trang 3/3 → tải lại còn 5 ca → 5 dòng, không pager → lại 25 ca → trang 1", async () => {
    const e3 = many("E3", 25);
    const { live, tick } = await renderQueue(e3);
    fireEvent.click(pageButton(6, "Cuối"));
    expect(pagerText(6)).toBe("Ca 21–25 / 25 · trang 3/3");
    await tick(e3.slice(0, 5));
    expect(idsIn()).toStrictEqual(ids(e3.slice(0, 5)));
    expect(pagerOf(6)).toBeNull();
    expect(countOf(6)).toBe("· 5 ca");
    await tick(e3);
    expect(pagerText(6)).toBe("Ca 1–10 / 25 · trang 1/3");
    expect(idsIn()).toStrictEqual(ids(e3.slice(0, 10)));
    expectQuiet(live);
  });

  it("trang 3/3 → tải lại còn 15 ca → trang 2/2 (gần nhất) → lại 25 ca → vẫn trang 2", async () => {
    const e3 = many("E3", 25);
    const { tick } = await renderQueue(e3);
    fireEvent.click(pageButton(6, "Cuối"));
    await tick(e3.slice(0, 15));
    expect(pagerText(6)).toBe("Ca 11–15 / 15 · trang 2/2");
    await tick(e3);
    expect(pagerText(6)).toBe("Ca 11–20 / 25 · trang 2/3");
  });
});

// ------------------------------------------------------------------------------------------------ t103

describe("t103: chế độ tìm (P11a, Q-fe-42 A) — trạng thái RIÊNG: mọi nhóm mở, trang 1; xoá ô → về đúng trạng thái đã lưu", () => {
  it("1 ca khớp trong nhóm ĐANG THU GỌN → dòng hiện; xoá ô → nhóm thu gọn lại", async () => {
    const e0 = many("E0", 3);
    const { live } = await renderQueue([...e0, ...many("E3", 4)]);
    fireEvent.click(toggleOf(2));
    expect(idsIn(groupOf(2))).toStrictEqual([]);
    typeSearch(e0[1]!.ticket_id);
    expect(searchCount()).toBe("Khớp 1 / 7 ca");
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("true");
    expect(idsIn()).toStrictEqual([e0[1]!.escalation_id]);
    typeSearch("");
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("false");
    expect(idsIn(groupOf(2))).toStrictEqual([]);
    expectQuiet(live);
  });

  it("> 10 ca khớp trong nhóm đang ở trang 3 → tìm về trang 1 (10 ca khớp đầu); xoá ô → lại trang 3", async () => {
    const e3 = many("E3", 25);
    await renderQueue(e3);
    fireEvent.click(pageButton(6, "Cuối"));
    typeSearch("ly do");
    expect(searchCount()).toBe("Khớp 25 / 25 ca");
    expect(pagerText(6)).toBe("Ca 1–10 / 25 · trang 1/3");
    expect(idsIn()).toStrictEqual(ids(e3.slice(0, 10)));
    typeSearch("");
    expect(pagerText(6)).toBe("Ca 21–25 / 25 · trang 3/3");
  });

  it("trong kết quả tìm: Sau/Trước, thu gọn được; thêm/bớt khoảng trắng KHÔNG đặt lại; danh sách từ đổi → đặt lại", async () => {
    const e3 = many("E3", 25);
    await renderQueue([...many("E0", 2), ...e3]);
    typeSearch("e3");
    fireEvent.click(pageButton(6, "Sau"));
    fireEvent.click(pageButton(6, "Sau"));
    fireEvent.click(pageButton(6, "Trước"));
    expect(pagerText(6)).toBe("Ca 11–20 / 25 · trang 2/3");
    for (const same of ["e3 ", "  e3", " E3\t"]) {
      typeSearch(same);
      expect(pagerText(6)).toBe("Ca 11–20 / 25 · trang 2/3");
    }
    fireEvent.click(toggleOf(6));
    typeSearch("e3  ");
    expect(toggleOf(6).getAttribute("aria-expanded")).toBe("false");
    typeSearch("e3 ly"); // danh sách từ đổi
    expect(toggleOf(6).getAttribute("aria-expanded")).toBe("true");
    expect(pagerText(6)).toBe("Ca 1–10 / 25 · trang 1/3");
    // Thao tác trong chế độ tìm không lọt sang trạng thái đã lưu.
    fireEvent.click(pageButton(6, "Cuối"));
    fireEvent.click(toggleOf(6));
    expect(groupOf(2)).toBeNull(); // An ninh không khớp "e3 ly"
    typeSearch("");
    expect(toggleOf(6).getAttribute("aria-expanded")).toBe("true");
    expect(pagerText(6)).toBe("Ca 1–10 / 25 · trang 1/3");
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("true");
  });

  it("trang trong chế độ tìm vẫn bị chặn theo số ca khớp (tải lại còn ít ca khớp hơn)", async () => {
    const e3 = many("E3", 25);
    const { tick } = await renderQueue(e3);
    typeSearch("e3");
    fireEvent.click(pageButton(6, "Cuối"));
    expect(pagerText(6)).toBe("Ca 21–25 / 25 · trang 3/3");
    await tick([...e3.slice(0, 12), ...many("E1", 20)]);
    expect(searchCount()).toBe("Khớp 12 / 32 ca");
    expect(pagerText(6)).toBe("Ca 11–12 / 12 · trang 2/2");
  });

  it("thẻ dùng chung hai chế độ: thẻ đang chọn không có ca khớp → tạm 'Tất cả', xoá ô → lại thẻ cũ; chọn thẻ khi tìm → giữ sau khi xoá", async () => {
    await renderQueue([...many("E0", 2), ...many("E9", 3), ...many("E3", 4)]);
    fireEvent.click(tabOf(2));
    typeSearch("e3");
    expect(tabAll().getAttribute("aria-selected")).toBe("true");
    expect(shownPriorities()).toStrictEqual([6]);
    typeSearch("");
    expect(tabOf(2).getAttribute("aria-selected")).toBe("true");
    expect(shownPriorities()).toStrictEqual([2]);
    typeSearch("ly do");
    expect(tabOf(2).getAttribute("aria-selected")).toBe("true");
    fireEvent.click(tabOf(4));
    expect(shownPriorities()).toStrictEqual([4]);
    typeSearch("");
    expect(tabOf(4).getAttribute("aria-selected")).toBe("true");
    expect(shownPriorities()).toStrictEqual([4]);
  });
});

// ------------------------------------------------------------------------------------------------ t104

describe("t104: dọn trạng thái theo danh sách CHƯA lọc (P11b) — nhóm hết ca rồi có ca mới thì MỞ; gõ tìm không làm bung nhóm", () => {
  it("An ninh thu gọn → hết ca → ca mới cùng hạng → nhóm MỞ, ca mới hiện; trang của nhóm hết ca cũng được dọn", async () => {
    const e3 = many("E3", 25);
    const { live, tick } = await renderQueue([esc("E0"), ...e3]);
    fireEvent.click(toggleOf(2));
    fireEvent.click(pageButton(6, "Cuối"));
    await tick([]);
    expect(screen.getByText("Không có ca nào đang chờ")).toBeTruthy();
    const fresh = esc("E0");
    await tick([fresh, ...e3]);
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("true");
    expect(idsIn(groupOf(2))).toStrictEqual([fresh.escalation_id]);
    expect(pagerText(6)).toBe("Ca 1–10 / 25 · trang 1/3");
    expectQuiet(live);
  });

  it("đang tìm (nhóm thu gọn không có ca khớp) + tự tải lại → xoá ô tìm → nhóm VẪN thu gọn", async () => {
    const e0 = many("E0", 2);
    const e3 = many("E3", 4);
    const { tick } = await renderQueue([...e0, ...e3]);
    fireEvent.click(toggleOf(2));
    typeSearch("e3");
    expect(groupOf(2)).toBeNull();
    await tick([...e0, ...e3, esc("E3")]);
    typeSearch("");
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("false");
    expect(idsIn(groupOf(2))).toStrictEqual([]);
    expect(countOf(2)).toBe("· 2 ca");
  });
});

// ------------------------------------------------------------------------------------------------ t105

describe("t105: khối nhóm khoá theo priority (P11d) — nhóm phía trước biến mất / xuất hiện không dựng lại khối sau", () => {
  it("nút thu gọn của nhóm Thường giữ nguyên nút DOM và tiêu điểm qua 2 lần tự tải lại", async () => {
    const e0 = esc("E0");
    const e3 = many("E3", 3);
    const { tick } = await renderQueue([e0, ...e3]);
    const button = toggleOf(6);
    button.focus();
    expect(document.activeElement).toBe(button);
    const section = groupOf(6)!;
    await tick(e3);
    expect(toggleOf(6)).toBe(button);
    expect(button.isConnected).toBe(true);
    expect(document.activeElement).toBe(button);
    expect(groupOf(6)).toBe(section);
    expect(section.getAttribute("aria-labelledby")).toBe(section.querySelector("h2")!.id);
    await tick([esc("E0"), ...e3]);
    expect(toggleOf(6)).toBe(button);
    expect(document.activeElement).toBe(button);
    const headingIds = [...document.querySelectorAll('[data-testid="queue-group"] h2')].map((h) => h.id);
    expect(new Set(headingIds).size).toBe(headingIds.length);
  });
});

// ================================================================================================ Q-fe-43 (t107–t108)
// Ca MỚI rơi vào nhóm đang thu gọn / bị thẻ khác che → một dòng `queue-missed` (con số là tín hiệu duy nhất về ca mới).

// ------------------------------------------------------------------------------------------------ t107

describe("t107: isHidden / trackMissed — ca mới khuất theo trạng thái ĐÃ LƯU; cộng dồn; hiện ra / rời hàng đợi → bỏ hẳn", () => {
  const view = (over: Partial<QueueView> = {}): QueueView => ({ ...EMPTY_VIEW, ...over });

  it("isHidden: thu gọn, hoặc đang chọn thẻ nhóm khác; trang sau không phải 'khuất'", () => {
    expect(isHidden(2, EMPTY_VIEW)).toBe(false);
    expect(isHidden(2, view({ collapsed: new Set([2]) }))).toBe(true);
    expect(isHidden(2, view({ active: 6 }))).toBe(true);
    expect(isHidden(6, view({ active: 6 }))).toBe(false);
    expect(isHidden(6, view({ pages: { 6: 3 } }))).toBe(false);
  });

  const before = [esc("E0"), ...many("E3", 3)];
  const fresh = esc("E0");
  const after = [before[0]!, fresh, ...before.slice(1)];

  it("lần tải đầu (before = null) → không ca nào là mới, kể cả khi nhóm đang khuất", () => {
    expect(trackMissed(NO_IDS, null, after, view({ collapsed: new Set([2]) }))).toBe(NO_IDS);
    expect(trackMissed(NO_IDS, null, after, view({ active: 6 }))).toBe(NO_IDS);
  });

  it("ca mới (so theo id, không theo tham chiếu) vào nhóm khuất → thêm; vào nhóm đang hiện → không; dữ liệu y hệt → đúng object cũ", () => {
    expect([...trackMissed(NO_IDS, before, after, view({ collapsed: new Set([2]) }))]).toStrictEqual([fresh.escalation_id]);
    expect([...trackMissed(NO_IDS, before, after, view({ active: 6 }))]).toStrictEqual([fresh.escalation_id]);
    expect(trackMissed(NO_IDS, before, after, view({ collapsed: new Set([6]) }))).toBe(NO_IDS);
    expect(trackMissed(NO_IDS, before, after, EMPTY_VIEW)).toBe(NO_IDS);
    const copies = before.map((i) => ({ ...i, assigned_to: "long.nh" })); // cùng id, object mới
    expect(trackMissed(NO_IDS, before, copies, view({ collapsed: new Set([2, 6]) }))).toBe(NO_IDS);
  });

  it("cộng dồn; ca đã báo mà nay hiện ra hoặc rời hàng đợi → bỏ; không đổi → đúng object cũ", () => {
    const hidden = view({ collapsed: new Set([2]) });
    const one = trackMissed(NO_IDS, before, after, hidden);
    const second = esc("E0");
    const two = trackMissed(one, after, [...after, second], hidden);
    expect([...two].sort()).toStrictEqual([fresh.escalation_id, second.escalation_id].sort());
    expect(trackMissed(two, [...after, second], [...after, second], hidden)).toBe(two);
    expect(trackMissed(two, [...after, second], [...after, second], EMPTY_VIEW)).toStrictEqual(new Set());
    expect([...trackMissed(two, [...after, second], after, hidden)]).toStrictEqual([fresh.escalation_id]);
  });
});

// ------------------------------------------------------------------------------------------------ t108

describe("t108: dòng 'Có N ca mới ở nhóm đang ẩn hoặc thu gọn' — báo, cộng dồn, nút hiện nhóm, tự mất khi ca hiện ra / rời hàng đợi", () => {
  const missedLine = () => screen.queryByTestId("queue-missed");
  const missedText = () => missedLine()?.querySelector("span")?.textContent ?? null;
  const revealButton = () => within(missedLine()!).getByRole("button", { name: "Hiện các nhóm này" });

  it("lần tải đầu không báo; tải lại dữ liệu y hệt / cùng id khác nội dung không báo", async () => {
    const server = [...many("E0", 2), ...many("E3", 3)];
    const { tick } = await renderQueue(server);
    expect(missedLine()).toBeNull();
    fireEvent.click(toggleOf(2));
    fireEvent.click(tabOf(6));
    await tick(server.map((i) => ({ ...i })));
    expect(missedLine()).toBeNull();
    await tick(server.map((i) => ({ ...i, assigned_to: "long.nh" })));
    expect(missedLine()).toBeNull();
  });

  it("ca mới vào nhóm ĐANG THU GỌN → dòng role=status đúng chữ; vào nhóm đang hiện (kể cả trang sau) → không", async () => {
    const e0 = many("E0", 2);
    const e3 = many("E3", 12);
    const { live, tick } = await renderQueue([...e0, ...e3]);
    fireEvent.click(toggleOf(2));
    const newE3 = esc("E3"); // nhóm Thường đang mở, ca mới rơi vào trang 2 → KHÔNG báo
    await tick([...e0, ...e3, newE3]);
    expect(missedLine()).toBeNull();
    const newE0 = esc("E0");
    await tick([...e0, newE0, ...e3, newE3]);
    expect(missedLine()!.getAttribute("role")).toBe("status");
    expect(missedText()).toBe("Có 1 ca mới ở nhóm đang ẩn hoặc thu gọn: An ninh (1)");
    expect(revealButton()).toBeTruthy();
    expect(countOf(2)).toBe("· 3 ca");
    expectQuiet(live);
  });

  it("ca mới vào nhóm khác thẻ đang chọn → báo; cộng dồn 2 lượt, nhiều nhóm theo thứ tự server; hiện cả khi đang tìm (kể cả 0 ca khớp)", async () => {
    const e0 = many("E0", 2);
    const e9 = many("E9", 2);
    const e3 = many("E3", 3);
    const { tick } = await renderQueue([...e0, ...e9, ...e3]);
    fireEvent.click(tabOf(6));
    const a = esc("E9");
    await tick([...e0, ...e9, a, ...e3]);
    expect(missedText()).toBe("Có 1 ca mới ở nhóm đang ẩn hoặc thu gọn: Lỗi hệ thống (1)");
    typeSearch("e3");
    const b = esc("E0");
    const c = esc("E0");
    await tick([...e0, b, c, ...e9, a, ...e3]);
    expect(missedText()).toBe("Có 3 ca mới ở nhóm đang ẩn hoặc thu gọn: An ninh (2), Lỗi hệ thống (1)");
    typeSearch("khong co ca nay");
    expect(screen.getByText(NO_MATCH_TEXT)).toBeTruthy();
    expect(missedText()).toBe("Có 3 ca mới ở nhóm đang ẩn hoặc thu gọn: An ninh (2), Lỗi hệ thống (1)");
  });

  it("bấm 'Hiện các nhóm này' → thẻ 'Tất cả' + mở các nhóm đó (trạng thái đã lưu) → dòng mất; ẩn lại không báo lại", async () => {
    const e0 = many("E0", 2);
    const e9 = many("E9", 2);
    const e3 = many("E3", 3);
    const { live, tick } = await renderQueue([...e0, ...e9, ...e3]);
    fireEvent.click(toggleOf(2));
    fireEvent.click(tabOf(6));
    const a = esc("E0");
    const b = esc("E9");
    await tick([...e0, a, ...e9, b, ...e3]);
    expect(missedText()).toBe("Có 2 ca mới ở nhóm đang ẩn hoặc thu gọn: An ninh (1), Lỗi hệ thống (1)");
    fireEvent.click(revealButton());
    expect(missedLine()).toBeNull();
    expect(tabAll().getAttribute("aria-selected")).toBe("true");
    expect(shownPriorities()).toStrictEqual([2, 4, 6]);
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("true");
    expect(idsIn(groupOf(2))).toContain(a.escalation_id);
    expect(idsIn(groupOf(4))).toContain(b.escalation_id);
    fireEvent.click(toggleOf(2));
    fireEvent.click(tabOf(6));
    expect(missedLine()).toBeNull();
    await tick([...e0, a, ...e9, b, ...e3]);
    expect(missedLine()).toBeNull();
    expectQuiet(live);
  });

  it("tự mở nhóm làm ca hiện ra → bớt khỏi dòng (còn nhóm khác thì vẫn báo nhóm đó); ca rời hàng đợi → dòng mất", async () => {
    const e0 = many("E0", 2);
    const e3 = many("E3", 3);
    const { tick } = await renderQueue([...e0, ...e3]);
    fireEvent.click(toggleOf(2));
    fireEvent.click(toggleOf(6));
    const a = esc("E0");
    const b = esc("E3");
    await tick([...e0, a, ...e3, b]);
    expect(missedText()).toBe("Có 2 ca mới ở nhóm đang ẩn hoặc thu gọn: An ninh (1), Thường (1)");
    fireEvent.click(toggleOf(2));
    expect(missedText()).toBe("Có 1 ca mới ở nhóm đang ẩn hoặc thu gọn: Thường (1)");
    fireEvent.click(toggleOf(2)); // thu gọn lại An ninh → không báo lại ca a
    expect(missedText()).toBe("Có 1 ca mới ở nhóm đang ẩn hoặc thu gọn: Thường (1)");
    await tick([...e0, a, ...e3]); // ca b rời hàng đợi
    expect(missedLine()).toBeNull();
  });

  it("chế độ tìm không quyết 'khuất': nhóm mở trong kết quả tìm nhưng thu gọn ở trạng thái đã lưu → vẫn báo; thu gọn chỉ trong chế độ tìm → không báo", async () => {
    const e0 = many("E0", 2);
    const e3 = many("E3", 3);
    const { tick } = await renderQueue([...e0, ...e3]);
    fireEvent.click(toggleOf(2)); // đã lưu: An ninh thu gọn
    typeSearch("ly do"); // chế độ tìm: mọi nhóm mở
    expect(toggleOf(2).getAttribute("aria-expanded")).toBe("true");
    fireEvent.click(toggleOf(6)); // chỉ thu gọn trong chế độ tìm
    const a = esc("E0");
    const b = esc("E3");
    await tick([...e0, a, ...e3, b]);
    expect(missedText()).toBe("Có 1 ca mới ở nhóm đang ẩn hoặc thu gọn: An ninh (1)");
  });
});
