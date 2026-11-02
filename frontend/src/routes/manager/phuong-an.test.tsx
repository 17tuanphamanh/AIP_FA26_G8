// N-PA P2 + P3 — Trưởng BP IT: khối "Cách xử lý của hệ thống" (D-67) ở trang Chính sách và tab "So sánh phương án" ở Tổng
// quan. Không gọi backend: fetch giả trả đúng hình dạng hợp đồng chốt ĐP 26/10 17:30 (route CHƯA CÓ ở backend).
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createClient } from "../../api/client.ts";
import type { Me, StrategyChange, StrategyView } from "../../api/types.ts";
import { AuthProvider } from "../../auth/AuthProvider.tsx";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { useAuth } from "../../auth/useAuth.ts";
import { FlashNotice } from "../../components/FlashNotice.tsx";
import { DEMO_UPDATED_AT, DEMO_VERSION, POLICY_DEMO } from "../../mocks/fixtures/policy.ts";
import { buildStrategies, METRIC_KEYS } from "../../mocks/fixtures/strategy.ts";
import { cellText, COMPARE_NOTE, SIM_BAND } from "./compare.ts";
import { DashboardPage } from "./DashboardPage.tsx";
import { MONITOR_DOWN_TEXT } from "./metrics.ts";
import { PolicyEditor } from "./PolicyEditor.tsx";
import { METRIC_LABEL } from "./strategyLabels.ts";
import {
  EVAL_MODE_TEXT,
  HISTORY_TRUNCATED_TEXT,
  NOT_SELECTABLE_TEXT,
  READONLY_TEXT,
  SAME_AS_CURRENT_TEXT,
  STRATEGY_MISSING_TEXT,
  STRATEGY_OPTIONS,
  UNCALIBRATED_TEXT,
} from "./strategyText.ts";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.unstubAllGlobals();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const MGR: Me = {
  user_id: "it_mgr01",
  role: "manager",
  permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "policy:read", "policy:edit", "dashboard:read:all", "audit:read:all", "alert:read"],
};
const READER: Me = { ...MGR, permissions: MGR.permissions.filter((p) => p !== "policy:edit") };

/** JWT dạng thật — client đọc `sub` để so danh tính khi đăng nhập lại. */
const jwt = (sub: string, n: string) => `h.${btoa(JSON.stringify({ sub, n })).replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_")}.s`;
const OLD = jwt("it_mgr01", "old");
const NEW = jwt("it_mgr01", "new");
const tokenBody = (token: string) => json(200, { access_token: token, token_type: "bearer", expires_in: 900, csrf_token: "c" });

const VIEW: StrategyView = {
  strategy: "hybrid",
  selectable: ["rule_only", "hybrid", "hybrid_guarded"],
  llm_calibrated: false,
  eval_mode: false,
  changed_by: null,
  changed_at: null,
  reason: null,
};
const HISTORY: StrategyChange[] = [
  { changed_at: "2026-10-25T03:00:00Z", changed_by: "quan.tm", strategy_from: "rule_only", strategy_to: "hybrid", reason: "Quay về mặc định." },
  { changed_at: "2026-10-18T03:00:00Z", changed_by: "quan.tm", strategy_from: "hybrid", strategy_to: "rule_only", reason: "Thử chỉ luật <b>một</b> tuần." },
];

type Call = { method: string; url: string; body: string | null; auth: string | null };
type Server = {
  view?: StrategyView | Record<string, unknown>;
  history?: { items: StrategyChange[]; truncated: boolean };
  /** Trả lời PUT thứ `n` (0-based) với Authorization `auth`. */
  put?: (body: Record<string, unknown>, n: number, auth: string | null) => Response;
  strategyMissing?: boolean;
  me?: Me;
  meAfterLogin?: Me;
  /** Token đăng nhập lại (mặc định NEW — cùng người). */
  loginToken?: string;
  policy?: boolean;
};

const pathOf = (url: string) => new URL(url, "http://x").pathname;
/** Bản sao của object bỏ một khoá (thân thiếu khoá). */
const without = (o: object, k: string): Record<string, unknown> => Object.fromEntries(Object.entries(o).filter(([x]) => x !== k));


