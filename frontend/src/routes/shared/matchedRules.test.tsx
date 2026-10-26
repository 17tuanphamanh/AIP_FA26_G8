// N-PA P4 — bảng "Các luật khớp" ở phiếu duyệt L1 và bước B13/B14 của nhật ký quyết định; KHÔNG ở màn nhân viên.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApprovalViewP4, MatchedRule, Me } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { buildApprovalFixtures } from "../../mocks/fixtures/approvals.ts";
import { ApprovalDetailRoute } from "../l1/ApprovalDetail.tsx";
import {
  APPLIED_TEXT,
  BAD_DATA_TEXT,
  MATCHED_ONLY_TEXT,
  matchedView,
  NO_DATA_TEXT,
  NO_RULE_TEXT,
  REPLACED_TEXT,
  SAME_LEVEL_TEXT,
  UNDECIDED_TEXT,
} from "./matchedRules.ts";
import { TicketTraceRoute } from "./TicketTrace.tsx";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const c of clients.splice(0)) c.clear();
  vi.unstubAllGlobals();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const L1: Me = {
  user_id: "l1_01",
  role: "l1",
  permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "escalation:handle", "dashboard:read:own", "audit:read:own"],
};
const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });

const R = (rule_id: string, decision: MatchedRule["decision"], applied: boolean, description: string | null = `Mô tả ${rule_id}`): MatchedRule => ({
  rule_id,
  description,
  decision,
  applied,
});

// ------------------------------------------------------------------------------------------------ t170

describe("t170: matchedView — applied / thua khác mức / thua cùng mức; [] ≠ thiếu khoá; số applied ≠ 1 → lỗi dữ liệu", () => {
  it("ba câu kết quả đúng chữ, giữ thứ tự server", () => {
    expect([APPLIED_TEXT, REPLACED_TEXT, SAME_LEVEL_TEXT]).toStrictEqual([
      "áp dụng (chặt nhất)",
      "khớp nhưng bị luật chặt hơn thay thế",
      "khớp, cùng mức với luật được áp dụng",
    ]);
    const view = matchedView([R("R20", "allow", false, null), R("R18", "approval_required", true), R("R19", "approval_required", false)]);
    expect(view.kind).toBe("rows");
    if (view.kind !== "rows") return;
    expect(view.rows.map((r) => [r.ruleId, r.description, r.decision, r.result])).toStrictEqual([
      ["R20", "—", "Cho phép", REPLACED_TEXT],
      ["R18", "Mô tả R18", "Cần duyệt", APPLIED_TEXT],
      ["R19", "Mô tả R19", "Cần duyệt", SAME_LEVEL_TEXT],
    ]);
  });
  it("deny thắng: allow + approval_required thua → 'bị thay thế'; deny thua cùng mức → 'cùng mức'", () => {
    const view = matchedView([R("A", "allow", false), R("B", "approval_required", false), R("C", "deny", true), R("D", "deny", false)]);
    expect(view.kind === "rows" && view.rows.map((r) => r.result)).toStrictEqual([REPLACED_TEXT, REPLACED_TEXT, APPLIED_TEXT, SAME_LEVEL_TEXT]);
  });
  it("[] → không có luật khớp; undefined → chưa có dữ liệu; 2 applied → lỗi dữ liệu", () => {
    expect(matchedView([])).toStrictEqual({ kind: "empty" });
    expect(matchedView(undefined)).toStrictEqual({ kind: "missing" });
    expect(matchedView([R("A", "deny", true), R("B", "deny", true)])).toStrictEqual({ kind: "invalid" });
    // Hợp đồng sửa 21:15: 0 applied hợp lệ (quyết định cuối không do luật) — xem t185.
    expect([NO_RULE_TEXT, NO_DATA_TEXT]).toStrictEqual(["Không có luật nào khớp", "Chưa có dữ liệu luật khớp"]);
  });
});

// ------------------------------------------------------------------------------------------------ t171

