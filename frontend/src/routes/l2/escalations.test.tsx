// F3 — màn L2 (hàng đợi escalate, chi tiết, đóng ca minh hoạ). Không gọi backend: fetch giả trả đúng dạng của
// backend/app/api/escalations.py (list[dict], đã sắp theo priority → created_at → escalation_id) và tickets.py.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorMessage, ApiError } from "../../api/errors.ts";
import { CLOSE_AVAILABLE, closeEscalation } from "../../api/escalations.ts";
import { api } from "../../api/http.ts";
import type { EscalationCloseIn, EscalationQueueItem, Me, TicketView } from "../../api/types.ts";
import { Sidebar } from "../../components/Sidebar.tsx";
import { closeOutcome } from "../../mocks/handlers/escalation-close.ts";
import { CloseForm } from "./CloseForm.tsx";
import { EscalationDetailRoute } from "./EscalationDetail.tsx";
import { EscalationQueue } from "./EscalationQueue.tsx";
import { DENY_BANNER, EMPTY_NOTE, GONE_TEXT, groupQueue, handoffRows, OVERFLOW_TEXT, waitingText } from "./queue.ts";

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
      if (method === "GET" && url.startsWith("/api/escalations/queue")) return json(200, queue);
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

function renderAt(path: string, { me, closeAvailable }: { me?: Me; closeAvailable?: boolean } = {}) {
  const client = new QueryClient();
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        {me ? <Sidebar me={me} onSignOut={async () => true} /> : null}
        <Routes>
          <Route path="/escalations" element={<EscalationQueue />} />
          <Route path="/escalations/:escalationId" element={<EscalationDetailRoute closeAvailable={closeAvailable} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const radio = (name: RegExp) => screen.getByRole("radio", { name });
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

  it("màn hàng đợi: gọi limit=200; 'Đang hiện N ca'; nhóm + dòng đúng thứ tự server; E3 có huy hiệu 'Cần bổ sung KB'", async () => {
    const calls = stubApi(server);
    renderAt("/escalations");
    await screen.findByText("Lỗi hệ thống / Hạ tầng");
    const groups = document.querySelectorAll('[data-testid="queue-group"]');
    expect([...groups].map((g) => g.querySelector("h2")?.textContent)).toStrictEqual(["An ninh", "Lỗi hệ thống / Hạ tầng", "Thường"]);
    const rows = [...document.querySelectorAll<HTMLElement>('[data-testid="queue-row"]')];
    expect(rows.map((r) => Number(r.dataset.escalationId))).toStrictEqual(server.map((i) => i.escalation_id));
    const e3 = rows.find((r) => r.dataset.exitCode === "E3")!;
    expect(within(e3).getByText("Cần bổ sung KB")).toBeTruthy();
    expect(within(rows[0]!).queryByText("Cần bổ sung KB")).toBeNull();
    expect(screen.getByTestId("queue-count").textContent).toBe("Đang hiện 5 ca");
    expect(calls.filter((c) => c.url.startsWith("/api/escalations/queue")).map((c) => c.url)).toStrictEqual([
      "/api/escalations/queue?limit=200",
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
    expect(badge.textContent).toBe("E5 — không thực hiện lại");
    expect(badge.closest<HTMLElement>('[data-testid="queue-row"]')?.dataset.exitCode).toBe("E5");
  });
});

// ------------------------------------------------------------------------------------------------ t29

describe("t29: ghi chú bàn giao thiếu khoá / rỗng / có HTML → '(không có)' hoặc chữ thô", () => {
  it("handoffRows: đúng 4 khối, đúng nhãn, đúng thứ tự; hỏng → null", () => {
    expect(handoffRows(null).map((r) => [r.label, r.text])).toStrictEqual([
      ["Yêu cầu (đã che)", null],
      ["Agent đã làm", null],
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
      "Agent đã làm",
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
    expect(banner.textContent).toBe("Ca E5 — không thực hiện lại hành động. Chỉ xác nhận từ chối hoặc mở ticket mới.");
    const completed = radio(COMPLETED);
    expect(completed.getAttribute("aria-disabled")).toBe("true");
    expect(completed.textContent).toContain("Không dùng với ca E5");
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
    expect(radio(COMPLETED).textContent).toContain("E6");
  });
});

// ------------------------------------------------------------------------------------------------ t31

describe("t31: ghi chú rỗng / chỉ khoảng trắng → không gửi", () => {
  it("chưa chọn kết quả, ghi chú rỗng, chỉ khoảng trắng → không gọi; hợp lệ → gọi đúng 1 lần, ghi chú đã cắt", async () => {
    const submit = vi.fn<(id: number, body: EscalationCloseIn) => Promise<void>>(async () => {});
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    render(<CloseForm item={esc("E3", { escalation_id: 31 })} available onSubmit={submit} />);
    const send = screen.getByRole("button", { name: "Đóng escalation" });
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
    await screen.findByText("Đã ghi nhận (minh hoạ)");
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
    render(<CloseForm item={esc("E3", { escalation_id: 32 })} available onSubmit={viaClient} />);
    fireEvent.click(radio(COMPLETED));
    const note = screen.getByLabelText("Ghi chú đóng") as HTMLTextAreaElement;
    fireEvent.change(note, { target: { value: "Đã cấp lại quyền." } });
    fireEvent.click(screen.getByRole("button", { name: "Đóng escalation" }));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(errorMessage(new ApiError(422, "deny_case_cannot_complete")));
    expect(alert.textContent).toBe("Không đóng được: ca E5 không được chọn “Đã hoàn tất”. Chỉ xác nhận từ chối hoặc mở ticket mới.");
    expect(calls.filter((c) => c.method === "POST")).toHaveLength(1);
    expect(JSON.parse(calls.find((c) => c.method === "POST")!.body!)).toStrictEqual({
      close_result: "completed",
      note: "Đã cấp lại quyền.",
    });
    expect(radio(COMPLETED).getAttribute("aria-checked")).toBe("true");
    expect(note.value).toBe("Đã cấp lại quyền.");
    expect(screen.queryByText("Đã ghi nhận (minh hoạ)")).toBeNull();
    expect((screen.getByRole("button", { name: "Đóng escalation" }) as HTMLButtonElement).disabled).toBe(false);
  });
});

// ------------------------------------------------------------------------------------------------ t33

describe("t33: MSW tắt → nút gửi khoá, 0 lời gọi /close", () => {
  it("mặc định (vitest: không DEV-mock) → khoá + 'Đóng ca có ở Phase 7'; bấm / submit form / gọi thẳng API đều không tới /close", async () => {
    expect(CLOSE_AVAILABLE).toBe(false);
    const calls = stubApi([esc("E3", { escalation_id: 33 })], () => json(202, {}));
    renderAt("/escalations/33");
    await screen.findByText("Ghi chú bàn giao");
    const send = screen.getByRole("button", { name: "Đóng escalation" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    expect(screen.getByTestId("close-unavailable").textContent).toBe("Đóng ca có ở Phase 7");
    fireEvent.click(radio(DENIAL));
    fireEvent.change(screen.getByLabelText("Ghi chú đóng"), { target: { value: "ghi chú" } });
    fireEvent.click(send);
    fireEvent.submit(send.closest("form")!);
    await expect(closeEscalation(33, { close_result: "confirmed_denial", note: "x" })).rejects.toThrow("Phase 7");
    await new Promise((r) => setTimeout(r, 20));
    expect(calls.filter((c) => c.url.includes("/close"))).toHaveLength(0);
    expect(screen.queryByText("Đã ghi nhận (minh hoạ)")).toBeNull();
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
    ["hàng đợi (L2)", "/escalations", L2, false],
    ["hàng đợi (L1 — thanh bên có mục duyệt dạng link)", "/escalations", L1, false],
    ["chi tiết ca deny", "/escalations/34", L2, false],
    ["chi tiết ca E3, đóng ca bật (dev:mock)", "/escalations/35", L2, true],
    ["ca không còn", "/escalations/999", L1, false],
  ])("%s", async (_name, path, me, closeAvailable) => {
    stubApi([esc("E5", { escalation_id: 34 }), esc("E3", { escalation_id: 35 })]);
    renderAt(path, { me, closeAvailable });
    await waitFor(() => expect(document.querySelector("h1")).toBeTruthy());
    await waitFor(() => expect(screen.queryByText(/^Đang tải/)).toBeNull());
    const texts = buttonTexts();
    expect(texts.length).toBeGreaterThan(0); // có quét thật (ít nhất nút đăng xuất / tải lại)
    expect(texts.filter((t) => APPROVE.test(t))).toStrictEqual([]);
  });
});

// ------------------------------------------------------------------------------------------------ t35

describe("t35: tải lại chi tiết khi ca không còn trong hàng đợi", () => {
  it.each([["999"], ["abc"]])("/escalations/%s → gọi lại queue limit=200 → 'Ca đã đóng…'", async (id) => {
    const calls = stubApi([esc("E3", { escalation_id: 1 })]);
    renderAt(`/escalations/${id}`);
    expect(await screen.findByRole("heading", { name: GONE_TEXT })).toBeTruthy();
    expect(GONE_TEXT).toBe("Ca đã đóng hoặc không còn trong hàng đợi");
    if (id === "999") expect(calls.map((c) => c.url)).toContain("/api/escalations/queue?limit=200");
    expect(calls.some((c) => c.url.startsWith("/api/tickets/"))).toBe(false);
    expect(screen.getByRole("link", { name: "‹ Hàng đợi escalate" }).getAttribute("href")).toBe("/escalations");
  });

  it("hàng đợi đủ 200 ca mà không có id → báo quá 200 ca (không khẳng định 'đã đóng'); màn hàng đợi cũng báo", async () => {
    const full = Array.from({ length: 200 }, (_, i) => esc("E3", { escalation_id: 1000 + i }));
    stubApi(full);
    renderAt("/escalations/999");
    expect(await screen.findByRole("heading", { name: OVERFLOW_TEXT })).toBeTruthy();
    expect(OVERFLOW_TEXT).toBe("Không tìm thấy ca trong 200 ca đầu của hàng đợi");
    expect(screen.getByText(/Hàng đợi đang quá 200 ca/)).toBeTruthy();
    expect(screen.queryByRole("heading", { name: GONE_TEXT })).toBeNull();
    cleanup();
    stubApi(full);
    renderAt("/escalations");
    expect((await screen.findByTestId("queue-overflow")).textContent).toContain("Hàng đợi đang quá 200 ca");
    expect(screen.getByTestId("queue-count").textContent).toBe("Đang hiện 200 ca");
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

describe("t36: handler MSW /close — kết quả theo ca thật trong hàng đợi", () => {
  const deny = esc("E5");
  const normal = esc("E3");
  it.each([
    ["deny + completed → 422 deny_case_cannot_complete", { close_result: "completed", note: "x" }, deny, 422, { detail: "deny_case_cannot_complete" }],
    ["deny + confirmed_denial → 202", { close_result: "confirmed_denial", note: "x" }, deny, 202, undefined],
    ["thường + completed → 202", { close_result: "completed", note: "x" }, normal, 202, undefined],
    ["không còn trong hàng đợi → 404", { close_result: "completed", note: "x" }, undefined, 404, { detail: "escalation_not_found" }],
    ["ghi chú chỉ khoảng trắng → 422 body.note", { close_result: "reopened_as_new", note: "  " }, normal, 422, { error: "invalid_request", fields: ["body.note"] }],
    ["thừa khoá → 422", { close_result: "completed", note: "x", force: true }, normal, 422, { error: "invalid_request", fields: ["body.force"] }],
  ])("%s", (_name, body, item, status, expected) => {
    const outcome = closeOutcome(body, item);
    expect(outcome.status).toBe(status);
    if (expected) expect(outcome.body).toStrictEqual(expected);
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
