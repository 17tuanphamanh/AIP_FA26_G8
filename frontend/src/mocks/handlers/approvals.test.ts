// t49 + handler giả F4 (chỉ nạp ở dev:mock). Chạy handler trực tiếp bằng `getResponse` của MSW — không service worker,
// không mạng. Lời gọi backend THẬT của handler (`/api/auth/me`, `/api/tickets/{id}` qua bypass) đi vào fetch giả.
import { getResponse, isPassthroughResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { ApprovalListItem, Me } from "../../api/types.ts";
import { approvalHandlers } from "./approvals.ts";
import { overrideHandlers } from "./override.ts";

const L1: Me = { user_id: "l1_01", role: "l1", permissions: ["approval:decide", "decision:override", "ticket:read:any"] };
const L2: Me = { user_id: "l2_01", role: "l2", permissions: ["escalation:handle", "ticket:read:any"] };

const url = (path: string) => new URL(path, location.href).toString();
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

/** Backend thật giả lập cho lời gọi `bypass` của handler: `/api/auth/me` trả `me`; ticket thật theo `tickets`. */
function stubBackend(me: Me, tickets: Record<string, { final_state: string | null }> = {}) {
  const seen: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const path = new URL(typeof input === "string" ? input : input.url, location.href).pathname;
      seen.push(path);
      if (path === "/api/auth/me") return json(200, me);
      const ticket = /^\/api\/tickets\/(.+)$/.exec(path)?.[1];
      if (ticket && tickets[ticket]) return json(200, { ticket_id: ticket, ...tickets[ticket] });
      return json(404, { detail: "not_found" });
    }),
  );
  return seen;
}

const post = (path: string, body: unknown) =>
  new Request(url(path), { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer t" }, body: JSON.stringify(body) });
const get = (path: string) => new Request(url(path), { headers: { Authorization: "Bearer t" } });

describe("t49: decision cho id KHÔNG tiền tố apv-demo- → handler không chặn (passthrough)", () => {
  it.each([["uuid ngẫu nhiên", crypto.randomUUID()], ["gần giống", "apv-demo"], ["tiền tố ở giữa", "x-apv-demo-01"], ["hoa", "APV-DEMO-01"]])(
    "%s → passthrough, không gọi gì (kể cả /me)",
    async (_name, id) => {
      const seen = stubBackend(L1);
      const res = await getResponse(approvalHandlers, post(`/api/approvals/${id}/decision`, { decision: "approved" }));
      expect(res === undefined || isPassthroughResponse(res)).toBe(true);
      expect(seen).toStrictEqual([]);
    },
  );

  it("id apv-demo- → handler chặn: 202 + header Date; từ chối thiếu note → 422 rejected_requires_note", async () => {
    stubBackend(L1);
    const bad = await getResponse(approvalHandlers, post("/api/approvals/apv-demo-03/decision", { decision: "rejected", reason_code: "other", note: " " }));
    expect(bad?.status).toBe(422);
    expect(await bad?.json()).toStrictEqual({ detail: "rejected_requires_note" });
    const extra = await getResponse(approvalHandlers, post("/api/approvals/apv-demo-03/decision", { decision: "approved", force: true }));
    expect(await extra?.json()).toStrictEqual({ error: "invalid_request", fields: ["body.force"] });
    const ok = await getResponse(approvalHandlers, post("/api/approvals/apv-demo-03/decision", { decision: "approved" }));
    expect(isPassthroughResponse(ok!)).toBe(false);
    expect(ok?.status).toBe(202);
    expect(Number.isNaN(Date.parse(ok?.headers.get("Date") ?? ""))).toBe(false);
    // Đã quyết → lần sau 409 đúng câu của backend.
    const again = await getResponse(approvalHandlers, post("/api/approvals/apv-demo-03/decision", { decision: "approved" }));
    expect(again?.status).toBe(409);
    expect(await again?.json()).toStrictEqual({ detail: "Yêu cầu đã chuyển sang bước khác" });
  });
});

/** Backend thật giả lập cho lời gọi `bypass`: `/api/auth/me` → `me`; `/api/approvals` như route 4c (quyền → `mine` /
 *  `status` → 200 `{items}` + header Date) hoặc theo `inbox` truyền vào. Trả các URL (đường dẫn + query) đã gọi. */
const REAL_DATE = "Wed, 30 Sep 2026 14:00:00 GMT"; // KHÁC giờ hiện tại → biết header Date lấy từ đâu
const STATUSES = ["pending", "approved", "rejected", "timeout"];
type Real = (url: URL, request: Request) => Response | Promise<Response>;

function realInbox(me: Me, items: unknown[] = []): Real {
  return (url) => {
    if (!me.permissions.includes("approval:decide")) return json(403, { detail: "forbidden" });
    const status = url.searchParams.get("status");
    const fields = [
      ...(url.searchParams.get("mine") === "1" ? [] : ["query.mine"]),
      ...(status === null || STATUSES.includes(status) ? [] : ["query.status"]),
    ];
    if (fields.length) return json(422, { error: "invalid_request", fields });
    return new Response(JSON.stringify({ items }), { status: 200, headers: { "Content-Type": "application/json", Date: REAL_DATE } });
  };
}

function stubReal(me: Me, inbox: Real = realInbox(me)) {
  const calls: { url: string; auth: string | null; headers: string[] }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const request = typeof input === "string" ? new Request(new URL(input, location.href)) : input;
      const url = new URL(request.url);
      calls.push({ url: `${url.pathname}${url.search}`, auth: request.headers.get("Authorization"), headers: [...request.headers.keys()] });
      if (url.pathname === "/api/auth/me") return json(200, me);
      if (url.pathname === "/api/approvals") return inbox(url, request);
      return json(404, { detail: "not_found" });
    }),
  );
  return calls;
}