/** Trang Chính sách qua client THẬT (AuthProvider, đăng nhập lại) trên fetch giả. */
function renderPolicy(server: Server = {}) {
  const calls: Call[] = [];
  let loggedIn = false;
  let puts = 0;
  let view = server.view ?? VIEW;
  const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? "GET";
    const auth = new Headers(init.headers).get("Authorization");
    calls.push({ method, url, body: typeof init.body === "string" ? init.body : null, auth });
    const path = pathOf(url);
    if (url === "/api/auth/refresh") return tokenBody(OLD);
    if (url === "/api/auth/login") {
      loggedIn = true;
      return tokenBody(server.loginToken ?? NEW);
    }
    if (url === "/api/auth/me") return json(200, loggedIn ? (server.meAfterLogin ?? server.me ?? MGR) : (server.me ?? MGR));
    if (path.startsWith("/api/admin/strategy") && server.strategyMissing) return json(404, { detail: "Not Found" });
    if (path === "/api/admin/strategy" && method === "GET") return json(200, view);
    if (path === "/api/admin/strategy/history") return json(200, server.history ?? { items: HISTORY, truncated: false });
    if (path === "/api/admin/strategy" && method === "PUT") {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      const res = server.put ? server.put(body, puts++, auth) : json(200, { ...VIEW, strategy: body.strategy, changed_by: "it_mgr01", changed_at: "2026-10-26T09:00:00Z", reason: body.reason });
      return res;
    }
    if (path === "/api/policy" && server.policy) {
      return json(200, { version_id: 0, version: DEMO_VERSION, content: POLICY_DEMO, updated_by: null, updated_at: DEMO_UPDATED_AT, is_current: true });
    }
    if (path === "/api/policy/versions" && server.policy) {
      return json(200, [{ version_id: 0, version: DEMO_VERSION, updated_by: null, updated_at: DEMO_UPDATED_AT, is_current: true, restored_from: null }]);
    }
    return json(404, { detail: "Not Found" });
  });
  const client = createClient({ fetch, readCookie: () => "csrf-1", locks: null, channel: { post: () => {}, subscribe: () => {} }, onSessionEnd: vi.fn() });
  function Gate({ children }: { children: ReactNode }) {
    return useAuth().state.status === "signedIn" ? children : <p>Đang kiểm tra…</p>;
  }
  function Landing() {
    return (
      <>
        <p data-testid="landing">{useLocation().pathname}</p>
        <FlashNotice />
      </>
    );
  }
  const queryClient = new QueryClient();
  clients.push(queryClient);
  render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider client={client} subscribe={() => () => {}}>
        <MemoryRouter initialEntries={["/policy"]}>
          <Routes>
            <Route
              path="/policy"
              element={
                <Gate>
                  <PolicyEditor client={client} />
                </Gate>
              }
            />
            <Route path="/dashboard" element={<Landing />} />
            <Route path="/chat" element={<Landing />} />
          </Routes>
        </MemoryRouter>
      </AuthProvider>
    </QueryClientProvider>,
  );
  return { calls, setView: (v: StrategyView) => (view = v) };
}

const options = () => screen.getAllByTestId("strategy-option");
const option = (key: string) => options().find((o) => o.dataset.key === key)!;
const puts = (calls: Call[]) => calls.filter((c) => c.method === "PUT");
const reasonBox = () => screen.getByLabelText(/Lý do đổi/) as HTMLTextAreaElement;
const tick = (ms = 30) => new Promise((r) => setTimeout(r, ms));

async function choose(key: string, reason: string) {
  fireEvent.click(option(key));
  fireEvent.change(reasonBox(), { target: { value: reason } });
  fireEvent.click(screen.getByTestId("strategy-apply"));
}

// ------------------------------------------------------------------------------------------------ t157

