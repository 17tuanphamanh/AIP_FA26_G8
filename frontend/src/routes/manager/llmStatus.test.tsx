// I1 — trang Trạng thái LLM (chỉ đọc, Trưởng BP IT). Không gọi backend: fetch giả trả đúng hình dạng route thật
// `GET /api/admin/llm-status` (backend/app/api/llm_status.py, `LlmStatus`).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseLlmStatus } from "../../api/llmStatus.ts";
import { ApiError } from "../../api/errors.ts";
import type { LlmStatus as Status, Me } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { hasPerm, STAFF_NAV } from "../../auth/permissions.ts";
import { RequirePerm } from "../../auth/RequireAuth.tsx";
import { AVG_DEFINITION_TEXT, COST_UPPER_BOUND_TEXT, LlmStatus } from "./LlmStatus.tsx";
import { MONITOR_DOWN_TEXT } from "./metrics.ts";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.unstubAllGlobals();
});

const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
// backend/app/auth/permissions.py (I1: `llm_status:read` chỉ manager).
const MGR: Me = {
  user_id: "it_mgr01",
  role: "manager",
  permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "policy:read", "policy:edit", "dashboard:read:all", "audit:read:all", "kb:edit", "alert:read", "llm_status:read"],
};
const L1: Me = {
  user_id: "l1_01",
  role: "l1",
  permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "escalation:handle", "dashboard:read:own", "audit:read:own"],
};

const STATUS: Status = {
  as_of: "2030-06-01T05:00:00Z", // 12:00 giờ VN
  backend: "scripted",
  models: { fast: "scripted", strong: "scripted" },
  api_key_configured: false,
  spend: { total_usd: 9.5, cap_usd: 38, percent: 25, warn_percent: 80, status: "ok" },
  usage: { calls_total: 420, calls_24h: 37, tickets_with_calls: 20, avg_cost_per_ticket_usd: 0.475 },
  kb: { alias: "kb_current", collection: "kb_v12", status: "ready" },
};
const status = (over: Partial<Status> = {}): Status => ({ ...STATUS, ...over });

const json = (code: number, body: unknown) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
type Call = { method: string; url: string };

function stub(respond: () => Response): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push({ method: init.method ?? "GET", url });
      return respond();
    }),
  );
  return calls;
}

const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });
const ITEM = STAFF_NAV.find((i) => i.to === "/llm-status")!;

function renderPage(me: Me = MGR) {
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(me)}>
        <MemoryRouter initialEntries={["/llm-status"]}>
          <Routes>
            <Route
              path="/llm-status"
              element={
                <RequirePerm perm={ITEM.perm}>
                  <LlmStatus />
                </RequirePerm>
              }
            />
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}

const text = (id: string) => screen.getByTestId(id).textContent ?? "";
const NBSP = /[\u00a0\u202f]/g;
const flat = (value: string) => value.replace(NBSP, " ");