const isDemo = (id: string) => id.startsWith("apv-demo-");

describe("handler hộp thư / xem phiếu (4c P5, P6)", () => {
  it("list (thật trả {items: []}): thiếu mine=1 → 422 của thật; L2 → 403 của thật; Date; minh hoạ theo created_at giảm dần (KHÔNG theo hạn) — đủ fixture bắt buộc", async () => {
    stubReal(L2);
    expect((await getResponse(approvalHandlers, get("/api/approvals?mine=1&status=pending")))?.status).toBe(403);
    stubReal(L1);
    expect((await getResponse(approvalHandlers, get("/api/approvals?status=pending")))?.status).toBe(422);
    const res = (await getResponse(approvalHandlers, get("/api/approvals?mine=1&status=pending")))!;
    expect(Number.isNaN(Date.parse(res.headers.get("Date") ?? ""))).toBe(false);
    const items = ((await res.json()) as { items: ApprovalListItem[] }).items;
    const created = items.map((i) => Date.parse(i.created_at));
    expect(created).toStrictEqual([...created].sort((a, b) => b - a));
    const deadlines = items.map((i) => Date.parse(i.deadline));
    expect(deadlines).not.toStrictEqual([...deadlines].sort((a, b) => a - b)); // giao diện phải tự sắp
    const now = Date.now();
    const urgent = items.filter((i) => {
      const d = Date.parse(i.deadline);
      const c = Date.parse(i.created_at);
      return d - now < 0.2 * (d - c);
    });
    expect(urgent.length).toBeGreaterThan(0); // có phiếu còn < 20%
    expect(items.some((i) => i.role_as === "backup" && i.reminder_2_at)).toBe(true);
    const approved = (await (await getResponse(approvalHandlers, get("/api/approvals?mine=1&status=approved")))!.json()) as { items: ApprovalListItem[] };
    expect(approved.items.length).toBeGreaterThan(0);
  });

  it("view: plan_changed → 409 không kèm object; id lạ có tiền tố → 404; phiếu thường có procedure + action", async () => {
    stubReal(L1);
    const changed = (await getResponse(approvalHandlers, get("/api/approvals/apv-demo-04")))!;
    expect(changed.status).toBe(409);
    expect(await changed.json()).toStrictEqual({ detail: "plan_changed" });
    expect((await getResponse(approvalHandlers, get("/api/approvals/apv-demo-khac")))?.status).toBe(404);
    const view = (await (await getResponse(approvalHandlers, get("/api/approvals/apv-demo-01")))!.json()) as Record<string, unknown>;
    expect(view.procedure).toStrictEqual({ doc_id: "KB-VPN-004", title: "Gia hạn và cấp lại chứng chỉ VPN" });
    expect((view.action as { params: unknown }).params).toStrictEqual({ device_id: "LAP-0342" });
  });
});