describe("t157: khối 'Cách xử lý của hệ thống' — 3 lựa chọn đúng tên D-67 + mô tả trung tính; đang áp dụng; null → '—'", () => {
  it("radiogroup 3 lựa chọn đúng thứ tự, tên, mô tả; lựa chọn hiện tại aria-checked; dữ liệu đổi null → '—'", async () => {
    renderPolicy();
    await screen.findByTestId("strategy-current");
    expect(screen.getByRole("radiogroup", { name: "Cách xử lý của hệ thống" })).toBeTruthy();
    expect(options().map((o) => o.dataset.key)).toStrictEqual(["rule_only", "hybrid", "hybrid_guarded"]);
    expect(STRATEGY_OPTIONS.map((o) => o.title)).toStrictEqual([
      "Chỉ dùng luật",
      "Kết hợp luật và LLM (mặc định)",
      "LLM xét mọi yêu cầu, luật làm lớp chặn cuối",
    ]);
    expect(STRATEGY_OPTIONS.map((o) => o.desc)).toStrictEqual([
      "Bảng luật quyết định; yêu cầu không khớp luật nào được chuyển người duyệt.",
      "Có luật khớp thì luật quyết định; không khớp luật nào thì LLM ước lượng.",
      "Luật cần duyệt hoặc cấm được giữ nguyên; các yêu cầu còn lại LLM xét thêm và chỉ có thể nâng mức cần người. Khi lớp AI không phản hồi, các việc luật cho tự làm sẽ chuyển kỹ thuật viên L2.",
    ]);
    for (const o of STRATEGY_OPTIONS) expect(option(o.key).textContent).toContain(o.desc);
    expect(option("hybrid").getAttribute("aria-checked")).toBe("true");
    expect(option("rule_only").getAttribute("aria-checked")).toBe("false");
    expect(screen.getByTestId("strategy-current-name").textContent).toBe("Kết hợp luật và LLM (mặc định)");
    for (const id of ["strategy-changed-by", "strategy-changed-at", "strategy-reason"]) expect(screen.getByTestId(id).textContent).toBe("—");
    // Không chữ khen / chê phương án nào.
    expect(screen.getByTestId("strategy-section").textContent).not.toMatch(/an toàn hơn|tốt hơn|khuyên dùng|khuyến nghị|rủi ro hơn|kém/i);
    expect(screen.queryByTestId("strategy-apply")).toBeNull(); // chưa đổi → chưa có ô lý do / nút
  });

  it("có người đổi: người, lúc (giờ VN), lý do hiện chữ thô", async () => {
    renderPolicy({ view: { ...VIEW, strategy: "rule_only", changed_by: "quan.tm", changed_at: "2026-10-26T03:05:00Z", reason: "Thử <i>một</i> tuần." } });
    expect((await screen.findByTestId("strategy-changed-by")).textContent).toBe("quan.tm");
    expect(screen.getByTestId("strategy-changed-at").textContent).toBe("26/10 10:05");
    expect(screen.getByTestId("strategy-reason").textContent).toBe("Thử <i>một</i> tuần.");
    expect(screen.getByTestId("strategy-section").querySelector("i")).toBeNull();
  });

  it("có nội dung chính sách: khối cách xử lý ở đầu trang, trước nội dung chính sách", async () => {
    renderPolicy({ policy: true });
    await screen.findAllByTestId("version-row");
    const section = await screen.findByTestId("strategy-section");
    const heading = screen.getByRole("heading", { name: "Nội dung chính sách" });
    expect(section.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });
});

// ------------------------------------------------------------------------------------------------ t158

describe("t158: lựa chọn không có trong `selectable` → hiện nhưng không chọn được (aria-disabled + lý do)", () => {
  it("bấm / Enter không chọn; không có ô lý do; lựa chọn khác vẫn chọn được", async () => {
    renderPolicy({ view: { ...VIEW, selectable: ["rule_only", "hybrid"] } });
    await screen.findByTestId("strategy-current");
    const guarded = option("hybrid_guarded");
    expect(guarded.getAttribute("aria-disabled")).toBe("true");
    expect(guarded.hasAttribute("disabled")).toBe(false);
    expect(within(guarded).getByTestId("strategy-not-selectable").textContent).toBe(NOT_SELECTABLE_TEXT);
    fireEvent.click(guarded);
    fireEvent.keyDown(guarded, { key: "Enter" });
    expect(guarded.getAttribute("aria-checked")).toBe("false");
    expect(screen.queryByTestId("strategy-apply")).toBeNull();
    expect(option("rule_only").getAttribute("aria-disabled")).toBeNull();
    fireEvent.click(option("rule_only"));
    expect(option("rule_only").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("strategy-apply")).toBeTruthy();
  });
});

// ------------------------------------------------------------------------------------------------ t159

describe("t159: nhãn 'Lớp AI chưa hiệu chỉnh: không tự xử lý' cạnh hybrid + hybrid_guarded khi llm_calibrated false HOẶC thiếu khoá", () => {
  const tagged = () => options().filter((o) => within(o).queryByTestId("strategy-uncalibrated")).map((o) => o.dataset.key);
  it.each([
    ["false", { ...VIEW, llm_calibrated: false }, ["hybrid", "hybrid_guarded"]],
    ["thiếu khoá", without(VIEW, "llm_calibrated"), ["hybrid", "hybrid_guarded"]],
    ["true", { ...VIEW, llm_calibrated: true }, []],
  ])("llm_calibrated %s", async (_n, view, expected) => {
    renderPolicy({ view });
    await screen.findByTestId("strategy-current");
    expect(tagged()).toStrictEqual(expected);
    if (expected.length) expect(within(option("hybrid")).getByTestId("strategy-uncalibrated").textContent).toBe(UNCALIBRATED_TEXT);
  });
});

// ------------------------------------------------------------------------------------------------ t160

describe("t160: eval_mode true → câu trung tính + nút Áp dụng khoá (aria-disabled), 0 PUT", () => {
  it("chọn khác + lý do hợp lệ → bấm Áp dụng không gửi", async () => {
    const { calls } = renderPolicy({ view: { ...VIEW, eval_mode: true } });
    expect((await screen.findByTestId("strategy-eval-mode")).textContent).toBe(EVAL_MODE_TEXT);
    expect(EVAL_MODE_TEXT).toBe("Hệ thống đang ở chế độ đánh giá. Lựa chọn ở đây chưa được áp dụng cho tới khi tắt chế độ đánh giá.");
    await choose("rule_only", "Lý do đủ mười ký tự.");
    expect(screen.getByTestId("strategy-apply").getAttribute("aria-disabled")).toBe("true");
    await tick();
    expect(puts(calls)).toHaveLength(0);
  });
});

// ------------------------------------------------------------------------------------------------ t161

describe("t161: đổi → ô lý do bắt buộc 10–500 ký tự sau cắt trắng → Áp dụng → PUT đúng body; xong → cập nhật + tải lại lịch sử", () => {
  it("lý do 9 ký tự / chỉ khoảng trắng → lỗi DƯỚI ô, 0 PUT; 10 ký tự → 1 PUT {strategy, reason đã cắt}", async () => {
    const { calls, setView } = renderPolicy();
    await screen.findByTestId("strategy-current");
    await choose("rule_only", "123456789");
    expect(screen.getByTestId("strategy-reason-error").textContent).toBe("Lý do cần ít nhất 10 ký tự (hiện có 9).");
    expect(reasonBox().getAttribute("aria-invalid")).toBe("true");
    fireEvent.change(reasonBox(), { target: { value: "            " } });
    fireEvent.click(screen.getByTestId("strategy-apply"));
    expect(screen.getByTestId("strategy-reason-error")).toBeTruthy();
    await tick();
    expect(puts(calls)).toHaveLength(0);

    const historyBefore = calls.filter((c) => pathOf(c.url) === "/api/admin/strategy/history").length;
    setView({ ...VIEW, strategy: "rule_only", changed_by: "it_mgr01", changed_at: "2026-10-26T09:00:00Z", reason: "1234567890" });
    fireEvent.change(reasonBox(), { target: { value: "  1234567890  " } });
    fireEvent.click(screen.getByTestId("strategy-apply"));
    expect((await screen.findByTestId("strategy-message")).textContent).toBe("Đã áp dụng: Chỉ dùng luật.");
    expect(puts(calls).map((c) => JSON.parse(c.body!))).toStrictEqual([{ strategy: "rule_only", reason: "1234567890" }]);
    await waitFor(() => expect(screen.getByTestId("strategy-current-name").textContent).toBe("Chỉ dùng luật"));
    await waitFor(() => expect(calls.filter((c) => pathOf(c.url) === "/api/admin/strategy/history").length).toBe(historyBefore + 1));
    expect(screen.queryByTestId("strategy-apply")).toBeNull(); // form dựng lại sạch theo bản mới
  });

  it("lý do 501 ký tự → lỗi, 0 PUT", async () => {
    const { calls } = renderPolicy();
    await screen.findByTestId("strategy-current");
    await choose("hybrid_guarded", "a".repeat(501));
    expect(screen.getByTestId("strategy-reason-error").textContent).toBe("Lý do tối đa 500 ký tự (hiện có 501).");
    await tick();
    expect(puts(calls)).toHaveLength(0);
  });
});

// ------------------------------------------------------------------------------------------------ t162

describe("t162: 403 reauth_required → hộp đăng nhập lại (đường F1) → gửi lại ĐÚNG 1 lần", () => {
  const reauthPut = (_b: Record<string, unknown>, _n: number, auth: string | null) =>
    auth === `Bearer ${NEW}` ? json(200, { ...VIEW, strategy: "rule_only" }) : json(403, { detail: "reauth_required" });

  async function reauth(password = "pw") {
    const dialog = await screen.findByRole("dialog", { name: "Xác nhận lại đăng nhập" });
    fireEvent.change(within(dialog).getByLabelText("Tên đăng nhập"), { target: { value: "quan.tm" } });
    fireEvent.change(within(dialog).getByLabelText("Mật khẩu"), { target: { value: password } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Đăng nhập lại" }));
    return dialog;
  }

  it("cùng người → PUT lần 2 bằng token mới, đúng body cũ; tổng 2 PUT; mật khẩu không còn trên màn", async () => {
    const { calls } = renderPolicy({ put: reauthPut });
    await screen.findByTestId("strategy-current");
    await choose("rule_only", "Lý do đủ mười ký tự.");
    await reauth();
    expect((await screen.findByTestId("strategy-message")).textContent).toBe("Đã áp dụng: Chỉ dùng luật.");
    await tick();
    const sent = puts(calls);
    expect(sent.map((c) => c.auth)).toStrictEqual([`Bearer ${OLD}`, `Bearer ${NEW}`]);
    expect(JSON.parse(sent[1]!.body!)).toStrictEqual(JSON.parse(sent[0]!.body!));
    expect([...document.querySelectorAll("input")].some((i) => i.type === "password" || i.value === "pw")).toBe(false);
  });

  it("huỷ → không gửi lại (1 PUT); người KHÁC → không gửi lại, về trang đầu của người mới + câu báo huỷ", async () => {
    const first = renderPolicy({ put: reauthPut });
    await screen.findByTestId("strategy-current");
    await choose("rule_only", "Lý do đủ mười ký tự.");
    const dialog = await screen.findByRole("dialog", { name: "Xác nhận lại đăng nhập" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Huỷ" }));
    await tick();
    expect(puts(first.calls)).toHaveLength(1);
    expect(screen.getByTestId("strategy-message").textContent).toBe("Chưa áp dụng — đăng nhập lại chưa xong.");
    cleanup();

    const other: Me = { ...MGR, user_id: "khac_01" };
    const second = renderPolicy({ put: reauthPut, meAfterLogin: other, loginToken: jwt("khac_01", "x") });
    await screen.findByTestId("strategy-current");
    await choose("rule_only", "Lý do đủ mười ký tự.");
    await reauth();
    expect((await screen.findByTestId("landing")).textContent).toBe("/dashboard");
    expect(screen.getByText("Bạn đã đăng nhập bằng tài khoản khác — thao tác trên chính sách đã huỷ.")).toBeTruthy();
    expect(puts(second.calls)).toHaveLength(1);
  });
});

// ------------------------------------------------------------------------------------------------ t163

describe("t163: 409 same_as_current → câu + tải lại; 422 fields → lỗi đúng ô; lỗi không dội lại lý do", () => {
  it("409 → 'Phương án này đang được áp dụng' + GET cách xử lý lần 2", async () => {
    const { calls } = renderPolicy({ put: () => json(409, { detail: "same_as_current" }) });
    await screen.findByTestId("strategy-current");
    const getsBefore = calls.filter((c) => c.method === "GET" && pathOf(c.url) === "/api/admin/strategy").length;
    await choose("rule_only", "Lý do đủ mười ký tự.");
    expect((await screen.findByTestId("strategy-message")).textContent).toBe(SAME_AS_CURRENT_TEXT);
    expect(SAME_AS_CURRENT_TEXT).toBe("Phương án này đang được áp dụng");
    await waitFor(() => expect(calls.filter((c) => c.method === "GET" && pathOf(c.url) === "/api/admin/strategy").length).toBe(getsBefore + 1));
  });

  it("422 fields reason → lỗi dưới ô lý do; fields strategy → lỗi dưới nhóm lựa chọn; câu không chứa lý do đã gõ", async () => {
    renderPolicy({ put: (_b, n) => json(422, { error: "invalid_request", fields: [n === 0 ? "reason" : "strategy"] }) });
    await screen.findByTestId("strategy-current");
    await choose("rule_only", "BI-MAT-123 lý do");
    const reasonErr = await screen.findByTestId("strategy-reason-error");
    expect(reasonErr.textContent).not.toContain("BI-MAT");
    expect(screen.queryByTestId("strategy-choice-error")).toBeNull();
    fireEvent.click(screen.getByTestId("strategy-apply"));
    expect((await screen.findByTestId("strategy-choice-error")).textContent).toBe(NOT_SELECTABLE_TEXT);
    // Lý do chỉ còn trong chính ô nhập (giữ để sửa) — không xuất hiện trong chữ nào khác của màn.
    expect(reasonBox().value).toBe("BI-MAT-123 lý do");
    const outside = document.body.cloneNode(true) as HTMLElement;
    for (const t of outside.querySelectorAll("textarea")) t.remove();
    expect(outside.textContent).not.toContain("BI-MAT");
  });

  it("403 forbidden / 500 → câu chung, không chứa lý do", async () => {
    renderPolicy({ put: () => json(403, { detail: "forbidden" }) });
    await screen.findByTestId("strategy-current");
    await choose("rule_only", "BI-MAT-456 lý do");
    expect((await screen.findByTestId("strategy-message")).textContent).toBe("Bạn không có quyền thực hiện thao tác này.");
  });
});

// ------------------------------------------------------------------------------------------------ t164

describe("t164: không có policy:edit → chỉ xem (không chọn được, không ô lý do, 0 PUT)", () => {
  it("mọi lựa chọn aria-disabled; câu chỉ xem; bấm không đổi", async () => {
    const { calls } = renderPolicy({ me: READER });
    expect((await screen.findByTestId("strategy-readonly")).textContent).toBe(READONLY_TEXT);
    for (const o of options()) expect(o.getAttribute("aria-disabled")).toBe("true");
    expect(screen.queryAllByTestId("strategy-not-selectable")).toHaveLength(0); // lý do "không cho chọn" chỉ khi có quyền sửa
    fireEvent.click(option("rule_only"));
    expect(option("rule_only").getAttribute("aria-checked")).toBe("false");
    expect(screen.queryByTestId("strategy-apply")).toBeNull();
    await tick();
    expect(calls.filter((c) => c.method !== "GET" && !c.url.startsWith("/api/auth"))).toHaveLength(0);
  });
});

// ------------------------------------------------------------------------------------------------ t165

describe("t165: lịch sử đổi — bảng 4 cột, thứ tự server, limit 50, truncated; route chưa có → câu trung tính", () => {
  it("bảng: Lúc · Người đổi · Từ → sang · Lý do (chữ thô); giữ thứ tự server; truncated → dòng báo", async () => {
    const { calls } = renderPolicy({ history: { items: HISTORY, truncated: true } });
    const rows = await screen.findAllByTestId("strategy-history-row");
    expect(rows).toHaveLength(2);
    const table = rows[0]!.closest("table")!;
    expect([...table.querySelectorAll("th")].map((th) => th.textContent)).toStrictEqual(["Lúc", "Người đổi", "Từ → sang", "Lý do"]);
    expect([...rows[0]!.querySelectorAll("td")].map((td) => td.textContent)).toStrictEqual([
      "25/10 10:00",
      "quan.tm",
      "Chỉ dùng luật → Kết hợp luật và LLM (mặc định)",
      "Quay về mặc định.",
    ]);
    expect(rows[1]!.querySelectorAll("td")[3]!.textContent).toBe("Thử chỉ luật <b>một</b> tuần.");
    // L4 (soát 01/11): cột Người đổi không ngắt giữa mã người dùng ("npa-" / "demo.quan.tm")
    expect(rows[0]!.querySelectorAll("td")[1]!.className.split(/\s+/)).toContain("whitespace-nowrap");
    expect(table.querySelector("b")).toBeNull();
    expect(screen.getByTestId("strategy-history-truncated").textContent).toBe(HISTORY_TRUNCATED_TEXT);
    expect(calls.some((c) => c.url === "/api/admin/strategy/history?limit=50")).toBe(true);
  });

  it("route chưa có (404) → 'Máy chủ chưa có chức năng chọn cách xử lý.', không khối lỗi đỏ; không chữ 'Phase'", async () => {
    renderPolicy({ strategyMissing: true, policy: true });
    expect((await screen.findByTestId("strategy-missing")).textContent).toBe(STRATEGY_MISSING_TEXT);
    await screen.findAllByTestId("version-row");
    expect(screen.queryByTestId("strategy-error")).toBeNull();
    expect(document.body.textContent).not.toMatch(/Phase/);
  });
});

// ------------------------------------------------------------------------------------------------ t166–t169 (Tổng quan)

const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });
const BUSINESS = {
  from: "2026-10-20T00:00:00Z",
  to: "2026-10-26T00:00:00Z",
  unavailable: [],
  scope: "all",
  metrics: {
    automation_rate: null,
    escalation_rate_raw: null,
    escalation_rate_weighted: null,
    deflection_rate: null,
    approval_expired_count: null,
    decided_by_distribution: null,
    top_matched_rules: null,
    override_count: null,
    e1_split: null,
    e3_cases: null,
  },
};

type Dash = { strategies?: (source: string) => Response };
function renderDashboard(dash: Dash = {}) {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      const path = pathOf(url);
      if (path === "/api/dashboard/business") return json(200, BUSINESS);
      if (path === "/api/alerts") return json(200, { items: [], truncated: false });
      if (path === "/api/dashboard/strategies") {
        const source = new URL(url, "http://x").searchParams.get("source") ?? "real";
        return dash.strategies ? dash.strategies(source) : json(200, buildStrategies(source as "real", "2026-10-20T00:00:00Z", "2026-10-26T00:00:00Z"));
      }
      return json(404, { detail: "Not Found" });
    }),
  );
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(MGR)}>
        <MemoryRouter initialEntries={["/dashboard"]}>
          <DashboardPage />
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
  return calls;
}

