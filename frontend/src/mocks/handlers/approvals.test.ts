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

describe("handler hộp thư / xem phiếu (4c P5, P6)", () => {
  it("list: thiếu mine=1 → 422; L2 → 403; có Date; trả theo created_at giảm dần (KHÔNG theo hạn) — đủ fixture bắt buộc", async () => {
    stubBackend(L2);
    expect((await getResponse(approvalHandlers, get("/api/approvals?mine=1&status=pending")))?.status).toBe(403);
    stubBackend(L1);
    expect((await getResponse(approvalHandlers, get("/api/approvals?status=pending")))?.status).toBe(422);
    const res = (await getResponse(approvalHandlers, get("/api/approvals?mine=1&status=pending")))!;
    expect(Number.isNaN(Date.parse(res.headers.get("Date") ?? ""))).toBe(false);
    const items = (await res.json()) as ApprovalListItem[];
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
    const approved = (await (await getResponse(approvalHandlers, get("/api/approvals?mine=1&status=approved")))!.json()) as ApprovalListItem[];
    expect(approved.length).toBeGreaterThan(0);
  });

  it("view: plan_changed → 409 không kèm object; id lạ → 404; phiếu thường có procedure + action", async () => {
    stubBackend(L1);
    const changed = (await getResponse(approvalHandlers, get("/api/approvals/apv-demo-04")))!;
    expect(changed.status).toBe(409);
    expect(await changed.json()).toStrictEqual({ detail: "plan_changed" });
    expect((await getResponse(approvalHandlers, get("/api/approvals/apv-khac")))?.status).toBe(404);
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
