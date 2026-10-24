// api/events.ts: kiểm dạng sự kiện, định tuyến vào đúng khối (reducer), kết nối (Last-Event-ID, 404, đóng không có sự kiện cuối) và
// `client.open` (xác thực + làm mới token khi 401). Không gọi mạng thật.
import { afterEach, describe, expect, it, vi } from "vitest";
import { done, frame, messageEnd, sseResponse, status, thought, token, toolCall, waiting, wire } from "../routes/employee/streamTestKit.ts";
import { createClient } from "./client.ts";
import {
  connectTicketStream,
  EMPTY_VIEW,
  parseStreamEvent,
  reduceStream,
  type StreamEvent,
  type StreamOutcome,
  type StreamView,
} from "./events.ts";

afterEach(() => vi.unstubAllGlobals());

const parse = (w: unknown) => parseStreamEvent(JSON.stringify(w));
const feed = (events: StreamEvent[], from: StreamView = EMPTY_VIEW) => events.reduce(reduceStream, from);

describe("parseStreamEvent", () => {
  it("nhận đủ 7 loại", () => {
    expect(parse(status("safety", "Đang kiểm tra an toàn"))).toEqual({ type: "status", step: "safety", label: "Đang kiểm tra an toàn", state: "active" });
    expect(parse(thought("Lý do"))).toEqual({ type: "thought", step: "assess", label: "Lý do" });
    expect(parse(toolCall("Kiểm tra chứng chỉ VPN", false))).toMatchObject({ type: "tool_call", ok: false });
    expect(parse(token("answer:1", "Chào "))).toEqual({ type: "token", messageId: "answer:1", text: "Chào " });
    expect(parse(messageEnd("answer:1"))).toEqual({ type: "message_end", messageId: "answer:1" });
    expect(parse(waiting("approval"))).toEqual({ type: "waiting", label: "Chờ", waitingFor: "approval" });
    expect(parse(done())).toEqual({ type: "done", label: "Hoàn tất" });
    expect(parse(status("diagnose", "x", "done", "t-1"))).toMatchObject({ childId: "t-1" });
  });

  it.each([
    ["JSON hỏng", "{"],
    ["không phải object", "[]"],
    ["loại lạ", JSON.stringify(wire("exfiltrate", { label: "x" }))],
    ["status sai state", JSON.stringify(status("a", "b", "weird"))],
    ["status thiếu label", JSON.stringify({ type: "status", step: "a", data: { state: "done" } })],
    ["tool_call ok không phải bool", JSON.stringify(wire("tool_call", { label: "x", data: { ok: "yes" } }))],
    ["token message_id sai dạng", JSON.stringify(token("../x", "a"))],
    ["token text không phải chuỗi", JSON.stringify(wire("token", { data: { message_id: "answer:1", text: 5 } }))],
    ["token quá dài", JSON.stringify(token("answer:1", "x".repeat(2_001)))],
    ["label quá dài", JSON.stringify(thought("x".repeat(201)))],
    ["waiting thiếu waiting_for", JSON.stringify(wire("waiting", { label: "x", data: {} }))],
  ])("bỏ: %s", (_name, raw) => {
    expect(parseStreamEvent(raw)).toBeNull();
  });
});