const tab = (name: string) => screen.getByRole("tab", { name });
async function openCompare() {
  await screen.findByRole("tab", { name: "So sánh phương án" });
  fireEvent.click(tab("So sánh phương án"));
}
const strategyCalls = (calls: string[]) => calls.filter((u) => pathOf(u) === "/api/dashboard/strategies").map((u) => new URL(u, "http://x").searchParams);

describe("t166: tab thứ 3 'So sánh phương án' — chung khoảng thời gian; nguồn mặc định 'Thật'; 'Dữ liệu thử' → source=sim + dải", () => {
  it("thứ tự tab; from/to giống tab Nghiệp vụ; đổi khoảng → gọi lại cùng khoảng; đổi nguồn → sim + dải 'DỮ LIỆU THỬ'", async () => {
    const calls = renderDashboard();
    await screen.findByRole("tab", { name: "Nghiệp vụ" });
    expect(screen.getAllByRole("tablist", { name: "Loại số liệu" })[0]!.textContent).toBe("Nghiệp vụAISo sánh phương án");
    await openCompare();
    await screen.findByTestId("compare-table");
    const biz = new URL(calls.find((u) => pathOf(u) === "/api/dashboard/business")!, "http://x").searchParams;
    const first = strategyCalls(calls)[0]!;
    expect([first.get("from"), first.get("source")]).toStrictEqual([biz.get("from"), "real"]);
    expect(screen.queryByTestId("compare-sim-band")).toBeNull();
    expect(tab("Thật").getAttribute("aria-selected")).toBe("true");

    fireEvent.click(tab("30 ngày"));
    await waitFor(() => expect(strategyCalls(calls)).toHaveLength(2));
    expect(strategyCalls(calls)[1]!.get("from")! < first.get("from")!).toBe(true);

    fireEvent.click(tab("Dữ liệu thử"));
    expect((await screen.findByTestId("compare-sim-band")).textContent).toBe(SIM_BAND);
    expect(SIM_BAND).toBe("DỮ LIỆU THỬ");
    expect(strategyCalls(calls).at(-1)!.get("source")).toBe("sim");
    expect(screen.getByTestId("compare").dataset.source).toBe("sim");
  });
});