const fixtureView = (id = "apv-demo-01"): ApprovalViewP4 =>
  buildApprovalFixtures(Date.now()).find((f) => f.approval_id === id)!.view as ApprovalViewP4;

function renderApproval(view: ApprovalViewP4) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url === `/api/approvals/${view.approval_id}`) return json(200, view);
      if (url.startsWith("/api/approvals?")) return json(200, { items: [] });
      return json(404, { detail: "not_found" });
    }),
  );
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(L1)}>
        <MemoryRouter initialEntries={[`/approvals/${view.approval_id}`]}>
          <Routes>
            <Route path="/approvals/:approvalId" element={<ApprovalDetailRoute />} />
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}

describe("t171: phiếu duyệt L1 — bảng 4 cột theo thứ tự server; thiếu khoá / [] / lỗi số applied không chặn quyết định", () => {
  it("apv-demo-01: R18 áp dụng, R19 cùng mức, R20 bị thay thế (mô tả null → '—')", async () => {
    renderApproval(fixtureView());
    const box = await screen.findByTestId("matched-rules");
    expect(within(box).getByRole("heading").textContent).toBe("Các luật khớp");
    expect([...box.querySelectorAll("th")].map((th) => th.textContent)).toStrictEqual(["Luật", "Mô tả", "Quyết định của luật", "Kết quả"]);
    const rows = within(box).getAllByTestId("matched-rule");
    expect(rows.map((r) => [...r.querySelectorAll("td")].map((td) => td.textContent))).toStrictEqual([
      ["R18", "Yêu cầu gửi ngoài giờ hành chính cần người duyệt", "Cần duyệt", APPLIED_TEXT],
      ["R19", "Nhân viên chưa qua thử việc cần người duyệt", "Cần duyệt", SAME_LEVEL_TEXT],
      ["R20", "—", "Cho phép", REPLACED_TEXT],
    ]);
    expect(rows.filter((r) => r.dataset.applied === "true")).toHaveLength(1);
    expect(box.querySelector(".text-danger, .bg-danger-bg, .text-orange-ink")).toBeNull(); // không tô màu theo quyết định
    expect(screen.getByTestId("decision-bar")).toBeTruthy();
  });

  it.each([
    ["thiếu khoá", undefined, NO_DATA_TEXT],
    ["mảng rỗng", [] as MatchedRule[], NO_RULE_TEXT],
    ["2 luật applied", [R("R18", "approval_required", true), R("R19", "approval_required", true)], BAD_DATA_TEXT],
  ])("%s → câu tại bảng; thanh quyết định vẫn còn", async (_n, rules, text) => {
    const rest = Object.fromEntries(Object.entries(fixtureView()).filter(([k]) => k !== "matched_rules")) as ApprovalViewP4;
    renderApproval(rules === undefined ? rest : { ...rest, matched_rules: rules });
    expect((await screen.findByTestId("matched-note")).textContent).toBe(text);
    expect(screen.queryAllByTestId("matched-rule")).toHaveLength(0);
    expect(screen.getByTestId("decision-bar")).toBeTruthy();
  });
});

// ------------------------------------------------------------------------------------------------ t172