describe("handler ghi đè (4d P1–P4) — kết quả cho F4-6", () => {
  const body = { override_decision: "HITL", reason_code: "too_risky_for_auto" };

  it("tkt-demo-open → 409 ticket_open; tkt-demo-same → 422 same_as_original; tkt-demo-reauth → 403 lần đầu, 201 lần sau, 409 lần ba", async () => {
    stubBackend(L1);
    const run = async (id: string, b: unknown = body) => {
      const res = (await getResponse(overrideHandlers, post(`/api/tickets/${id}/override`, b)))!;
      return [res.status, ((await res.json()) as { detail?: string }).detail ?? null];
    };
    expect(await run("tkt-demo-open")).toStrictEqual([409, "ticket_open"]);
    expect(await run("tkt-demo-same")).toStrictEqual([422, "same_as_original"]);
    expect(await run("tkt-demo-reauth")).toStrictEqual([403, "reauth_required"]);
    expect(await run("tkt-demo-reauth", { ...body, reason_code: "other" })).toStrictEqual([422, null]); // Khác thiếu note
    expect(await run("tkt-demo-reauth")).toStrictEqual([201, null]);
    expect(await run("tkt-demo-reauth")).toStrictEqual([409, "already_overridden"]);
  });

  it("ticket thật: không có → 404; chưa kết thúc → 409 ticket_open; đã kết thúc → 201; không có decision:override → 403", async () => {
    stubBackend(L1, { "t-open": { final_state: null }, "t-done": { final_state: "S_RESOLVED" } });
    const status = async (id: string) => (await getResponse(overrideHandlers, post(`/api/tickets/${id}/override`, body)))?.status;
    expect(await status("t-none")).toBe(404);
    expect(await status("t-open")).toBe(409);
    expect(await status("t-done")).toBe(201);
    stubBackend(L2);
    expect(await status("t-done")).toBe(403);
  });
});

// ------------------------------------------------------------------------------------------------ t84 (N4c P6a)