describe("t167: bảng — cột theo strategies, dòng theo metrics ĐÚNG thứ tự server; nhãn tạm; khoá lạ nguyên khoá; không màu / mũi tên / điểm", () => {
  it("thứ tự server được giữ (server đảo cột + dòng); nhãn tạm; ô chưa đủ dữ liệu + '—'; chú thích đúng chữ", async () => {
    renderDashboard({
      strategies: (source) => {
        const body = buildStrategies(source as "real", "a", "b");
        return json(200, {
          ...body,
          strategies: ["hybrid_guarded", "rule_only", "hybrid"],
          metrics: [{ key: "zz_moi", kind: "value", unit: "count", values: { hybrid_guarded: { value: 1 }, rule_only: { value: 2 }, hybrid: { value: 3 } } }, ...[...body.metrics].reverse()],
        });
      },
    });
    await openCompare();
    const table = await screen.findByTestId("compare-table");
    expect([...table.querySelectorAll<HTMLElement>('[data-testid="compare-col"]')].map((c) => c.dataset.strategy)).toStrictEqual(["hybrid_guarded", "rule_only", "hybrid"]);
    const rows = [...table.querySelectorAll<HTMLElement>('[data-testid="compare-row"]')];
    expect(rows.map((r) => r.dataset.key)).toStrictEqual(["zz_moi", ...[...METRIC_KEYS].reverse()]);
    expect(rows[0]!.querySelector("th")!.textContent).toBe("zz_moi"); // khoá lạ → nguyên khoá
    expect(rows.find((r) => r.dataset.key === "auto_rate")!.querySelector("th")!.textContent).toBe(METRIC_LABEL.auto_rate);
    const cell = (key: string, s: string) => rows.find((r) => r.dataset.key === key)!.querySelector<HTMLElement>(`[data-strategy="${s}"]`)!.textContent;
    expect(cell("l1_reject_rate", "hybrid_guarded")).toBe("chưa đủ dữ liệu (n=12)");
    expect(cell("llm_cost_per_ticket", "rule_only")).toBe("chưa đủ dữ liệu (n=0)"); // {value: null, n: 0} (hợp đồng sửa lần 3)
    expect(cell("auto_rate", "hybrid")).toBe("55,9\u00a0% (190/340)");
    expect(screen.getByTestId("compare-note").textContent).toBe(COMPARE_NOTE);
    expect(COMPARE_NOTE).toBe(
      "Các chỉ số vận hành không có chiều tốt hơn, tuỳ ưu tiên của đơn vị. Tỉ lệ bỏ sót ca cần người chỉ đo được trên bộ tình huống có nhãn (báo cáo đánh giá).",
    );
    // Không màu trạng thái / mũi tên / điểm tổng: mọi ô cùng một class, không chữ xếp hạng.
    const cells = [...table.querySelectorAll<HTMLElement>('[data-testid="compare-cell"]')];
    expect(new Set(cells.map((c) => c.className)).size).toBe(1);
    expect(cells.some((c) => /danger|orange|green|success|warn|red/.test(c.className))).toBe(false);
    expect(table.textContent).not.toMatch(/[↑↓▲▼]|điểm tổng|tốt nhất|xếp hạng/i);
    expect(rows.find((r) => r.dataset.key === "llm_cost_per_ticket")!.className).toBe(rows[1]!.className); // chi phí như mọi dòng
  });

  it("unavailable: khoá trong bảng → ô 'Chưa có dữ liệu'; khoá không trong bảng → một dòng liệt kê", async () => {
    renderDashboard({ strategies: (source) => json(200, { ...buildStrategies(source as "real", "a", "b"), unavailable: ["overrides", "khoa_khac"] }) });
    await openCompare();
    const table = await screen.findByTestId("compare-table");
    const row = table.querySelector<HTMLElement>('[data-key="overrides"]')!;
    expect([...row.querySelectorAll("td")].map((td) => td.textContent)).toStrictEqual(["Chưa có dữ liệu", "Chưa có dữ liệu", "Chưa có dữ liệu"]);
    expect(screen.getByTestId("compare-unavailable").textContent).toBe("Chưa có dữ liệu: khoa_khac");
  });
});

