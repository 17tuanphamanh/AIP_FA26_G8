// t65 — handler policy (route THẬT F7, N-POL1): KHÔNG nạp ở dev:mock, chỉ cho test — soát nó khớp hình dạng route thật.
// Dashboard + alerts đã là route thật M9 A3 — handler giả và phần t65 của chúng đã xoá (N-A3). Chạy handler trực tiếp
// bằng `getResponse` của MSW — không service worker, không mạng. Lời gọi backend THẬT của handler (`/api/auth/me` qua
// bypass) đi vào fetch giả.
import { getResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { getPolicy, listPolicyVersions, validatePolicy } from "../../api/policy.ts";
import { createClient } from "../../api/client.ts";
import type { Me, PolicyVersionItem, PolicyView } from "../../api/types.ts";
import { DEMO_VERSION, POLICY_DEMO } from "../fixtures/policy.ts";
import { handlers } from "./index.ts";
import { policyHandlers, policyIssues } from "./policy.ts";

const BASE = ["ticket:create", "ticket:read:own"];
const MGR: Me = { user_id: "it_mgr01", role: "manager", permissions: [...BASE, "policy:read", "policy:edit", "dashboard:read:all", "alert:read"] };
const READER: Me = { ...MGR, permissions: MGR.permissions.filter((p) => p !== "policy:edit") };

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
  new Request(url(path), {
    method,
    headers: { "Content-Type": "application/json", Authorization: "Bearer t" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

describe("t65: handler policy = hình dạng route thật F7 (đọc, mảng trần, validate 422/403/413), luật mẫu trung tính", () => {
  const versions = async () => (await (await getResponse(policyHandlers, get("/api/policy/versions")))!.json()) as PolicyVersionItem[];
  const current = async () => (await (await getResponse(policyHandlers, get("/api/policy")))!.json()) as PolicyView;
  const validate = (body: unknown) => getResponse(policyHandlers, send("POST", "/api/policy/validate", body));

  it("GET: ĐÚNG 6 khoá, bản file (version_id 0, updated_by null, is_current); /versions MẢNG TRẦN 1 mục, restored_from null", async () => {
    stubMe(READER);
    const view = await current();
    expect(Object.keys(view).sort()).toStrictEqual(["content", "is_current", "updated_at", "updated_by", "version", "version_id"]);
    expect([view.version_id, view.version, view.updated_by, view.is_current]).toStrictEqual([0, DEMO_VERSION, null, true]);
    expect(view.version).toMatch(/^file-[0-9a-f]{8}$/);
    expect(view.content).toStrictEqual(POLICY_DEMO);
    const list = await versions();
    expect(Array.isArray(list)).toBe(true);
    expect(list).toStrictEqual([{ version_id: 0, version: DEMO_VERSION, updated_by: null, updated_at: view.updated_at, is_current: true, restored_from: null }]);
  });

  it("fixture KHÔNG chép luật thật: mọi luật intent 'demo', id không phải R…, không có business_hours", () => {
    expect(POLICY_DEMO.rules.every((r) => r.intent === "demo" && !/^R\d+$/.test(r.id))).toBe(true);
    expect(Object.keys(POLICY_DEMO)).toStrictEqual(["constants", "rules"]);
  });

  it("validate: policy:read → 403 forbidden; policy:edit + hợp lệ → 200 {valid, version_preview}; không có PUT/restore", async () => {
    stubMe(READER);
    const denied = (await validate({ content: POLICY_DEMO }))!;
    expect([denied.status, await denied.json()]).toStrictEqual([403, { detail: "forbidden" }]);
    stubMe(MGR);
    const ok = (await validate({ content: POLICY_DEMO }))!;
    const body = (await ok.json()) as { valid: boolean; version_preview: string };
    expect(ok.status).toBe(200);
    expect(Object.keys(body).sort()).toStrictEqual(["valid", "version_preview"]);
    expect(body.valid).toBe(true);
    expect(body.version_preview).toMatch(/^file-[0-9a-f]{8}$/);
    expect(await getResponse(policyHandlers, send("PUT", "/api/policy", { content: POLICY_DEMO }))).toBeUndefined();
    expect(await getResponse(policyHandlers, send("POST", "/api/policy/versions/0/restore"))).toBeUndefined();
  });

  it("validate: sai nghĩa → 422 invalid_policy, loc từ gốc nội dung; sai hình dạng → 422 invalid_request; > 64 KB → 413", async () => {
    stubMe(MGR);
    const bad = { ...POLICY_DEMO, constants: { ...POLICY_DEMO.constants, THRESHOLD_LOW: 0.9 }, rules: [POLICY_DEMO.rules[0], { ...POLICY_DEMO.rules[1], type: "alow" }] };
    const res = (await validate({ content: bad }))!;
    expect(res.status).toBe(422);
    expect(await res.json()).toStrictEqual({
      error: "invalid_policy",
      errors: [
        { loc: ["constants"], msg: "Value error, THRESHOLD_LOW phải nhỏ hơn THRESHOLD_HIGH" },
        { loc: ["rules", 1, "type"], msg: "Input should be 'allow', 'approval_required' or 'deny'" },
      ],
    });
    const shape = (await validate({ content: [], extra: 1 }))!;
    expect([shape.status, await shape.json()]).toStrictEqual([422, { error: "invalid_request", fields: ["<extra>", "content"] }]);
    const big = (await validate({ content: { ...POLICY_DEMO, note: "x".repeat(70_000) } }))!;
    expect([big.status, await big.json()]).toStrictEqual([413, { detail: "payload_too_large" }]);
    expect(policyIssues(POLICY_DEMO)).toStrictEqual([]);
  });

  it("api/policy.ts đi qua handler: getPolicy / listPolicyVersions / validatePolicy nhận đúng hình dạng (fail-closed không bắt nhầm)", async () => {
    const me = vi.fn(async () => json(200, MGR));
    const fetch = vi.fn(async (input: string, init: RequestInit = {}) => {
      if (input === "/api/auth/me") return me();
      const request = new Request(url(input), init);
      vi.stubGlobal("fetch", vi.fn(async () => json(200, MGR))); // bypass `/api/auth/me` của handler
      return (await getResponse(policyHandlers, request)) ?? json(404, { detail: "Not Found" });
    });
    const client = createClient({ fetch, readCookie: () => null, locks: null, channel: null, onSessionEnd: vi.fn() });
    expect((await getPolicy(client)).version).toBe(DEMO_VERSION);
    expect((await listPolicyVersions(client)).map((v) => v.version_id)).toStrictEqual([0]);
    expect((await validatePolicy(POLICY_DEMO, client)).valid).toBe(true);
  });
});

describe("t118 (P11): route thật M9 A3 không còn handler giả — dashboard, alerts đi thẳng backend ở dev:mock", () => {
  it("getResponse(handlers) của 5 lời gọi Tổng quan / Cảnh báo → undefined (không handler nào khớp)", async () => {
    stubMe(MGR);
    const window = "from=2026-09-25T00:00:00.000%2B07:00&to=2026-10-01T12:00:00.000%2B07:00";
    for (const request of [
      get("/api/alerts?status=open"),
      get("/api/alerts"),
      send("POST", "/api/alerts/1/ack"),
      get(`/api/dashboard/business?${window}`),
      get(`/api/dashboard/ai?${window}`),
    ]) {
      expect(await getResponse(handlers, request)).toBeUndefined();
    }
  });

  it("4 file mock đã xoá không còn; không file nguồn nào (ngoài test) import chúng", () => {
    const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}"], { query: "?raw", import: "default", eager: true });
    const files = Object.keys(sources);
    expect(files.length).toBeGreaterThan(50); // glob thật sự đọc được mã nguồn
    expect(files.filter((f) => /\/mocks\/(handlers|fixtures)\/(alerts|dashboard)\.ts$/.test(f))).toStrictEqual([]);
    const importsDeleted = /from\s+["'][^"']*\/(handlers|fixtures)\/(alerts|dashboard)(\.ts)?["']/;
    expect(files.filter((f) => importsDeleted.test(sources[f]!))).toStrictEqual([]);
  });
});