describe("reduceStream — mỗi loại vào đúng khối", () => {
  it("status ticket gốc → stepper (cùng step thì cập nhật, không thêm)", () => {
    const view = feed([
      { type: "status", step: "safety", label: "Đang kiểm tra an toàn", state: "active" },
      { type: "status", step: "safety", label: "Đã kiểm tra an toàn", state: "done" },
      { type: "status", step: "understand", label: "Đang tìm hiểu yêu cầu", state: "active" },
    ]);
    expect(view.steps).toEqual([
      { step: "safety", label: "Đã kiểm tra an toàn", state: "done" },
      { step: "understand", label: "Đang tìm hiểu yêu cầu", state: "active" },
    ]);
    expect(view.log).toEqual([]);
    expect(view.messages).toEqual([]);
  });

  it("thought + tool_call → log (ThinkingBox), không vào stepper", () => {
    const view = feed([
      { type: "thought", step: "assess", label: "Lý do A" },
      { type: "tool_call", step: "diagnose", label: "Kiểm tra chứng chỉ VPN", ok: false },
    ]);
    expect(view.log).toEqual([
      { kind: "thought", label: "Lý do A" },
      { kind: "tool_call", label: "Kiểm tra chứng chỉ VPN", ok: false },
    ]);
    expect(view.steps).toEqual([]);
  });

  it("status của ticket con → log có childId, KHÔNG vào stepper", () => {
    const view = feed([{ type: "status", step: "diagnose", label: "Đang kiểm tra hệ thống", state: "active", childId: "t-1" }]);
    expect(view.steps).toEqual([]);
    expect(view.log).toEqual([{ kind: "status", label: "Đang kiểm tra hệ thống", childId: "t-1" }]);
  });

  it("token nối vào đúng tin; message_end đánh dấu xong; token muộn sau message_end bị bỏ (không nhân đôi chữ)", () => {
    let view = feed([
      { type: "token", messageId: "answer:1", text: "Chào " },
      { type: "token", messageId: "answer:1", text: "bạn" },
      { type: "token", messageId: "question:1", text: "Mã máy?" },
      { type: "message_end", messageId: "answer:1" },
    ]);
    expect(view.messages).toEqual([
      { id: "answer:1", kind: "answer", ordinal: 1, text: "Chào bạn", ended: true },
      { id: "question:1", kind: "question", ordinal: 1, text: "Mã máy?", ended: false },
    ]);
    view = feed([{ type: "token", messageId: "answer:1", text: "bạn" }], view);
    expect(view.messages[0]?.text).toBe("Chào bạn");
  });

  it("waiting/done → end; nội dung kế tiếp là lượt mới: xoá bước + log, giữ tin", () => {
    let view = feed([
      { type: "status", step: "safety", label: "a", state: "done" },
      { type: "thought", step: "x", label: "t" },
      { type: "token", messageId: "answer:1", text: "x y" },
      { type: "waiting", label: "Chờ bạn xác nhận kết quả", waitingFor: "confirm" },
    ]);
    expect(view.end).toEqual({ type: "waiting", label: "Chờ bạn xác nhận kết quả", waitingFor: "confirm" });
    expect(view.steps).toHaveLength(1);
    view = feed([{ type: "waiting", label: "Chờ bạn xác nhận kết quả", waitingFor: "confirm" }], view); // gửi lại khi nối lại: không xoá
    expect(view.steps).toHaveLength(1);
    view = feed([{ type: "status", step: "understand", label: "b", state: "active" }], view);
    expect(view.end).toBeNull();
    expect(view.steps.map((s) => s.step)).toEqual(["understand"]);
    expect(view.log).toEqual([]);
    expect(view.messages).toHaveLength(1);
    expect(feed([{ type: "done", label: "Hoàn tất" }]).end).toEqual({ type: "done", label: "Hoàn tất" });
  });
});