// ------------------------------------------------------------------------------------------------ t200 (hợp đồng sửa lần 3, ĐP 26/10 23:51)

describe("t200: ô so sánh — ratio {0,0} và value {null, n:0} → 'chưa đủ dữ liệu (n=0)' (không NaN/Infinity); cả ô null chỉ ở phương án 0 lá → '—'; không gửi source=all", () => {
  const rowsOf = (table: HTMLElement) => [...table.querySelectorAll<HTMLElement>('[data-testid="compare-row"]')];
  const cellOf = (table: HTMLElement, key: string, s: string) =>
    rowsOf(table).find((r) => r.dataset.key === key)!.querySelector<HTMLElement>(`[data-strategy="${s}"]`)!.textContent;
  it("Thật: {num:0, den:0} và {value:null, n:0} ra 'chưa đủ dữ liệu (n=0)'; không ô nào chứa NaN / Infinity / '—'", async () => {
    renderDashboard();
    await openCompare();
    const table = await screen.findByTestId("compare-table");
    expect(cellOf(table, "quick_approve_rate", "hybrid_guarded")).toBe("chưa đủ dữ liệu (n=0)");
    expect(cellOf(table, "llm_cost_per_ticket", "rule_only")).toBe("chưa đủ dữ liệu (n=0)");
    expect(table.textContent).not.toMatch(/NaN|Infinity|∞/);
    const cells = [...table.querySelectorAll<HTMLElement>('[data-testid="compare-cell"]')].map((c) => c.textContent);
    expect(cells.filter((t) => t === "—")).toStrictEqual([]);
  });
  it("Dữ liệu thử: phương án 0 lá (mọi ô null) → cả cột '—'; cột khác vẫn có số; mọi lần gọi chỉ source real|sim", async () => {
    const calls = renderDashboard();
    await openCompare();
    await screen.findByTestId("compare-table");
    fireEvent.click(tab("Dữ liệu thử"));
    await waitFor(() => expect(screen.getByTestId("compare").dataset.source).toBe("sim"));
    const table = screen.getByTestId("compare-table");
    expect(rowsOf(table).map((r) => cellOf(table, r.dataset.key!, "hybrid_guarded"))).toStrictEqual(METRIC_KEYS.map(() => "—"));
    expect(cellOf(table, "auto_rate", "hybrid")).toBe("55,9\u00a0% (570/1.020)");
    expect(table.textContent).not.toMatch(/NaN|Infinity/);
    expect(strategyCalls(calls).map((q) => q.get("source"))).toStrictEqual(["real", "sim"]);
  });
  it("cellText trực tiếp: {num:0, den:0} với ngưỡng bất kỳ không chia — chữ không chứa NaN", () => {
    expect(cellText({ kind: "ratio" }, { num: 0, den: 0 })).toBe("chưa đủ dữ liệu (n=0)");
    expect(cellText({ kind: "value", unit: "usd" }, { value: null, n: 0 })).toBe("chưa đủ dữ liệu (n=0)");
    expect(cellText({ kind: "ratio" }, null)).toBe("—");
  });
});

