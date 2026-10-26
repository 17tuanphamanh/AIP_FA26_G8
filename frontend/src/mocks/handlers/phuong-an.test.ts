// N-PA P7 + P6 — handler MSW mới (chỉ dev:mock) khớp hợp đồng chốt và parser chặt của FE; không còn chữ "Phase 7" hiển thị.
// Chạy handler bằng `getResponse` của MSW (không service worker); `/api/auth/me` (quyền — backend thật) đi vào fetch giả.
import { getResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseStrategies } from "../../api/dashboard.ts";
import { parseQueuePage } from "../../api/escalations.ts";
import { parseStrategyHistory, parseStrategyView } from "../../api/strategy.ts";
import type { Me } from "../../api/types.ts";
import { METRIC_KEYS } from "../fixtures/strategy.ts";
import { escalationCloseHandlers } from "./escalation-close.ts";
import { escalationQueueHandlers, escalationStore } from "./escalation-queue.ts";
import { handlers } from "./index.ts";
import { strategyCompareHandlers } from "./strategy-compare.ts";
import { resetStrategyMock, strategyHandlers } from "./strategy.ts";

afterEach(() => vi.unstubAllGlobals());

const BASE = ["ticket:create", "ticket:read:own"];
const MGR: Me = { user_id: "quan.tm", role: "manager", permissions: [...BASE, "policy:read", "policy:edit", "dashboard:read:all", "alert:read"] };
const READER: Me = { ...MGR, permissions: MGR.permissions.filter((p) => p !== "policy:edit") };
const L2: Me = { user_id: "long.nh", role: "l2", permissions: [...BASE, "ticket:read:any", "escalation:handle"] };

const url = (path: string) => new URL(path, location.href).toString();
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function stubMe(me: Me) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const path = new URL(typeof input === "string" ? input : input.url, location.href).pathname;
      return path === "/api/auth/me" ? json(200, me) : json(404, { detail: "not_found" });
    }),
  );
}
const get = (path: string) => new Request(url(path), { headers: { Authorization: "Bearer t" } });
const send = (method: string, path: string, body?: unknown) =>
  new Request(url(path), { method, headers: { "Content-Type": "application/json", Authorization: "Bearer t" }, body: body === undefined ? undefined : JSON.stringify(body) });
async function call(list: Parameters<typeof getResponse>[0], req: Request) {
  const res = (await getResponse(list, req))!;
  return { status: res.status, body: (await res.json()) as Record<string, unknown> };
}

// ------------------------------------------------------------------------------------------------ t181