describe("I1: nội dung trang", () => {
  it("hiện backend, 2 model, khoá, chi tiêu/trần/tỉ lệ, mức dùng, trung bình/ticket, KB, mốc giờ VN", async () => {
    const calls = stub(() => json(200, STATUS));
    renderPage();
    await screen.findByTestId("llm-backend");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Trạng thái LLM");
    expect(text("llm-backend-state")).toContain("Giả lập (scripted)");
    expect(text("llm-model-fast")).toBe("scripted");
    expect(text("llm-model-strong")).toBe("scripted");
    expect(text("llm-key-state")).toContain("chưa cấu hình");
    expect(flat(text("llm-spend-total"))).toBe("9,5 / 38 USD");
    expect(flat(text("llm-spend-percent"))).toBe("Đã dùng 25 % trần");
    expect(text("llm-spend-state")).toContain("Trong ngưỡng");
    expect(flat(text("llm-calls-24h"))).toBe("37");
    expect(flat(text("llm-calls-total"))).toBe("420");
    expect(flat(text("llm-tickets"))).toBe("20");
    expect(flat(text("llm-avg-cost"))).toBe("0,475 USD");
    expect(text("llm-kb-version")).toBe("kb_v12");
    expect(text("llm-kb-state")).toContain("Đã nạp");
    expect(text("llm-as-of")).toContain("12:00");
    expect(calls).toStrictEqual([{ method: "GET", url: "/api/admin/llm-status" }]); // một GET duy nhất
  });

  it("dòng phụ dưới số chi tiêu: cận trên theo bảng giá giờ cao điểm; có định nghĩa trung bình theo ticket", async () => {
    stub(() => json(200, STATUS));
    renderPage();
    await screen.findByTestId("llm-spend");
    expect(COST_UPPER_BOUND_TEXT).toBe("Chi phí tính theo bảng giá giờ cao điểm trong cấu hình — là cận trên, có thể cao hơn hoá đơn nhà cung cấp.");
    expect(text("llm-spend-note")).toBe(COST_UPPER_BOUND_TEXT);
    expect(within(screen.getByTestId("llm-spend")).getByTestId("llm-spend-note")).toBeTruthy(); // nằm trong thẻ chi tiêu
    expect(text("llm-avg-definition")).toBe(AVG_DEFINITION_TEXT);
  });

  it("chỉ đọc: không nút, không ô nhập, không form, không link sửa", async () => {
    stub(() => json(200, STATUS));
    renderPage();
    await screen.findByTestId("llm-backend");
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryAllByRole("textbox")).toHaveLength(0);
    expect(screen.queryAllByRole("combobox")).toHaveLength(0);
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    expect(document.querySelector("form, input, select, textarea, button, a")).toBeNull();
  });

  it.each([
    ["ok", "bg-done", "Trong ngưỡng"],
    ["warn", "bg-fpt-orange", "Từ ngưỡng cảnh báo (80 % trần) trở lên"],
    ["over", "bg-danger", "Đã chạm trần"],
  ] as const)("trạng thái chi tiêu %s = chấm %s + chữ xám", async (spendStatus, dot, label) => {
    stub(() => json(200, status({ spend: { ...STATUS.spend, status: spendStatus, percent: spendStatus === "over" ? 104.2 : 90 } })));
    renderPage();
    await screen.findByTestId("llm-spend-state");
    const state = screen.getByTestId("llm-spend-state");
    expect(flat(state.textContent ?? "")).toContain(label);
    expect(state.className).toContain("text-ink-2");
    expect(state.querySelector("span[aria-hidden='true']")?.className).toContain(dot);
  });

  it("ngưỡng cảnh báo hiện theo warn_percent của server (không cứng 80 %)", async () => {
    stub(() => json(200, status({ spend: { ...STATUS.spend, status: "warn", warn_percent: 50, percent: 60 } })));
    renderPage();
    await screen.findByTestId("llm-spend-state");
    expect(flat(text("llm-spend-state"))).toContain("50 % trần");
    expect(text("llm-spend-state")).not.toContain("80");
  });

  it("vượt trần: tỉ lệ > 100 % hiện nguyên, không cắt", async () => {
    stub(() => json(200, status({ spend: { total_usd: 40, cap_usd: 38, percent: 105.26, warn_percent: 80, status: "over" } })));
    renderPage();
    await screen.findByTestId("llm-spend-percent");
    expect(flat(text("llm-spend-percent"))).toBe("Đã dùng 105,3 % trần");
  });

  it("backend real + khoá đã cấu hình: chỉ chữ 'đã cấu hình', chấm xanh; model chưa đặt → 'chưa cấu hình'", async () => {
    stub(() => json(200, status({ backend: "real", api_key_configured: true, models: { fast: "deepseek-flash", strong: null } })));
    renderPage();
    await screen.findByTestId("llm-backend");
    expect(text("llm-backend-state")).toContain("Thật (real)");
    expect(text("llm-key-state")).toBe("Khoá API: đã cấu hình");
    expect(screen.getByTestId("llm-key-state").querySelector("span")?.className).toContain("bg-done");
    expect(text("llm-model-fast")).toBe("deepseek-flash");
    expect(text("llm-model-strong")).toBe("chưa cấu hình");
  });

  it("trường lạ trong thân (vd khoá giả) KHÔNG bao giờ được in ra trang", async () => {
    stub(() => json(200, { ...STATUS, api_key: "sk-LEAK-should-never-render", api_key_hint: "sk-LE" }));
    renderPage();
    await screen.findByTestId("llm-backend");
    expect(document.body.textContent).not.toContain("sk-LE");
  });

  it("chưa có ticket nào → trung bình hiện '—', không bịa 0", async () => {
    stub(() => json(200, status({ usage: { calls_total: 0, calls_24h: 0, tickets_with_calls: 0, avg_cost_per_ticket_usd: null } })));
    renderPage();
    await screen.findByTestId("llm-avg-cost");
    expect(text("llm-avg-cost")).toBe("— (chưa có ticket)");
    expect(flat(text("llm-calls-total"))).toBe("0");
  });

  it.each([
    ["ready", "kb_v12", "Đã nạp", "bg-done"],
    ["missing", null, "Chưa có bản KB nào đang dùng", "bg-fpt-orange"],
    ["unknown", null, "Không kiểm tra được lúc này", "bg-ink-3"],
  ] as const)("KB %s", async (kbStatus, collection, label, dot) => {
    stub(() => json(200, status({ kb: { alias: "kb_current", collection, status: kbStatus } })));
    renderPage();
    await screen.findByTestId("llm-kb-state");
    expect(text("llm-kb-state")).toContain(label);
    expect(screen.getByTestId("llm-kb-state").querySelector("span")?.className).toContain(dot);
    expect(text("llm-kb-version")).toBe(collection ?? "chưa cấu hình");
  });
});