describe("connectTicketStream", () => {
  async function run(responder: (url: string, init: RequestInit) => Response | Promise<Response>, lastEventId: string | null = null) {
    const requests: { url: string; headers: Headers }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init: RequestInit = {}) => {
        requests.push({ url, headers: new Headers(init.headers) });
        return responder(url, init);
      }),
    );
    const got: { event: StreamEvent; id: string | undefined }[] = [];
    let opened = 0;
    const outcome: StreamOutcome = await connectTicketStream({
      ticketId: "t 1",
      lastEventId,
      signal: new AbortController().signal,
      onOpen: () => (opened += 1),
      onEvent: (event, id) => got.push({ event, id }),
    });
    return { outcome, got, opened, requests };
  }

  it("gửi Last-Event-ID + Accept, đọc sự kiện kèm id, kết thúc 'ended' sau waiting", async () => {
    const r = await run(
      () => sseResponse([frame(status("safety", "Đang kiểm tra an toàn"), "7.1"), ": hb\n\n", frame(token("answer:1", "a b"), "7.2"), frame(waiting(), undefined)]),
      "6",
    );
    expect(r.requests).toHaveLength(1);
    expect(r.requests[0]?.url).toBe("/api/tickets/t%201/events");
    expect(r.requests[0]?.headers.get("Last-Event-ID")).toBe("6");
    expect(r.requests[0]?.headers.get("Accept")).toContain("text/event-stream");
    expect(r.outcome).toEqual({ kind: "ended" });
    expect(r.opened).toBe(1);
    expect(r.got.map((g) => [g.event.type, g.id])).toEqual([["status", "7.1"], ["token", "7.2"], ["waiting", undefined]]);
  });

  it("sự kiện lạ/sai dạng bị bỏ, không làm đứt luồng", async () => {
    const r = await run(() => sseResponse([frame(wire("exfiltrate"), "1"), "event: status\ndata: {oops\n\n", frame(done(), "2")]));
    expect(r.got.map((g) => g.event.type)).toEqual(["done"]);
    expect(r.outcome).toEqual({ kind: "ended" });
  });

  it("404 → unavailable (không thử lại); 500/403 → refused; sai content-type → error", async () => {
    expect((await run(() => new Response("{}", { status: 404 }))).outcome).toEqual({ kind: "unavailable" });
    const refused = await run(() => new Response("{}", { status: 503 }));
    expect(refused.outcome).toEqual({ kind: "refused", status: 503 });
    expect(refused.requests).toHaveLength(1); // fetchEventSource không tự thử lại
    expect((await run(() => new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } }))).outcome).toEqual({ kind: "error" });
  });

  it("đóng mà chưa có done/waiting → closed; lỗi mạng → error; huỷ → aborted", async () => {
    expect((await run(() => sseResponse([frame(status("a", "b"), "1")]))).outcome).toEqual({ kind: "closed" });
    expect((await run(() => Promise.reject(new TypeError("network")))).outcome).toEqual({ kind: "error" });
    const abort = new AbortController();
    vi.stubGlobal("fetch", vi.fn((_u: string, init: RequestInit) => new Promise<Response>((_res, rej) => init.signal?.addEventListener("abort", () => rej(new DOMException("a", "AbortError"))))));
    const pending = connectTicketStream({ ticketId: "t", lastEventId: null, signal: abort.signal, onOpen: () => undefined, onEvent: () => undefined });
    abort.abort();
    expect(await pending).toEqual({ kind: "aborted" });
  });
});

describe("client.open — xác thực như client hiện có", () => {
  const ok = (access: string) =>
    new Response(JSON.stringify({ access_token: access, token_type: "bearer", expires_in: 900, csrf_token: "c" }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });

  it("gắn Bearer; 401 → làm mới token rồi gửi lại ĐÚNG một lần; trả Response thô chưa đọc thân", async () => {
    const seen: (string | null)[] = [];
    const fetch = vi.fn(async (url: string, init: RequestInit = {}) => {
      if (url === "/api/auth/login") return ok("old");
      if (url === "/api/auth/refresh") return ok("new");
      seen.push(new Headers(init.headers).get("Authorization"));
      return seen.at(-1) === "Bearer new" ? sseResponse([frame(done(), "1")]) : new Response("{}", { status: 401 });
    });
    const client = createClient({ fetch, readCookie: () => "csrf-1", locks: null, onSessionEnd: vi.fn() });
    await client.login("an.nv", "pw");
    const res = await client.open("/api/tickets/t/events", { headers: { "Last-Event-ID": "5" } });
    expect(seen).toEqual(["Bearer old", "Bearer new"]);
    expect(res.status).toBe(200);
    expect(res.bodyUsed).toBe(false);
    expect(await res.text()).toContain("event: done");
  });

  it("vẫn 401 sau làm mới → báo hết phiên, trả 401 (không ném, không vòng lặp)", async () => {
    const onSessionEnd = vi.fn();
    const fetch = vi.fn(async (url: string) => (url.startsWith("/api/auth/") ? ok("t") : new Response("{}", { status: 401 })));
    const client = createClient({ fetch, readCookie: () => "csrf-1", locks: null, onSessionEnd });
    await client.login("an.nv", "pw");
    expect((await client.open("/api/tickets/t/events")).status).toBe(401);
    expect(onSessionEnd).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls.filter(([u]) => u === "/api/tickets/t/events")).toHaveLength(2);
  });

  it("chỉ gọi /api/ cùng origin", async () => {
    const client = createClient({ fetch: vi.fn(), readCookie: () => null, locks: null, onSessionEnd: vi.fn() });
    await expect(client.open("https://evil.example/x")).rejects.toThrow();
  });
});