describe("t168: bảng phụ 'Thành phần yêu cầu theo loại' — chỉ số đếm, loại theo thứ tự xuất hiện, thiếu → '—'", () => {
  it("dòng + ô", async () => {
    renderDashboard();
    await openCompare();
    const mix = await screen.findByTestId("intent-mix");
    const rows = [...mix.querySelectorAll<HTMLElement>('[data-testid="intent-row"]')];
    expect(rows.map((r) => r.dataset.key)).toStrictEqual(["vpn", "account", "software", "access"]);
    expect(rows.map((r) => r.querySelector("th")!.textContent)).toStrictEqual(["VPN", "Tài khoản", "Phần mềm", "Quyền truy cập"]);
    const access = [...rows[3]!.querySelectorAll("td")].map((td) => td.textContent);
    expect(access).toStrictEqual(["—", "40", "10"]);
    expect(screen.getByRole("heading", { name: "Thành phần yêu cầu theo loại" })).toBeTruthy();
  });
});

describe("t169: lỗi — source lệch → lỗi dữ liệu, KHÔNG bảng; 503 → 'Số liệu tạm thời không có'; 404 → khối trong tab, giữ hàng tab", () => {
  it("source lệch", async () => {
    renderDashboard({ strategies: () => json(200, buildStrategies("sim", "a", "b")) }); // gửi real, server trả sim
    await openCompare();
    expect((await screen.findByTestId("compare-data-error")).textContent).toBe("Số liệu trả về không đúng nguồn đã chọn — không hiển thị để tránh hiểu sai.");
    expect(screen.queryByTestId("compare-table")).toBeNull();
    expect(screen.queryByTestId("intent-mix")).toBeNull();
  });
  it("503 monitor_unavailable", async () => {
    renderDashboard({ strategies: () => json(503, { detail: "monitor_unavailable" }) });
    await openCompare();
    expect((await screen.findByTestId("load-error")).textContent).toContain(MONITOR_DOWN_TEXT);
    expect(screen.queryByTestId("compare-table")).toBeNull();
  });
  it("404 Not Found (route chưa có) → khối trong tab; hàng tab + khoảng thời gian vẫn còn", async () => {
    renderDashboard({ strategies: () => json(404, { detail: "Not Found" }) });
    await openCompare();
    expect((await screen.findByTestId("compare-missing")).textContent).toContain("Máy chủ chưa có số liệu so sánh phương án.");
    expect(tab("Nghiệp vụ")).toBeTruthy();
    expect(tab("7 ngày")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/Phase/);
  });
});