describe("t172: nhật ký quyết định — bảng chỉ ở bước có khối policy (B13/B14); thiếu khoá → 'Chưa có dữ liệu luật khớp'", () => {
  const EMPTY = { screen: null, classify: null, diagnose: null, sources: null, policy: null, approval: null, execution: null, outcome: null };
  const policy = { rule_id: "R18", rule_description: "x", policy_decision: "approval_required", risk_level: "medium", decided_by: "rule", raw_prob: null, calibrated_prob: null };
  function renderTrace(matched: MatchedRule[] | undefined) {
    const body = {
      ticket_id: "t-1",
      is_parent: false,
      parent_ticket_id: null,
      children: [],
      steps: [
        { ...EMPTY, step: "B3", event: "classified", at: "2099-09-26T01:00:00Z", classify: { intent: "vpn", confidence: 0.9, model_probs: null, model_version: null, is_multi: false } },
        { ...EMPTY, step: "B13/B14", event: "risk_decided", at: "2099-09-26T01:01:00Z", policy: matched === undefined ? policy : { ...policy, matched_rules: matched } },
      ],
    };
    vi.stubGlobal("fetch", vi.fn(async () => json(200, body)));
    const client = new QueryClient();
    clients.push(client);
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={["/trace/t-1"]}>
          <Routes>
            <Route path="/trace/:ticketId" element={<TicketTraceRoute />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }
  const stepCard = (s: string) => document.querySelector<HTMLElement>(`[data-testid="trace-step"][data-step="${s}"]`)!;

  it("có luật: bảng trong thẻ B13/B14, không ở thẻ B3", async () => {
    renderTrace([R("R18", "approval_required", true), R("R20", "allow", false)]);
    await screen.findAllByTestId("trace-step");
    expect(within(stepCard("B13/B14")).getAllByTestId("matched-rule").map((r) => r.querySelectorAll("td")[3]!.textContent)).toStrictEqual([
      APPLIED_TEXT,
      REPLACED_TEXT,
    ]);
    expect(within(stepCard("B3")).queryByTestId("matched-rules")).toBeNull();
  });
  it("thiếu khoá → 'Chưa có dữ liệu luật khớp'", async () => {
    renderTrace(undefined);
    await screen.findAllByTestId("trace-step");
    expect(within(stepCard("B13/B14")).getByTestId("matched-note").textContent).toBe(NO_DATA_TEXT);
  });
});

// ------------------------------------------------------------------------------------------------ t173

describe("t173: màn nhân viên KHÔNG dùng bảng luật khớp — đồ thị import từ các màn chat không chạm MatchedRules", () => {
  it("mọi module tới được từ routes/employee/* (trừ test) không import routes/shared/MatchedRules / matchedRules", () => {
    const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}"], { query: "?raw", import: "default", eager: true });
    const files = Object.keys(sources);
    expect(files.length).toBeGreaterThan(50);
    const resolve = (from: string, spec: string) => {
      const parts = from.split("/").slice(0, -1);
      for (const seg of spec.split("/")) {
        if (seg === "..") parts.pop();
        else if (seg !== ".") parts.push(seg);
      }
      const p = parts.join("/");
      return [p, `${p}.ts`, `${p}.tsx`].find((c) => Object.hasOwn(sources, c)) ?? p;
    };
    const seen = new Set<string>();
    const queue = files.filter((f) => f.startsWith("/src/routes/employee/"));
    expect(queue.length).toBeGreaterThan(3);
    while (queue.length) {
      const f = queue.pop()!;
      if (seen.has(f)) continue;
      seen.add(f);
      for (const m of sources[f]!.matchAll(/(?:from|import)\s*\(?\s*["'](\.{1,2}\/[^"']+)["']/g)) {
        const target = resolve(f, m[1]!);
        if (Object.hasOwn(sources, target)) queue.push(target);
      }
    }
    expect(seen.has("/src/routes/employee/ChatPage.tsx")).toBe(true);
    expect([...seen].filter((f) => /\/routes\/shared\/(MatchedRules\.tsx|matchedRules\.ts)$/.test(f))).toStrictEqual([]);
    expect([...seen].filter((f) => sources[f]!.includes("matched-rules"))).toStrictEqual([]);
  });
});

// ------------------------------------------------------------------------------------------------ t183

describe("t183 (soát bảo mật FAIL-1): luật 'applied' KHÔNG chặt nhất → lỗi dữ liệu, không vẽ bảng", () => {
  it.each([
    ["deny thua + allow applied", [R("D", "deny", false), R("A", "allow", true)]],
    ["approval_required thua + allow applied", [R("A", "allow", true), R("Q", "approval_required", false)]],
    ["deny thua + approval_required applied", [R("Q", "approval_required", true), R("D", "deny", false)]],
  ])("%s → invalid", (_n, rules) => {
    expect(matchedView(rules)).toStrictEqual({ kind: "invalid" });
  });
  it("applied chặt nhất (kể cả có luật cùng mức) vẫn hợp lệ", () => {
    expect(matchedView([R("A", "allow", false), R("D1", "deny", true), R("D2", "deny", false)]).kind).toBe("rows");
  });
  it("màn phiếu duyệt: câu lỗi dữ liệu, không bảng, thanh quyết định vẫn còn", async () => {
    renderApproval({ ...fixtureView(), matched_rules: [R("R12", "deny", false), R("R20", "allow", true)] });
    expect((await screen.findByTestId("matched-note")).textContent).toBe(BAD_DATA_TEXT);
    expect(screen.queryAllByTestId("matched-rule")).toHaveLength(0);
    expect(screen.getByTestId("decision-bar")).toBeTruthy();
  });
});

// ------------------------------------------------------------------------------------------------ t185, t186 (hợp đồng sửa 21:15/21:30)

describe("t185: 0 luật applied (quyết định cuối không do luật) → mọi luật 'khớp' + một dòng dưới bảng; > 1 applied vẫn lỗi", () => {
  it("matchedView: rows 'khớp', cờ undecided", () => {
    const view = matchedView([R("R20", "allow", false), R("R18", "approval_required", false)]);
    expect(view.kind).toBe("rows");
    if (view.kind !== "rows") return;
    expect(view.rows.map((r) => r.result)).toStrictEqual([MATCHED_ONLY_TEXT, MATCHED_ONLY_TEXT]);
    expect(MATCHED_ONLY_TEXT).toBe("khớp");
    expect(view.undecided).toBe(true);
    expect(matchedView([R("A", "deny", true), R("B", "deny", true)])).toStrictEqual({ kind: "invalid" });
  });
  it("màn phiếu duyệt: bảng + dòng 'Quyết định cuối không do luật — …'", async () => {
    renderApproval({ ...fixtureView(), matched_rules: [R("R20", "allow", false), R("R18", "approval_required", false)] });
    const box = await screen.findByTestId("matched-rules");
    expect(within(box).getAllByTestId("matched-rule").map((r) => r.querySelectorAll("td")[3]!.textContent)).toStrictEqual(["khớp", "khớp"]);
    expect(within(box).getByTestId("matched-undecided").textContent).toBe(UNDECIDED_TEXT);
    expect(UNDECIDED_TEXT).toBe("Quyết định cuối không do luật — xem lý do ở bước đánh giá rủi ro");
  });
  it("có đúng 1 applied → không có dòng 'không do luật'", async () => {
    renderApproval(fixtureView());
    await screen.findAllByTestId("matched-rule");
    expect(screen.queryByTestId("matched-undecided")).toBeNull();
  });
});

describe("t186: decision null (luật đã xoá khỏi chính sách) → parser nhận, cột Quyết định '—', bỏ qua khi so mức chặt", () => {
  const nullRule = { rule_id: "R99", description: null, decision: null, applied: false };
  it("phiếu duyệt KHÔNG 502; bảng hiện '—'; không làm invalid", async () => {
    renderApproval({ ...fixtureView(), matched_rules: [R("R20", "allow", true), nullRule as unknown as MatchedRule] });
    const rows = await screen.findAllByTestId("matched-rule");
    expect([...rows[1]!.querySelectorAll("td")].map((td) => td.textContent)).toStrictEqual(["R99", "—", "—", "khớp"]);
    expect(screen.getByTestId("decision-bar")).toBeTruthy();
  });
  it("matchedView: luật applied có decision null → vẫn vẽ (không so mức)", () => {
    const view = matchedView([{ ...nullRule, applied: true } as unknown as MatchedRule, R("D", "deny", false)]);
    expect(view.kind === "rows" && view.rows.map((r) => [r.decision, r.result])).toStrictEqual([
      ["—", APPLIED_TEXT],
      ["Cấm", MATCHED_ONLY_TEXT],
    ]);
  });
});