describe("t84: handler hộp thư LUÔN gọi backend thật trước; lỗi thật trả nguyên; chỉ gộp minh hoạ khi thật 2xx hợp lệ", () => {
  const A: ApprovalListItem = {
    approval_id: "412",
    ticket_id: "6a1c2e4f-0b3d-4e5f-8a7b-9c0d1e2f3a4b",
    status: "pending",
    created_at: "2026-09-30T13:50:00Z",
    deadline: "2026-09-30T14:20:00Z",
    reminder_1_at: null,
    reminder_2_at: null,
    role_as: "primary",
    action_type: null,
    device_id: null,
  };
  const call = async (path: string) => (await getResponse(approvalHandlers, get(path)))!;

  it("thật 200 {items:[A]} → {items: [A, …minh hoạ lọc status]}; header Date = của thật; gọi thật đúng URL + query, chỉ mang Authorization", async () => {
    const calls = stubReal(L1, realInbox(L1, [A]));
    const res = await call("/api/approvals?mine=1&status=pending");
    expect(res.status).toBe(200);
    expect(res.headers.get("Date")).toBe(REAL_DATE);
    const items = ((await res.json()) as { items: ApprovalListItem[] }).items;
    expect(items[0]).toStrictEqual(A); // phần thật đứng đầu, nguyên vẹn
    const demo = items.slice(1);
    // Trạng thái quyết định của handler nằm trong bộ nhớ module (t49 cùng file đã quyết apv-demo-03) → kiểm theo id.
    expect(demo.map((i) => i.approval_id)).toEqual(expect.arrayContaining(["apv-demo-01", "apv-demo-02", "apv-demo-04", "apv-demo-08"]));
    expect(demo.every((i) => isDemo(i.approval_id) && i.status === "pending")).toBe(true);
    expect(demo.some((i) => i.action_type === null && i.device_id === null)).toBe(true); // ca P3 (apv-demo-08)
    expect(items.map((i) => i.approval_id)).not.toContain("apv-demo-viewer"); // phiếu giám sát không nằm trong hộp thư
    expect(calls).toStrictEqual([{ url: "/api/approvals?mine=1&status=pending", auth: "Bearer t", headers: expect.any(Array) }]);
    // Chỉ Authorization của request gốc; `accept: msw/passthrough` là dấu bypass do chính MSW thêm (msw/lib/utils/bypass).
    expect(calls[0]!.headers.map((h) => h.toLowerCase()).sort()).toStrictEqual(["accept", "authorization"]);
  });

  it("không có status → minh hoạ đủ mọi trạng thái; status=approved → chỉ approved", async () => {
    stubReal(L1, realInbox(L1, []));
    const all = ((await (await call("/api/approvals?mine=1")).json()) as { items: ApprovalListItem[] }).items;
    expect(new Set(all.map((i) => i.status))).toStrictEqual(new Set(["pending", "approved", "rejected", "timeout"]));
    const approved = ((await (await call("/api/approvals?mine=1&status=approved")).json()) as { items: ApprovalListItem[] }).items;
    expect(approved.length).toBeGreaterThan(0);
    expect(approved.every((i) => i.status === "approved")).toBe(true);
  });

  it.each([
    ["403 forbidden (không có approval:decide)", 403, { detail: "forbidden" }],
    ["401 (token hết hạn → client tự refresh)", 401, { detail: "unauthorized" }],
    ["422 query.status", 422, { error: "invalid_request", fields: ["query.status"] }],
    ["500 lỗi máy chủ", 500, { detail: "internal" }],
  ])("thật %s → trả NGUYÊN mã + thân, không gộp minh hoạ", async (_name, status, body) => {
    stubReal(L1, () => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", server: "uvicorn" } }));
    const res = await call("/api/approvals?mine=1&status=pending");
    expect(res.status).toBe(status);
    expect(await res.json()).toStrictEqual(body);
    expect(res.headers.get("server")).toBe("uvicorn");
  });

  it("thật 200 nhưng thân sai dạng (mảng trần / không phải JSON) → trả nguyên thân để client báo lỗi", async () => {
    stubReal(L1, () => json(200, [A]));
    const bare = await call("/api/approvals?mine=1&status=pending");
    expect(bare.status).toBe(200);
    expect(await bare.json()).toStrictEqual([A]);
    stubReal(L1, () => new Response("<html>proxy</html>", { status: 200, headers: { "Content-Type": "text/html" } }));
    const html = await call("/api/approvals?mine=1&status=pending");
    expect(await html.text()).toBe("<html>proxy</html>");
  });

  it("lỗi mạng (fetch ném — backend tắt) → 503 backend_unreachable, KHÔNG trả riêng minh hoạ", async () => {
    stubReal(L1, () => {
      throw new TypeError("Failed to fetch");
    });
    const res = await call("/api/approvals?mine=1&status=pending");
    expect(res.status).toBe(503);
    expect(await res.json()).toStrictEqual({ detail: "backend_unreachable" });
  });

  it("thiếu mine → handler VẪN gọi thật và trả nguyên 422 query.mine của thật", async () => {
    const calls = stubReal(L1);
    const res = await call("/api/approvals?status=pending");
    expect(res.status).toBe(422);
    expect(await res.json()).toStrictEqual({ error: "invalid_request", fields: ["query.mine"] });
    expect(calls.map((c) => c.url)).toStrictEqual(["/api/approvals?status=pending"]);
  });
});

// ------------------------------------------------------------------------------------------------ t85 (N4c P6b, P6c)

describe("t85: xem phiếu chỉ chặn id apv-demo-; id khác → passthrough; phiếu giám sát + phiếu thiếu dữ liệu đúng hình thật", () => {
  it.each([["số BIGINT của phiếu thật", "412"], ["uuid", crypto.randomUUID()], ["không tiền tố", "apv-khac"], ["hoa", "APV-DEMO-01"]])(
    "%s → passthrough, không gọi gì (kể cả /me), không trả fixture",
    async (_name, id) => {
      const calls = stubReal(L1);
      const res = await getResponse(approvalHandlers, get(`/api/approvals/${id}`));
      expect(res === undefined || isPassthroughResponse(res)).toBe(true);
      expect(calls).toStrictEqual([]);
    },
  );

  it("apv-demo-01 → fixture (12 khoá như ApprovalView); apv-demo-viewer → role_as viewer, pending; apv-demo-08 → các trường null", async () => {
    stubReal(L1);
    const view = async (id: string) => (await (await getResponse(approvalHandlers, get(`/api/approvals/${id}`)))!.json()) as Record<string, unknown>;
    const normal = await view("apv-demo-01");
    expect(Object.keys(normal).sort()).toStrictEqual(
      ["action", "action_plan_hash", "approval_id", "deadline", "facts", "procedure", "request_summary", "requester", "risk", "role_as", "status", "ticket_id"],
    );
    expect(normal.approval_id).toBe("apv-demo-01");
    const watcher = await view("apv-demo-viewer");
    expect([watcher.role_as, watcher.status]).toStrictEqual(["viewer", "pending"]);
    const sparse = await view("apv-demo-08");
    expect([(sparse.requester as { department: unknown }).department, sparse.risk, sparse.procedure]).toStrictEqual([null, null, null]);
    expect(typeof sparse.action_plan_hash).toBe("string");
  });

  it("không có approval:decide → 403 (như require của route thật)", async () => {
    stubReal(L2);
    expect((await getResponse(approvalHandlers, get("/api/approvals/apv-demo-01")))?.status).toBe(403);
  });

  it("decision: 202 có decided_as theo vai trò của fixture; phiếu giám sát → 403 forbidden", async () => {
    stubReal(L1);
    const decide = async (id: string) => (await getResponse(approvalHandlers, post(`/api/approvals/${id}/decision`, { decision: "approved" })))!;
    const primary = await decide("apv-demo-08");
    expect(primary.status).toBe(202);
    expect(((await primary.json()) as { decided_as: string }).decided_as).toBe("primary");
    const backup = await decide("apv-demo-02");
    expect(((await backup.json()) as { decided_as: string }).decided_as).toBe("backup");
    const watcher = await decide("apv-demo-viewer");
    expect(watcher.status).toBe(403);
    expect(await watcher.json()).toStrictEqual({ detail: "forbidden" });
  });
});
