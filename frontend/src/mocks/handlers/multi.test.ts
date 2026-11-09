// t78 / t133: handler giả nhiều ý (F6 P6; N-T20 P5 — route thật T20b, MSW chỉ minh hoạ ca lỗi) — chạy trực tiếp bằng
// `getResponse` của MSW, không service worker, không mạng. Lời gọi backend THẬT của handler (`/api/auth/me` qua bypass) đi
// vào fetch giả.
import { getResponse, isPassthroughResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { parseTicketView } from "../../api/tickets.ts";
import type { Me, TicketView } from "../../api/types.ts";
import { aggregate, summaryText } from "../fixtures/multi.ts";
import { awaitingFields, multiHandlers, resetMultiTickets, shapeFields } from "./employee-multi.ts";

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

  it("GET đầu = cha đang chờ các ý (3 trạng thái khác nhau, chưa tin nào); GET hai = round 1 (confirm / answer / none) — đúng hợp đồng T20b", async () => {
    stubBackend(EMPLOYEE);
    const first = await view(ID);
    expect([first.status, first.waiting_for, first.final_state, first.conversation.length]).toStrictEqual(["S_CLASSIFYING", null, null, 0]);
    expect(first.children_progress?.map((p) => p.progress)).toStrictEqual(["ready", "pending_approval", "processing"]);
    const round1 = await view(ID);
    expect([round1.status, round1.waiting_for, round1.exit_code, round1.close_reason]).toStrictEqual(["S_CONFIRMING", "reply", null, null]);
    const digest = round1.conversation[0] as { kind: string; round: number; text: string; items: Record<string, unknown>[] };
    expect([digest.kind, digest.round]).toStrictEqual(["digest", 1]);
    expect(digest.items.map((i) => [i.child_id, i.needs])).toStrictEqual([
      [c(1), "confirm"],
      [c(2), "answer"],
      [c(3), "none"],
    ]);
    // t133: đúng 6 khoá của `compose_digest` — không options / sources; `text` = các dòng "Ý i – title: text"; tiêu đề kiểu
    // `child_title`; dải tiến độ không có outcome "blocked"; cả thân qua bộ kiểm chặt của giao diện.
    for (const item of digest.items) expect(Object.keys(item).sort()).toStrictEqual(["child_id", "index", "kind", "needs", "text", "title"]);
    expect(digest.text.split("\n")).toStrictEqual(digest.items.map((i) => `Ý ${String(i.index)} – ${String(i.title)}: ${String(i.text)}`));
    expect(round1.children_progress?.map((p) => p.title)).toStrictEqual(["Đặt lại mật khẩu", "Cài đặt phần mềm", "Cấp quyền truy cập"]);
    expect(parseTicketView(round1, ID)).toBe(round1);
    expect(round1.children_progress?.map((p) => [p.progress, p.outcome])).toStrictEqual([
      ["needs_user", null],
      ["needs_user", null],
      ["closed", "rejected"],
    ]);
  });

  it("t133 thân sai → 422 như route thật: khoá sai dạng → body.items (chung); hình dạng Pydantic → items.<cid>.<Nhánh>.<trường>; lệch awaiting → body.items.<cid> sắp theo id", async () => {
    stubBackend(EMPLOYEE);
    await toRound1();
    const cases: [unknown, string[]][] = [
      [[], [""]],
      [{ ...ROUND1_OK, force: true }, ["<extra>"]],
      [{ items: {} }, ["items"]],
      [{ items: { ...ROUND1_OK.items, "mật khẩu: Abc123": { confirmed: true } } }, ["body.items"]], // khoá người gửi không bị dội
      [{ items: { ...ROUND1_OK.items, [`${ID}-x`]: { confirmed: true } } }, ["body.items"]],
      [{ items: { ...ROUND1_OK.items, [`${ID}-100`]: { confirmed: true } } }, ["body.items"]],
      [{ items: { ...ROUND1_OK.items, [c(3)]: { confirmed: true } } }, [`body.items.${c(3)}`]],
      [{ items: { [c(1)]: { confirmed: true } } }, [`body.items.${c(2)}`]],
      [{ items: { [c(1)]: { answer: "x" }, [c(2)]: { answer: "LAP-0342" } } }, [`body.items.${c(1)}`]],
      [{ items: { [c(1)]: { confirmed: true }, [c(2)]: { confirmed: true } } }, [`body.items.${c(2)}`]],
      [
        { items: { [c(1)]: { confirmed: "yes" }, [c(2)]: { answer: "LAP-0342" } } },
        [`items.${c(1)}.ReplyAnswer.answer`, `items.${c(1)}.ReplyAnswer.<extra>`, `items.${c(1)}.ReplyConfirm.confirmed`],
      ],
      [
        { items: { [c(1)]: { confirmed: false, note: "n".repeat(1001) }, [c(2)]: { answer: "LAP-0342" } } },
        [`items.${c(1)}.ReplyAnswer.answer`, `items.${c(1)}.ReplyAnswer.<extra>`, `items.${c(1)}.ReplyConfirm.note`],
      ],
      [
        { items: { [c(1)]: { confirmed: true }, [c(2)]: { answer: "" } } },
        [`items.${c(2)}.ReplyAnswer.answer`, `items.${c(2)}.ReplyConfirm.confirmed`, `items.${c(2)}.ReplyConfirm.<extra>`],
      ],
    ];
    for (const [body, fields] of cases) {
      const res = await post(ID, body);
      expect(res?.status, JSON.stringify(body).slice(0, 80)).toBe(422);
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
    const stale = await post(ID, ROUND1_OK);
    expect(stale?.status).toBe(422); // ý 1 không còn trong awaiting, ý 2 sai loại
    expect(await stale?.json()).toStrictEqual({ error: "invalid_request", fields: [`body.items.${c(1)}`, `body.items.${c(2)}`] });

    expect((await post(ID, { items: { [c(2)]: { confirmed: false, note: " chưa mở được " } } }))?.status).toBe(202);
    const closed = await view(ID);
    expect(closed.conversation.at(-2)).toStrictEqual({ role: "user", text: "Ý 2: Chưa ổn — chưa mở được" });
    // Vòng cuối: tin digest `items: []`, `text` = câu tổng kết (resolved + escalated + rejected → PARTIALLY_ESCALATED).
    expect(closed.conversation.at(-1)).toStrictEqual({
      role: "assistant",
      kind: "digest",
      round: 3,
      text: "Đã xong 1/3 yêu cầu; phần còn lại đã chuyển kỹ thuật viên.",
      items: [],
    });
    expect(parseTicketView(closed, ID)).toBe(closed);
    expect([closed.status, closed.final_state, closed.waiting_for]).toStrictEqual(["S_RESOLVED", "S_RESOLVED", null]);
    expect(Number.isNaN(Date.parse(closed.closed_at ?? ""))).toBe(false);
    expect(closed.children_progress?.map((p) => p.outcome)).toStrictEqual(["resolved", "escalated", "rejected"]);
    expect((await post(ID, { items: { [c(2)]: { confirmed: true } } }))?.status).toBe(409); // trả muộn sau khi cha đóng
  });

  it("-422 → thân đúng vẫn 422 tại ý 2 (dạng thật body.items.<cid>); -409 → 409; trước round (đang xử lý) → 409; thiếu ticket:message → 403", async () => {
    stubBackend(EMPLOYEE);
    const bad = "tkt-demo-multi-422";
    expect((await post(bad, { items: { [c(1, bad)]: { confirmed: true } } }))?.status).toBe(409); // chưa tới round 1
    await toRound1(bad);
    const res = await post(bad, { items: { [c(1, bad)]: { confirmed: true }, [c(2, bad)]: { answer: "PC-1107" } } });
    expect(res?.status).toBe(422);
    expect(await res?.json()).toStrictEqual({ error: "invalid_request", fields: [`body.items.${c(2, bad)}`] });

    const late = "tkt-demo-multi-409";
    await toRound1(late);
    const res409 = await post(late, { items: { [c(1, late)]: { confirmed: true }, [c(2, late)]: { answer: "PC-1107" } } });
    expect(res409?.status).toBe(409);
    expect(await res409?.json()).toStrictEqual({ detail: "Yêu cầu đã chuyển sang bước khác" });

    stubBackend(NO_MESSAGE);
    const forbidden = await post(ID, ROUND1_OK);
    expect(forbidden?.status).toBe(403);
  });

  it("shapeFields / awaitingFields + bảng đóng cha + câu tổng kết 5.2.5", () => {
    expect(shapeFields("p", { items: { "p-1": { confirmed: true } } })).toStrictEqual([]);
    expect(shapeFields("p", { items: null })).toStrictEqual(["items"]);
    expect(shapeFields("p", { items: { "p-1": { confirmed: true }, "q-1": { confirmed: true } } })).toStrictEqual(["body.items"]);
    expect(awaitingFields({ "p-2": { answer: "a" }, "p-1": { confirmed: true } }, { "p-1": "confirm", "p-2": "answer" })).toStrictEqual([]);
    expect(awaitingFields({ "p-10": { confirmed: true } }, { "p-1": "confirm", "p-2": "answer" })).toStrictEqual(["body.items.p-1", "body.items.p-10", "body.items.p-2"]);
    expect(summaryText(["resolved", "resolved"])).toBe("Cả 2 yêu cầu đã hoàn tất.");
    expect(summaryText(["resolved", "rejected", "resolved"])).toBe("Đã xong 2/3 yêu cầu; có yêu cầu không được duyệt.");
    expect(summaryText(["escalated", "rejected"])).toBe("Các yêu cầu không xử lý tự động được (chuyển kỹ thuật viên hoặc không được duyệt).");
    expect(aggregate(["resolved", "resolved", "resolved"])).toBe("S_RESOLVED");
    expect(aggregate(["resolved", "escalated", "rejected"])).toBe("S_RESOLVED");
    expect(aggregate(["escalated", "escalated"])).toBe("S_ESCALATED");
    expect(aggregate(["rejected", "rejected"])).toBe("S_REJECTED");
    expect(aggregate(["escalated", "rejected"])).toBe("S_ESCALATED");
  });
});
