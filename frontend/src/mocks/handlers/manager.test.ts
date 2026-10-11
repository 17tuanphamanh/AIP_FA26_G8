// t65 — handler giả F5 (chỉ nạp ở dev:mock): policy (Phase 7). Dashboard + alerts đã là route thật M9 A3 — handler giả và
// phần t65 của chúng đã xoá (N-A3). Chạy handler trực tiếp bằng `getResponse` của MSW — không service worker, không mạng.
// Lời gọi backend THẬT của handler (`/api/auth/me` qua bypass) đi vào fetch giả.
import { getResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Me, PolicyVersionItem, PolicyView } from "../../api/types.ts";
import { POLICY_JSON } from "../fixtures/policy.ts";
import { handlers } from "./index.ts";
import { policyHandlers, policyIssues, resetPolicy } from "./policy.ts";

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

beforeEach(() => {
  resetPolicy();
});

describe("t65: handler policy (Q-fe-26) — 4 phiên bản; PUT 409/422/201; quay lui = TẠO bản mới, bản cũ nguyên", () => {
  const versions = async () => (await (await getResponse(policyHandlers, get("/api/policy/versions")))!.json()) as PolicyVersionItem[];
  const current = async () => (await (await getResponse(policyHandlers, get("/api/policy")))!.json()) as PolicyView;

  it("GET: bản đang áp dụng '4' = config/policy.json; 4 phiên bản, đúng 1 đang áp dụng; bản 3 khôi phục từ bản 1", async () => {
    stubMe(READER);
    const view = await current();
    expect([view.version_id, view.version, view.is_current]).toStrictEqual([14, "4", true]);
    expect(view.content).toStrictEqual(POLICY_JSON);
    expect(Object.keys(view.content)).toStrictEqual(["constants", "business_hours", "rules"]);
    const list = await versions();
    expect(list.map((v) => v.version)).toStrictEqual(["4", "3", "2", "1"]);
    expect(list.filter((v) => v.is_current)).toHaveLength(1);
    expect(list.find((v) => v.version === "3")?.restored_from).toBe("1");
    // policy:read không ghi được.
    expect((await getResponse(policyHandlers, send("PUT", "/api/policy", { content: POLICY_JSON, base_version_id: 14 })))?.status).toBe(403);
  });

  it("kiểm nghĩa giả: ngưỡng dưới ≥ ngưỡng trên, type sai, id trùng → loc đúng (tính từ gốc nội dung)", () => {
    const bad = JSON.parse(JSON.stringify(POLICY_JSON)) as typeof POLICY_JSON;
    bad.constants.THRESHOLD_LOW = 0.85;
    (bad.rules[2] as { type: string }).type = "aproval_required";
    bad.rules[4]!.id = "R17";
    expect(policyIssues(bad)).toStrictEqual([
      { loc: ["constants", "THRESHOLD_LOW"], msg: "Ngưỡng dưới 0.85 phải nhỏ hơn ngưỡng trên 0.75" },
      { loc: ["rules", 2, "type"], msg: 'type "aproval_required" không hợp lệ — chỉ allow, approval_required, deny' },
      { loc: ["rules", 4, "id"], msg: 'id "R17" trùng với luật thứ 2' },
    ]);
    expect(policyIssues(POLICY_JSON)).toStrictEqual([]);
    expect(policyIssues([])).toStrictEqual([{ loc: [], msg: "Nội dung chính sách phải là một object JSON" }]);
  });

  it("PUT: thừa khoá → 422 invalid_request; base cũ → 409 version_conflict; sai nghĩa → 422 invalid_policy; đúng → 201 bản '5'", async () => {
    stubMe(MGR);
    const put = (body: unknown) => getResponse(policyHandlers, send("PUT", "/api/policy", body));
    expect(await (await put({ content: POLICY_JSON, base_version_id: 14, force: true }))!.json()).toStrictEqual({ error: "invalid_request", fields: ["body.force"] });
    const conflict = (await put({ content: POLICY_JSON, base_version_id: 13 }))!;
    expect([conflict.status, await conflict.json()]).toStrictEqual([409, { detail: "version_conflict" }]);
    const invalid = (await put({ content: { ...POLICY_JSON, constants: { ...POLICY_JSON.constants, THRESHOLD_HIGH: 0.1 } }, base_version_id: 14 }))!;
    expect(invalid.status).toBe(422);
    expect(await invalid.json()).toMatchObject({ error: "invalid_policy", errors: [{ loc: ["constants", "THRESHOLD_LOW"] }] });
    const ok = (await put({ content: { ...POLICY_JSON, constants: { ...POLICY_JSON.constants, SLA_MINUTES: 35 } }, base_version_id: 14 }))!;
    expect([ok.status, await ok.json()]).toStrictEqual([201, { version_id: 15, version: "5" }]);
    expect((await current()).version).toBe("5");
    expect((await versions()).filter((v) => v.is_current).map((v) => v.version)).toStrictEqual(["5"]);
  });

  it("quay lui bản 2 → danh sách +1, bản mới đang áp dụng (restored_from '2', nội dung = bản 2); bản 2 còn nguyên; id lạ → 404", async () => {
    stubMe(MGR);
    const before = await versions();
    const v2Before = before.find((v) => v.version === "2")!;
    const res = (await getResponse(policyHandlers, send("POST", "/api/policy/versions/12/restore")))!;
    expect([res.status, await res.json()]).toStrictEqual([201, { version_id: 15, version: "5" }]);
    const after = await versions();
    expect(after).toHaveLength(before.length + 1);
    const created = after.find((v) => v.version_id === 15)!;
    expect([created.is_current, created.restored_from, created.updated_by]).toStrictEqual([true, "2", "it_mgr01"]);
    expect(after.filter((v) => v.is_current)).toHaveLength(1);
    expect(after.find((v) => v.version === "2")).toStrictEqual({ ...v2Before, is_current: false });
    const view = await current();
    expect((view.content as { constants: { SLA_MINUTES: number } }).constants.SLA_MINUTES).toBe(20); // nội dung bản 2
    expect((await getResponse(policyHandlers, send("POST", "/api/policy/versions/999/restore")))?.status).toBe(404);
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