// ------------------------------------------------------------------------------------------------ t184

describe("t184 (soát bảo mật NGHI-1): PUT 2xx khác 200 / 200 thân sai → KHÔNG báo thành công, báo chưa xác nhận + tải lại", () => {
  it.each([
    ["202", () => json(202, { ...VIEW, strategy: "rule_only" })],
    ["200 thân sai hình", () => json(200, { strategy: "rule_only" })],
  ])("%s → câu 'Chưa xác nhận được kết quả…' + GET cách xử lý + GET lịch sử lần nữa", async (_n, put) => {
    const { calls } = renderPolicy({ put });
    await screen.findByTestId("strategy-current");
    await screen.findAllByTestId("strategy-history-row");
    const count = (p: string) => calls.filter((c) => c.method === "GET" && pathOf(c.url) === p).length;
    const [cur, hist] = [count("/api/admin/strategy"), count("/api/admin/strategy/history")];
    await choose("rule_only", "Lý do đủ mười ký tự.");
    expect((await screen.findByTestId("strategy-message")).textContent).toBe("Chưa xác nhận được kết quả — đang tải lại trạng thái hiện tại.");
    await waitFor(() => expect(count("/api/admin/strategy")).toBe(cur + 1));
    await waitFor(() => expect(count("/api/admin/strategy/history")).toBe(hist + 1));
    expect(screen.queryByText(/Đã áp dụng/)).toBeNull();
  });
});
