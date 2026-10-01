// t65 — handler giả F5 (chỉ nạp ở dev:mock): dashboard, alerts, policy. Chạy handler trực tiếp bằng `getResponse` của
// MSW — không service worker, không mạng. Lời gọi backend THẬT của handler (`/api/auth/me` qua bypass) đi vào fetch giả.
import { getResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AlertItem, BusinessDashboard, Me, PolicyVersionItem, PolicyView } from "../../api/types.ts";
import { ALERT_ACKED_ELSEWHERE_ID, ALERT_GONE_ID } from "../fixtures/alerts.ts";
import { POLICY_JSON } from "../fixtures/policy.ts";
import { alertHandlers, resetAlerts } from "./alerts.ts";
import { dashboardHandlers, MONITOR_COOKIE, monitorDown, parseWindow } from "./dashboard.ts";
import { policyHandlers, policyIssues, resetPolicy } from "./policy.ts";

const BASE = ["ticket:create", "ticket:read:own"];
const MGR: Me = { user_id: "it_mgr01", role: "manager", permissions: [...BASE, "policy:read", "policy:edit", "dashboard:read:all", "alert:read"] };
const READER: Me = { ...MGR, permissions: MGR.permissions.filter((p) => p !== "policy:edit") };
const L1: Me = { user_id: "l1_01", role: "l1", permissions: [...BASE, "approval:decide", "dashboard:read:own"] };

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

const W7 = "from=2026-09-25T00:00:00.000%2B07:00&to=2026-10-01T12:00:00.000%2B07:00";

beforeEach(() => {
  resetAlerts();
  resetPolicy();
});


describe("t65: handler dashboard (M9 §4.5, §5.1) — quyền, from/to, 503 bằng cookie, fixture đủ 3 ca P3", () => {
  it("L1 (chỉ dashboard:read:own) → 403; thiếu múi giờ / from ≥ to / > 90 ngày → 422", async () => {
    stubMe(L1);
    expect((await getResponse(dashboardHandlers, get(`/api/dashboard/business?${W7}`)))?.status).toBe(403);
    expect(parseWindow(url("/api/dashboard/business?from=2026-09-25T00:00:00&to=2026-10-01T12:00:00%2B07:00"))).toStrictEqual({ fields: ["query.from"] });
    expect(parseWindow(url("/api/dashboard/business?from=2026-10-01T00:00:00%2B07:00&to=2026-09-01T00:00:00%2B07:00"))).toStrictEqual({ fields: ["query.from", "query.to"] });
    expect(parseWindow(url("/api/dashboard/business?from=2026-01-01T00:00:00%2B07:00&to=2026-10-01T00:00:00%2B07:00"))).toStrictEqual({ fields: ["query.from", "query.to"] });
    stubMe(MGR);
    expect((await getResponse(dashboardHandlers, get("/api/dashboard/business?from=2026-09-25&to=2026-10-01")))?.status).toBe(422);
  });

  it("7 ngày: override_count ∈ unavailable (null); escalation_rate_weighted null ∉ unavailable; approval_expired_count = 0 thật; E3 tkt-demo-", async () => {
    stubMe(MGR);
    const res = (await getResponse(dashboardHandlers, get(`/api/dashboard/business?${W7}`)))!;
    expect(res.status).toBe(200);
    const body = (await res.json()) as BusinessDashboard;
    expect(body.from).toBe("2026-09-25T00:00:00.000+07:00");
    expect(body.unavailable).toStrictEqual(["override_count"]);
    expect(body.override_count).toBeNull();
    expect(body.escalation_rate_weighted).toBeNull();
    expect(body.approval_expired_count).toBe(0);
    expect(body.e3_cases?.every((c) => c.ticket_id.startsWith("tkt-demo-"))).toBe(true);
  });

  it(`khoá ${MONITOR_COOKIE}=unavailable → monitorDown (503 monitor_unavailable); giá trị khác / không có → không`, async () => {
    // Trình duyệt: MSW đọc `cookies` từ document.cookie (request same-origin). Trong Node (vitest) MSW không có kho cookie
    // và happy-dom bỏ header Cookie → kiểm hàm quyết định ở đây; đường đọc cookie thật do verify F5-4 kiểm.
    expect(monitorDown({ [MONITOR_COOKIE]: "unavailable" })).toBe(true);
    expect(monitorDown({ [MONITOR_COOKIE]: "1" })).toBe(false);
    expect(monitorDown({})).toBe(false);
    stubMe(MGR);
    expect((await getResponse(dashboardHandlers, get(`/api/dashboard/ai?${W7}`)))?.status).toBe(200);
  });
});

describe("t65: handler alerts (§4.5) — ack 200 → 409 lần 2 (acked_by giữ người đầu); id đặc biệt 409 / 404", () => {
  const ack = (id: number) => getResponse(alertHandlers, send("POST", `/api/alerts/${id}/ack`));
  const openIds = async () => ((await (await getResponse(alertHandlers, get("/api/alerts?status=open")))!.json()) as AlertItem[]).map((a) => a.alert_id);

  it("không có alert:read → 403; status lạ → 422; trả theo alert_id tăng dần (giao diện tự sắp mức độ)", async () => {
    stubMe(L1);
    expect((await getResponse(alertHandlers, get("/api/alerts?status=open")))?.status).toBe(403);
    stubMe(MGR);
    expect((await getResponse(alertHandlers, get("/api/alerts?status=x")))?.status).toBe(422);
    const ids = await openIds();
    expect(ids).toStrictEqual([...ids].sort((a, b) => a - b));
    expect(ids).toContain(ALERT_ACKED_ELSEWHERE_ID);
    expect(ids).toContain(ALERT_GONE_ID);
  });

  it("ack 1001 → 200 acked_by = người gọi; lần 2 → 409, acked_by không đổi; id lạ → 404", async () => {
    stubMe(MGR);
    const first = (await ack(1001))!;
    expect(first.status).toBe(200);
    const acked = (await first.json()) as AlertItem;
    expect([acked.status, acked.acked_by]).toStrictEqual(["acked", "it_mgr01"]);
    stubMe({ ...MGR, user_id: "it_mgr02" });
    const again = (await ack(1001))!;
    expect(again.status).toBe(409);
    const all = (await (await getResponse(alertHandlers, get("/api/alerts")))!.json()) as AlertItem[];
    expect(all.find((a) => a.alert_id === 1001)?.acked_by).toBe("it_mgr01");
    expect((await ack(123456))?.status).toBe(404);
    expect(await openIds()).not.toContain(1001);
  });

  it("ALERT_ACKED_ELSEWHERE_ID → 409 rồi danh sách mở không còn; ALERT_GONE_ID → 404 rồi biến mất hẳn", async () => {
    stubMe(MGR);
    expect((await ack(ALERT_ACKED_ELSEWHERE_ID))?.status).toBe(409);
    expect(await openIds()).not.toContain(ALERT_ACKED_ELSEWHERE_ID);
    expect((await ack(ALERT_GONE_ID))?.status).toBe(404);
    const all = (await (await getResponse(alertHandlers, get("/api/alerts")))!.json()) as AlertItem[];
    expect(all.some((a) => a.alert_id === ALERT_GONE_ID)).toBe(false);
  });
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
