// t78: handler giả nhiều ý (F6 P6) — chạy trực tiếp bằng `getResponse` của MSW, không service worker, không mạng.
// Lời gọi backend THẬT của handler (`/api/auth/me` qua bypass) đi vào fetch giả.
import { getResponse, isPassthroughResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me, TicketView } from "../../api/types.ts";
import { aggregate } from "../fixtures/multi.ts";
import { multiHandlers, replyFields, resetMultiTickets } from "./employee-multi.ts";

afterEach(() => resetMultiTickets());

const EMPLOYEE: Me = { user_id: "nv001", role: "employee", permissions: ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"] };
const NO_MESSAGE: Me = { user_id: "x", role: "employee", permissions: ["ticket:create"] };

const url = (path: string) => new URL(path, location.href).toString();
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function stubBackend(me: Me) {
  const seen: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: Request | string) => {
      const path = new URL(typeof input === "string" ? input : input.url, location.href).pathname;
      seen.push(path);
      return path === "/api/auth/me" ? json(200, me) : json(404, { detail: "not_found" });
    }),
  );
  return seen;
}

const get = (id: string) => getResponse(multiHandlers, new Request(url(`/api/tickets/${id}`), { headers: { Authorization: "Bearer t" } }));
const post = (id: string, body: unknown) =>
  getResponse(
    multiHandlers,
    new Request(url(`/api/tickets/${id}/reply`), {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer t" },
      body: JSON.stringify(body),
    }),
  );
const view = async (id: string) => (await (await get(id))!.json()) as TicketView;

const ID = "tkt-demo-multi-1";
const c = (n: number, id = ID) => `${id}-${n}`;
const ROUND1_OK = { items: { [c(1)]: { confirmed: true }, [c(2)]: { answer: "LAP-0342" } } };

/** Đưa ticket tới round 1 (GET đầu = đang xử lý, GET hai = round 1). */
async function toRound1(id = ID) {
  await get(id);
  return view(id);
}