describe("I1: lỗi và quyền", () => {
  it("503 monitor_unavailable → 'Số liệu tạm thời không có', không số nào", async () => {
    stub(() => json(503, { detail: "monitor_unavailable" }));
    renderPage();
    const error = await screen.findByTestId("load-error");
    expect(error.textContent).toContain(MONITOR_DOWN_TEXT);
    expect(screen.queryByTestId("llm-spend")).toBeNull();
    expect(document.body.textContent).not.toMatch(/USD/);
  });

  it("404 'Not Found' (backend cũ chưa có route) → bảng 'chưa có', không khối lỗi đỏ", async () => {
    stub(() => json(404, { detail: "Not Found" }));
    renderPage();
    expect(await screen.findByTestId("llm-status-missing")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("403 từ backend → trang không có quyền", async () => {
    stub(() => json(403, { detail: "forbidden" }));
    renderPage();
    expect(await screen.findByRole("heading", { name: "Bạn không có quyền xem trang này" })).toBeTruthy();
  });

  it("thân sai hình dạng → lỗi, không dựng màn từ dữ liệu không rõ", async () => {
    stub(() => json(200, { ...STATUS, spend: { ...STATUS.spend, status: "great" } }));
    renderPage();
    expect(await screen.findByTestId("load-error")).toBeTruthy();
    expect(screen.queryByTestId("llm-spend")).toBeNull();
  });

  it("L1 (thiếu llm_status:read) → trang 403 TRƯỚC khi gọi API", async () => {
    const calls = stub(() => json(200, STATUS));
    renderPage(L1);
    expect(await screen.findByRole("heading", { name: "Bạn không có quyền xem trang này" })).toBeTruthy();
    expect(calls).toHaveLength(0);
  });
});

describe("I1: menu và kiểu", () => {
  it("mục 'Trạng thái LLM' → /llm-status, quyền llm_status:read; chỉ manager có", () => {
    expect(ITEM).toMatchObject({ to: "/llm-status", label: "Trạng thái LLM", perm: "llm_status:read" });
    expect(hasPerm(MGR, ITEM.perm)).toBe(true);
    expect(hasPerm(L1, ITEM.perm)).toBe(false);
  });

  it("parseLlmStatus: nhận thân đúng; từ chối sai kiểu / thiếu khoá bằng 502", () => {
    expect(parseLlmStatus(STATUS)).toStrictEqual(STATUS);
    const bad: unknown[] = [
      null,
      [],
      { ...STATUS, api_key_configured: "yes" },
      { ...STATUS, backend: "mock" },
      { ...STATUS, kb: { ...STATUS.kb, status: "ok" } },
      { ...STATUS, usage: { ...STATUS.usage, calls_24h: "37" } },
      { ...STATUS, spend: { ...STATUS.spend, percent: Number.NaN } },
      { ...STATUS, models: { fast: 1, strong: null } },
      Object.fromEntries(Object.entries(STATUS).filter(([key]) => key !== "spend")),
    ];
    for (const body of bad) {
      expect(() => parseLlmStatus(body), JSON.stringify(body)).toThrow(ApiError);
    }
  });

  it("chữ ≥ 16 px: trang chỉ dùng cỡ body/heading/title — không text-secondary / text-label", () => {
    const sources = import.meta.glob("./LlmStatus.tsx", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const source = Object.values(sources)[0] ?? "";
    expect(source.length).toBeGreaterThan(0);
    expect(source).not.toMatch(/text-secondary|text-label/);
  });
});