describe("t181: handler MSW N-PA — hình dạng hợp đồng (parser FE đọc được), lỗi đúng mã", () => {
  it("strategy: GET (eval_mode false, llm_calibrated false); PUT 422 reason/strategy, 409 same_as_current, 200 + lịch sử thêm dòng; không policy:edit → 403", async () => {
    resetStrategyMock();
    stubMe(MGR);
    const view = parseStrategyView((await call(strategyHandlers, get("/api/admin/strategy"))).body);
    expect([view.strategy, view.eval_mode, view.llm_calibrated]).toStrictEqual(["hybrid", false, false]);
    expect(await call(strategyHandlers, send("PUT", "/api/admin/strategy", { strategy: "rule_only", reason: "  ngắn  " }))).toStrictEqual({
      status: 422,
      body: { error: "invalid_request", fields: ["reason"] },
    });
    expect((await call(strategyHandlers, send("PUT", "/api/admin/strategy", { strategy: "llm_only", reason: "Lý do đủ mười ký tự." }))).body.fields).toStrictEqual(["strategy"]);
    expect(await call(strategyHandlers, send("PUT", "/api/admin/strategy", { strategy: "hybrid", reason: "Lý do đủ mười ký tự." }))).toStrictEqual({
      status: 409,
      body: { detail: "same_as_current" },
    });
    const ok = await call(strategyHandlers, send("PUT", "/api/admin/strategy", { strategy: "rule_only", reason: "  Lý do đủ mười ký tự.  " }));
    expect(ok.status).toBe(200);
    expect(parseStrategyView(ok.body)).toMatchObject({ strategy: "rule_only", changed_by: "quan.tm", reason: "Lý do đủ mười ký tự." });
    const history = parseStrategyHistory((await call(strategyHandlers, get("/api/admin/strategy/history?limit=50"))).body);
    expect(history.items[0]).toMatchObject({ strategy_from: "hybrid", strategy_to: "rule_only", changed_by: "quan.tm" });
    expect(history.truncated).toBe(false);
    expect((await call(strategyHandlers, get("/api/admin/strategy/history?limit=1"))).body.truncated).toBe(true);
    stubMe(READER);
    expect((await call(strategyHandlers, send("PUT", "/api/admin/strategy", { strategy: "hybrid", reason: "Lý do đủ mười ký tự." }))).status).toBe(403);
    resetStrategyMock();
  });

  it("strategies: real|sim, source trả lại đúng, 17 khoá đúng thứ tự, 1 ô mẫu < 20, 1 ô null, intent_mix khác giữa cột; source lạ → 422", async () => {
    stubMe(MGR);
    const q = "from=2026-10-20T00:00:00.000%2B07:00&to=2026-10-26T12:00:00.000%2B07:00";
    for (const source of ["real", "sim"] as const) {
      const d = parseStrategies((await call(strategyCompareHandlers, get(`/api/dashboard/strategies?${q}&source=${source}`))).body, source);
      expect(d.metrics.map((m) => m.key)).toStrictEqual([...METRIC_KEYS]);
      const cells = d.metrics.flatMap((m) => Object.values(m.values));
      expect(cells.filter((c) => c === null)).toHaveLength(1);
      expect(cells.filter((c) => c !== null && "den" in c && c.den < 20)).toHaveLength(1);
      const mixes = d.strategies.map((s) => JSON.stringify(d.intent_mix[s]));
      expect(new Set(mixes).size).toBe(3);
    }
    expect((await call(strategyCompareHandlers, get(`/api/dashboard/strategies?${q}&source=all`))).body.fields).toStrictEqual(["query.source"]);
    expect((await call(strategyCompareHandlers, get("/api/dashboard/strategies?from=2026-10-20T00:00:00&to=x"))).status).toBe(422);
  });

  it("queue: ≥ 2 trang ca mở (cursor nối), danh sách đã đóng; limit > 100 / after sai → 422; close 200 → rời danh sách mở", async () => {
    stubMe(L2);
    const p1 = parseQueuePage((await call(escalationQueueHandlers, get("/api/escalations/queue?status=open&limit=50"))).body, "open");
    expect(p1.items).toHaveLength(50);
    expect(p1.next_cursor).not.toBeNull();
    const p2 = parseQueuePage((await call(escalationQueueHandlers, get(`/api/escalations/queue?status=open&limit=50&after=${p1.next_cursor}`))).body, "open");
    expect(p2.next_cursor).toBeNull();
    expect(new Set([...p1.items, ...p2.items].map((i) => i.escalation_id)).size).toBe(p1.items.length + p2.items.length);
    expect(parseQueuePage((await call(escalationQueueHandlers, get("/api/escalations/queue?status=closed"))).body, "closed").items.length).toBeGreaterThan(0);
    expect((await call(escalationQueueHandlers, get("/api/escalations/queue?limit=101"))).body.fields).toStrictEqual(["query.limit"]);
    expect((await call(escalationQueueHandlers, get("/api/escalations/queue?after=zzz"))).body.fields).toStrictEqual(["query.after"]);
    const target = escalationStore.list("open").find((i) => i.exit_code === "E3")!;
    const closed = await call(escalationCloseHandlers, send("POST", `/api/escalations/${target.escalation_id}/close`, { close_result: "completed", note: "xong" }));
    expect(closed.status).toBe(200);
    expect(escalationStore.list("open").some((i) => i.escalation_id === target.escalation_id)).toBe(false);
    expect((await call(escalationCloseHandlers, send("POST", `/api/escalations/${target.escalation_id}/close`, { close_result: "completed", note: "xong" }))).status).toBe(409);
  });

  it("danh sách handler: business / ai vẫn KHÔNG có handler (route thật M9 A3); route N-PA có", async () => {
    stubMe(MGR);
    const w = "from=2026-09-25T00:00:00.000%2B07:00&to=2026-10-01T12:00:00.000%2B07:00";
    expect(await getResponse(handlers, get(`/api/dashboard/business?${w}`))).toBeUndefined();
    expect(await getResponse(handlers, get(`/api/dashboard/ai?${w}`))).toBeUndefined();
    expect(await getResponse(handlers, get(`/api/dashboard/strategies?${w}&source=real`))).toBeDefined();
    expect(await getResponse(handlers, get("/api/admin/strategy"))).toBeDefined();
  });
});

// ------------------------------------------------------------------------------------------------ t182

describe("t182: không còn chữ 'Phase 7' hiển thị trong mã nguồn giao diện (ngoài chú thích)", () => {
  it("bỏ chú thích // và /* */ rồi tìm 'Phase 7' trong mọi file src (không test, không mocks)", () => {
    const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}"], { query: "?raw", import: "default", eager: true });
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    const stripComments = (code: string) =>
      code
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .split("\n")
        .map((line) => line.replace(/(^|[^:"'`])\/\/.*$/, "$1"))
        .join("\n");
    const hits = Object.entries(sources).filter(([, code]) => /Phase\s*7/.test(stripComments(code))).map(([f]) => f);
    expect(hits).toStrictEqual([]);
  });
});