describe("t78: handler nhiều ý — chỉ id tkt-demo-multi-, kiểm thân chặt, máy trạng thái P1 §8.2", () => {
  it.each([
    ["uuid", crypto.randomUUID()],
    ["gần giống", "tkt-demo-multi"],
    ["tiền tố ở giữa", "x-tkt-demo-multi-1"],
    ["fixture F4", "tkt-demo-open"],
  ])("id %s → GET và POST /reply đều passthrough, không gọi gì (kể cả /me)", async (_name, id) => {
    const seen = stubBackend(EMPLOYEE);
    for (const res of [await get(id), await post(id, ROUND1_OK)]) expect(res === undefined || isPassthroughResponse(res)).toBe(true);
    expect(seen).toStrictEqual([]);
  });

  it("id lạ trong tiền tố → 404; mọi response giả có header Date", async () => {
    stubBackend(EMPLOYEE);
    const res = await get("tkt-demo-multi-zzz");
    expect(res?.status).toBe(404);
    expect(Number.isNaN(Date.parse((await get(ID))?.headers.get("Date") ?? ""))).toBe(false);
  });

  it("GET đầu = cha đang chờ các ý (3 trạng thái khác nhau, chưa tin nào); GET hai = round 1 (confirm / answer + options / none)", async () => {
    stubBackend(EMPLOYEE);
    const first = await view(ID);
    expect([first.status, first.waiting_for, first.final_state, first.conversation.length]).toStrictEqual(["S_CLASSIFYING", null, null, 0]);
    expect(first.children_progress?.map((p) => p.progress)).toStrictEqual(["ready", "pending_approval", "processing"]);
    const round1 = await view(ID);
    expect([round1.status, round1.waiting_for, round1.exit_code, round1.close_reason]).toStrictEqual(["S_CONFIRMING", "reply", null, null]);
    const digest = round1.conversation[0] as { kind: string; round: number; items: { child_id: string; needs: string; options?: string[] }[] };
    expect([digest.kind, digest.round]).toStrictEqual(["digest", 1]);
    expect(digest.items.map((i) => [i.child_id, i.needs])).toStrictEqual([
      [c(1), "confirm"],
      [c(2), "answer"],
      [c(3), "none"],
    ]);
    expect(digest.items[1]!.options).toStrictEqual(["LAP-0342", "PC-1107"]);
    expect(round1.children_progress?.map((p) => [p.progress, p.outcome])).toStrictEqual([
      ["needs_user", null],
      ["needs_user", null],
      ["closed", "rejected"],
    ]);
  });

  it("thân sai → 422 đúng vị trí: khoá thừa (đỉnh / items / trong ý), thiếu ý, ý ngoài awaiting, sai kiểu, rỗng, quá dài", async () => {
    stubBackend(EMPLOYEE);
    await toRound1();
    const cases: [unknown, string[]][] = [
      [[], ["body"]],
      [{ ...ROUND1_OK, force: true }, ["body.<extra>"]],
      [{ items: { ...ROUND1_OK.items, [c(3)]: { confirmed: true } } }, ["body.items.<extra>"]],
      [{ items: { [c(1)]: { confirmed: true } } }, [`body.items.${c(2)}`]],
      [{ items: { [c(1)]: { confirmed: "yes" }, [c(2)]: { answer: "LAP-0342" } } }, [`body.items.${c(1)}.confirmed`]],
      [{ items: { [c(1)]: { answer: "x" }, [c(2)]: { answer: "LAP-0342" } } }, [`body.items.${c(1)}.<extra>`, `body.items.${c(1)}.confirmed`]],
      [{ items: { [c(1)]: { confirmed: false, note: "n".repeat(1001) }, [c(2)]: { answer: "LAP-0342" } } }, [`body.items.${c(1)}.note`]],
      [{ items: { [c(1)]: { confirmed: true }, [c(2)]: { answer: "   " } } }, [`body.items.${c(2)}.answer`]],
      [{ items: { [c(1)]: { confirmed: true }, [c(2)]: { answer: "LAP-0342", note: "x" } } }, [`body.items.${c(2)}.<extra>`]],
    ];
    for (const [body, fields] of cases) {
      const res = await post(ID, body);
      expect(res?.status).toBe(422);
      expect(await res?.json()).toStrictEqual({ error: "invalid_request", fields });
    }
    expect((await view(ID)).waiting_for).toBe("reply"); // thân sai không đổi trạng thái
  });

  it("chuỗi đủ: reply 2 khoá → tin user + ý 2 chạy tiếp → round 2 CHỈ ý 2 → reply 2 khoá cũ = 422 → reply 1 khoá → cha đóng", async () => {
    stubBackend(EMPLOYEE);
    await toRound1();
    const ok = await post(ID, ROUND1_OK);
    expect(ok?.status).toBe(202);
    expect(await ok?.json()).toStrictEqual({ ticket_id: ID, status: "S_CONFIRMING", notices: [] });

    const working = await view(ID);
    expect([working.status, working.waiting_for]).toStrictEqual(["S_CLASSIFYING", null]);
    expect(working.conversation.at(-1)).toStrictEqual({ role: "user", text: "Ý 1: Đã ổn · Ý 2: LAP-0342" });
    expect(working.children_progress?.map((p) => [p.progress, p.outcome])).toStrictEqual([
      ["closed", "resolved"],
      ["processing", null],
      ["closed", "rejected"],
    ]);
    expect((await post(ID, ROUND1_OK))?.status).toBe(409); // cha không ở parent_reply_wait

    const round2 = await view(ID);
    expect(round2.waiting_for).toBe("reply");
    const digest2 = round2.conversation.at(-1) as { round: number; items: { child_id: string; needs: string; text: string }[] };
    expect(digest2.round).toBe(2);
    expect(digest2.items.map((i) => [i.child_id, i.needs])).toStrictEqual([[c(2), "confirm"]]);
    expect(digest2.items[0]!.text).toContain("LAP-0342");
    expect((await post(ID, ROUND1_OK))?.status).toBe(422); // ý 1 không còn trong awaiting

    expect((await post(ID, { items: { [c(2)]: { confirmed: false, note: " chưa mở được " } } }))?.status).toBe(202);
    const closed = await view(ID);
    expect(closed.conversation.at(-1)).toStrictEqual({ role: "user", text: "Ý 2: Chưa ổn — chưa mở được" });
    expect([closed.status, closed.final_state, closed.waiting_for]).toStrictEqual(["S_RESOLVED", "S_RESOLVED", null]);
    expect(Number.isNaN(Date.parse(closed.closed_at ?? ""))).toBe(false);
    expect(closed.children_progress?.map((p) => p.outcome)).toStrictEqual(["resolved", "escalated", "rejected"]);
    expect((await post(ID, { items: { [c(2)]: { confirmed: true } } }))?.status).toBe(409); // trả muộn sau khi cha đóng
  });

  it("-422 → thân hợp lệ vẫn 422 tại ý 2; -409 → 409; trước round (đang xử lý) → 409; thiếu ticket:message → 403", async () => {
    stubBackend(EMPLOYEE);
    const bad = "tkt-demo-multi-422";
    expect((await post(bad, { items: { [c(1, bad)]: { confirmed: true } } }))?.status).toBe(409); // chưa tới round 1
    await toRound1(bad);
    const res = await post(bad, { items: { [c(1, bad)]: { confirmed: true }, [c(2, bad)]: { answer: "PC-1107" } } });
    expect(res?.status).toBe(422);
    expect(await res?.json()).toStrictEqual({ error: "invalid_request", fields: [`body.items.${c(2, bad)}.answer`] });

    const late = "tkt-demo-multi-409";
    await toRound1(late);
    const res409 = await post(late, { items: { [c(1, late)]: { confirmed: true }, [c(2, late)]: { answer: "PC-1107" } } });
    expect(res409?.status).toBe(409);
    expect(await res409?.json()).toStrictEqual({ detail: "Yêu cầu đã chuyển sang bước khác" });

    stubBackend(NO_MESSAGE);
    const forbidden = await post(ID, ROUND1_OK);
    expect(forbidden?.status).toBe(403);
  });

  it("replyFields + bảng đóng cha B5", () => {
    expect(replyFields({ items: {} }, {})).toStrictEqual([]);
    expect(replyFields({ items: null }, { a: "answer" })).toStrictEqual(["body.items"]);
    expect(aggregate(["resolved", "resolved", "resolved"])).toBe("S_RESOLVED");
    expect(aggregate(["resolved", "escalated", "rejected"])).toBe("S_RESOLVED");
    expect(aggregate(["escalated", "escalated"])).toBe("S_ESCALATED");
    expect(aggregate(["rejected", "rejected"])).toBe("S_REJECTED");
    expect(aggregate(["escalated", "rejected"])).toBe("S_ESCALATED");
  });
});
