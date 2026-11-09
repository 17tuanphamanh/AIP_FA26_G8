// Nhật ký quyết định — `parseTrace` (fail-closed) + trang dòng thời gian + nút mở ở 3 màn. Không gọi backend: fetch giả trả
// đúng hình dạng route thật `GET /api/tickets/{id}/trace` (backend/app/api/trace.py, `TicketTrace`).
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useParams } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { approvalQuery } from "../../api/approvals.ts";
import { ApiError } from "../../api/errors.ts";
import { queueQuery } from "../../api/escalations.ts";
import { parseTrace, type TicketTrace, type TraceStep } from "../../api/trace.ts";
import type { Me } from "../../api/types.ts";
import { AuthContext, type AuthValue } from "../../auth/context.ts";
import { RequirePerm } from "../../auth/RequireAuth.tsx";
import { ApprovalTraceLink, EscalationTraceLink, TicketTraceLink, TicketTraceRoute } from "./TicketTrace.tsx";
import { MA_KET_THUC, nhanIT } from "../../lib/nhan.ts";
import { closeNoteLine, TRACE_FORBIDDEN_TEXT, TRACE_INVALID_TEXT, TRACE_NOT_FOUND_TEXT } from "./traceText.ts";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.unstubAllGlobals();
});

const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const L1: Me = {
  user_id: "l1_01",
  role: "l1",
  permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "escalation:handle", "dashboard:read:own", "audit:read:own"],
};
const L2: Me = { user_id: "l2_01", role: "l2", permissions: [...BASE, "ticket:read:any", "escalation:handle", "kb:edit"] };
const EMP: Me = { user_id: "nv001", role: "employee", permissions: BASE };

const EMPTY = { screen: null, classify: null, diagnose: null, sources: null, policy: null, approval: null, execution: null, outcome: null };
const step = (n: number, s: string, event: string, extra: Partial<TraceStep> = {}): TraceStep => ({
  step: s,
  event,
  at: `2099-09-26T01:${String(n).padStart(2, "0")}:00Z`,
  ...EMPTY,
  ...extra,
});

const TRACE: TicketTrace = {
  ticket_id: "T-1",
  is_parent: false,
  parent_ticket_id: null,
  children: [],
  steps: [
    step(1, "B1", "identity_established"),
    step(2, "B2", "screened", { screen: { layer: "llm", p_injection: 0.03, decision: "safe" } }),
    step(3, "B3", "intent_classified", {
      classify: { intent: "vpn", confidence: 0.95, model_probs: { vpn: 0.97, account: 0.02 }, model_version: "intent-clf@1", is_multi: false },
    }),
    step(4, "B6", "diagnosed", { diagnose: { fact_keys: ["cert_expired", "device_registered"] } }),
    step(5, "B10", "deflected_info_only", { sources: [{ doc_id: "KB-VPN-001", title: "Gia hạn chứng chỉ VPN" }] }),
    step(6, "B13/B14", "risk_decided", {
      policy: {
        rule_id: "R18",
        rule_description: "ngoài giờ",
        policy_decision: "approval_required",
        risk_level: "medium",
        decided_by: "rule",
        raw_prob: null,
        calibrated_prob: null,
      },
    }),
    step(7, "B15", "queued", { approval: { approver_id: "l1_01", approver_name: "Lê Thu Hà", result: "pending", at: "2099-09-26T01:07:00Z" } }),
    step(8, "B16", "approved", { approval: { approver_id: "l1_01", approver_name: "Lê Thu Hà", result: "approved", at: "2099-09-26T01:08:00Z" } }),
    step(9, "B18", "executed_ok", {
      execution: { action: "renew_vpn_cert", success: true, rollback_status: "none_needed", calls: [{ name: "renew_vpn_cert", result: "ok" }] },
    }),
    step(10, "B20", "ticket_closed", { outcome: { route: "approved", exit_code: null } }),
  ],
};

const json = (code: number, body: unknown) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

function stub(respond: () => Response): string[] {
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      calls.push(`${init.method ?? "GET"} ${url}`);
      return respond();
    }),
  );
  return calls;
}

const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });

/** Thay cho màn phiếu duyệt thật: một observer của `approvalQuery` cạnh nút (như App.tsx). */
function ApprovalPageStandIn() {
  const { approvalId = "" } = useParams();
  const query = useQuery(approvalQuery(approvalId));
  return <p data-testid="stand-in">{query.data?.ticket_id}</p>;
}

function renderAt(path: string, me: Me = L1, prime?: (client: QueryClient) => void, sibling?: ReactNode) {
  const client = new QueryClient();
  clients.push(client);
  prime?.(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(me)}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route
              path="/trace/:ticketId"
              element={
                <RequirePerm perm="ticket:read:any">
                  <TicketTraceRoute />
                </RequirePerm>
              }
            />
            <Route path="/approvals/ticket/:ticketId" element={<TicketTraceLink />} />
            <Route
              path="/approvals/:approvalId"
              element={
                <>
                  <ApprovalTraceLink />
                  {sibling}
                </>
              }
            />
            <Route path="/escalations/:escalationId" element={<EscalationTraceLink />} />
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}

const NBSP = /[\u00a0\u202f]/g;
const titles = () => screen.getAllByTestId("trace-step-title").map((el) => (el.textContent ?? "").replace(NBSP, " "));

describe("parseTrace — fail-closed", () => {
  it("nhận đúng hình dạng route thật", () => {
    expect(parseTrace(structuredClone(TRACE))).toStrictEqual(TRACE);
  });

  const broken: [string, (t: Record<string, unknown>) => unknown][] = [
    ["không phải object", () => [TRACE]],
    ["thiếu khoá gốc", (t) => ({ ...t, children: undefined })],
    ["thừa khoá gốc (câu người dùng)", (t) => ({ ...t, redacted_request: "Tôi quên mật khẩu" })],
    ["bước thừa khoá (prompt)", (t) => ({ ...t, steps: [{ ...TRACE.steps[0], prompt: "b03_classify@v2" }] })],
    ["bước thiếu khoá", (t) => ({ ...t, steps: [{ step: "B1", event: "x", at: "2099-01-01T00:00:00Z" }] })],
    ["at không phải ngày", (t) => ({ ...t, steps: [{ ...TRACE.steps[0], at: "hôm qua" }] })],
    ["xác suất > 1", (t) => ({ ...t, steps: [step(1, "B2", "x", { screen: { layer: "llm", p_injection: 1.5, decision: "safe" } })] })],
    ["decision ngoài miền", (t) => ({ ...t, steps: [step(1, "B2", "x", { screen: { layer: "llm", p_injection: 0.1, decision: "ok" as never } })] })],
    ["decided_by ngoài miền", (t) => ({ ...t, steps: [step(1, "B13/B14", "x", { policy: { ...TRACE.steps[5]!.policy!, decided_by: "human" as never } })] })],
    ["calls sai kiểu", (t) => ({ ...t, steps: [step(1, "B17", "x", { execution: { ...TRACE.steps[8]!.execution!, calls: "renew" as never } })] })],
    ["con thiếu ticket_id", (t) => ({ ...t, is_parent: true, children: [{ intent: "vpn", exit_code: null }] })],
    ["is_parent không phải boolean", (t) => ({ ...t, is_parent: "false" })],
    ["close_result ngoài miền", (t) => ({ ...t, steps: [step(1, "B20", "escalation_closed", { outcome: { route: null, exit_code: null, close_result: "done" as never } })] })],
    ["close_note không phải chuỗi", (t) => ({ ...t, steps: [step(1, "B20", "escalation_closed", { outcome: { route: null, exit_code: null, close_note: 5 as never } })] })],
    ["outcome thừa khoá (closed_by)", (t) => ({ ...t, steps: [step(1, "B20", "escalation_closed", { outcome: { route: null, exit_code: null, closed_by: "long.nh" } as never })] })],
  ];
  it.each(broken)("%s → 502 invalid_trace_body", (_, mutate) => {
    const body = mutate(structuredClone(TRACE) as unknown as Record<string, unknown>);
    expect(() => parseTrace(body)).toThrowError(ApiError);
    try {
      parseTrace(body);
    } catch (e) {
      expect(e).toMatchObject({ status: 502, code: "invalid_trace_body" });
    }
  });
});

describe("thẻ đóng ca L2 (B20 escalation_closed) — lô N (N7)", () => {
  const closed = (close_result?: "completed" | "confirmed_denial" | "reopened_as_new" | null) =>
    step(1, "B20", "escalation_closed", { outcome: close_result === undefined ? { route: null, exit_code: null } : { route: null, exit_code: null, close_result } });

  it("parseTrace nhận close_result (3 giá trị + null) và nhận khi vắng khoá", () => {
    for (const r of ["completed", "confirmed_denial", "reopened_as_new", null, undefined] as const) {
      const body = { ...TRACE, steps: [closed(r)] };
      expect(parseTrace(structuredClone(body))).toStrictEqual(body);
    }
  });

  it("3 kết quả đóng → 'L2 đã đóng ca · <nhãn đóng ca>'; route null không close_result → 'chưa rõ' như cũ", async () => {
    stub(() => json(200, { ...TRACE, steps: [closed("completed"), closed("confirmed_denial"), closed("reopened_as_new"), closed(null), closed()] }));
    renderAt("/trace/T-1");
    await screen.findAllByTestId("trace-step");
    expect(titles()).toStrictEqual([
      "Kết cục: L2 đã đóng ca · đã hoàn tất",
      "Kết cục: L2 đã đóng ca · xác nhận từ chối",
      "Kết cục: L2 đã đóng ca · mở yêu cầu mới",
      "Kết cục: chưa rõ",
      "Kết cục: chưa rõ",
    ]);
  });
});

describe("QS04 — thẻ B20 không có route: kết cục theo mã thoát", () => {
  const b20 = (outcome: { route: string | null; exit_code: string | null; close_result?: "completed" | null }, event = "ticket_closed") =>
    step(1, "B20", event, { outcome });
  const titleOf = async (outcome: Parameters<typeof b20>[0], event?: string): Promise<string> => {
    stub(() => json(200, { ...TRACE, steps: [b20(outcome, event)] }));
    renderAt("/trace/T-1");
    await screen.findAllByTestId("trace-step");
    const [only] = titles();
    cleanup();
    return only!;
  };

  it("E0 (bị chặn ở B2, S_BLOCKED) → nhãn mã thoát, KHÔNG còn 'chưa rõ'", async () => {
    expect(await titleOf({ route: null, exit_code: "E0" })).toBe("Kết cục: nghi tấn công, đã chặn");
  });

  it("E2 → đúng nhãn E2", async () => {
    expect(await titleOf({ route: null, exit_code: "E2" })).toBe("Kết cục: lỗi khi xử lý (AI hoặc công cụ)");
  });

  it.each(Object.keys(MA_KET_THUC))("%s → nhãn của bảng mã thoát (nhan.ts), không 'chưa rõ'", async (code) => {
    const t = await titleOf({ route: null, exit_code: code });
    expect(t).not.toBe("Kết cục: chưa rõ");
    expect(t.toLocaleLowerCase("vi")).toBe(`kết cục: ${MA_KET_THUC[code]!.nhan.toLocaleLowerCase("vi")}`);
  });

  it("không có exit_code → giữ 'chưa rõ'", async () => {
    expect(await titleOf({ route: null, exit_code: null })).toBe("Kết cục: chưa rõ");
    expect(await titleOf({ route: null, exit_code: "" })).toBe("Kết cục: chưa rõ");
  });

  it("mã lạ → 'Khác · mã' (nguyên mã, không đoán nghĩa; khoá prototype không rơi vào bảng)", async () => {
    expect(await titleOf({ route: null, exit_code: "E42" })).toBe("Kết cục: Khác · E42");
    expect(await titleOf({ route: null, exit_code: "constructor" })).toBe("Kết cục: Khác · constructor");
  });

  it("có route → như cũ (route thắng mã thoát)", async () => {
    expect(await titleOf({ route: "escalated", exit_code: "E5" })).toBe("Kết cục: chuyển kỹ thuật viên L2");
    expect(await titleOf({ route: "approved", exit_code: null })).toBe("Kết cục: xử lý sau khi IT duyệt");
    expect(await titleOf({ route: "auto", exit_code: "E0" })).toBe("Kết cục: tự xử lý");
  });

  it("escalation_closed → như cũ (close_result thắng mã thoát)", async () => {
    expect(await titleOf({ route: null, exit_code: null, close_result: "completed" }, "escalation_closed")).toBe("Kết cục: L2 đã đóng ca · đã hoàn tất");
    expect(await titleOf({ route: null, exit_code: "E5", close_result: "completed" }, "escalation_closed")).toBe("Kết cục: L2 đã đóng ca · đã hoàn tất");
  });

  it("dòng 'Mã kết thúc' dưới thẻ vẫn hiện nhãn + mã", async () => {
    stub(() => json(200, { ...TRACE, steps: [b20({ route: null, exit_code: "E0" })] }));
    renderAt("/trace/T-1");
    expect((await screen.findByTestId("trace-exit")).textContent).toContain("Nghi tấn công, đã chặn");
    expect(screen.getByTestId("trace-exit").textContent).toContain("E0");
  });
});

describe("QS05a — nhãn sự kiện escalation_closed", () => {
  it("bảng SU_KIEN: 'Kỹ thuật viên đóng ca' (hết 'Khác · escalation_closed')", () => {
    expect(nhanIT("su_kien", "escalation_closed")).toStrictEqual({ nhan: "Kỹ thuật viên đóng ca", ma: "escalation_closed" });
    expect(nhanIT("su_kien", "escalation_closed_x").nhan).toBe("Khác");
  });

  it("dòng mã dưới thẻ + tiêu đề (bước không có outcome) dùng nhãn mới", async () => {
    stub(() => json(200, { ...TRACE, steps: [step(1, "B20", "escalation_closed")] }));
    renderAt("/trace/T-1");
    const card = await screen.findByTestId("trace-step");
    const codes = within(card).getByTestId("trace-step-codes").textContent ?? "";
    expect(codes).toContain("Kỹ thuật viên đóng ca");
    expect(codes).toContain("escalation_closed");
    expect(codes).not.toContain("Khác");
    expect(titles()).toStrictEqual(["Ghi nhận và chuyển người: kỹ thuật viên đóng ca"]);
  });
});

describe("QS05b — ghi chú đóng ca của L2 (close_note)", () => {
  const NOTE = "Đã gọi lại người dùng, tài khoản đã mở khoá. SĐT: [SĐT_ĐÃ_ẨN]";
  const closedWith = (close_note?: string | null) =>
    step(1, "B20", "escalation_closed", {
      outcome: { route: null, exit_code: null, close_result: "completed", ...(close_note === undefined ? {} : { close_note }) },
    });
  const renderNote = async (close_note?: string | null) => {
    stub(() => json(200, { ...TRACE, steps: [closedWith(close_note)] }));
    renderAt("/trace/T-1");
    return await screen.findByTestId("trace-step");
  };

  it("parseTrace nhận close_note: chuỗi, null, và vắng khoá", () => {
    for (const note of ["ghi chú", null, undefined] as const) {
      const body = { ...TRACE, steps: [closedWith(note)] };
      expect(parseTrace(structuredClone(body))).toStrictEqual(body);
    }
  });

  it("có ghi chú → dòng 'Ghi chú: <close_note>' ở cuối thẻ", async () => {
    const card = await renderNote(NOTE);
    const line = within(card).getByTestId("trace-close-note");
    expect(line.textContent).toBe(`Ghi chú: ${NOTE}`);
    expect(card.lastElementChild).toBe(line);
    expect(titles()).toStrictEqual(["Kết cục: L2 đã đóng ca · đã hoàn tất"]); // tiêu đề không đổi
  });

  it.each([["null", null], ["rỗng", ""], ["chỉ khoảng trắng", " \n\t "], ["vắng khoá", undefined]] as const)(
    "%s → KHÔNG hiện dòng ghi chú",
    async (_, value) => {
      const card = await renderNote(value);
      expect(within(card).queryByTestId("trace-close-note")).toBeNull();
      expect(card.textContent).not.toContain("Ghi chú");
    },
  );

  it("thẻ B20 thường (không phải đóng ca) không có dòng ghi chú", async () => {
    stub(() => json(200, TRACE));
    renderAt("/trace/T-1");
    await screen.findAllByTestId("trace-step");
    expect(screen.queryByTestId("trace-close-note")).toBeNull();
  });

  it("cắt hiển thị 300 ký tự + '…' (đúng 300 → nguyên văn; 301 → cắt)", async () => {
    const digits = "0123456789".repeat(31); // 310 ký tự, mỗi vị trí phân biệt được
    expect(closeNoteLine({ route: null, exit_code: null, close_note: digits.slice(0, 299) })).toBe(`Ghi chú: ${digits.slice(0, 299)}`);
    expect(closeNoteLine({ route: null, exit_code: null, close_note: digits.slice(0, 300) })).toBe(`Ghi chú: ${digits.slice(0, 300)}`);
    expect(closeNoteLine({ route: null, exit_code: null, close_note: digits.slice(0, 301) })).toBe(`Ghi chú: ${digits.slice(0, 300)}…`);
    expect(closeNoteLine({ route: null, exit_code: null, close_note: digits })).toBe(`Ghi chú: ${digits.slice(0, 300)}…`);
    const card = await renderNote(digits);
    expect(within(card).getByTestId("trace-close-note").textContent).toBe(`Ghi chú: ${digits.slice(0, 300)}…`);
  });

  it("cắt theo ký tự, không chẻ đôi cặp thay thế (emoji ở vị trí 300)", () => {
    const note = `${"a".repeat(299)}😀b`; // 301 ký tự (code point); UTF-16 dài 302
    expect(closeNoteLine({ route: null, exit_code: null, close_note: note })).toBe(`Ghi chú: ${"a".repeat(299)}😀…`);
    expect(closeNoteLine({ route: null, exit_code: null, close_note: `${"a".repeat(299)}😀` })).toBe(`Ghi chú: ${"a".repeat(299)}😀`);
  });

  it("closeNoteLine: không có outcome.close_note → null", () => {
    expect(closeNoteLine({ route: null, exit_code: null })).toBeNull();
    expect(closeNoteLine({ route: null, exit_code: null, close_note: null })).toBeNull();
    expect(closeNoteLine({ route: null, exit_code: null, close_note: "   " })).toBeNull();
  });

  it("chữ từ server hiện THÔ như chữ — không dựng HTML", async () => {
    const card = await renderNote('<img src=x onerror="alert(1)"> <b>đậm</b>');
    expect(within(card).getByTestId("trace-close-note").textContent).toBe('Ghi chú: <img src=x onerror="alert(1)"> <b>đậm</b>');
    expect(card.querySelector("img, b")).toBeNull();
  });
});

describe("trang dòng thời gian", () => {
  it("mỗi bước một thẻ, nhãn tiếng Việt, một GET duy nhất", async () => {
    const calls = stub(() => json(200, TRACE));
    renderAt("/trace/T-1");
    await screen.findAllByTestId("trace-step");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Nhật ký quyết định");
    expect(screen.getAllByTestId("trace-step")).toHaveLength(10);
    expect(titles()).toStrictEqual([
      "Xác thực người gửi: đã xác thực người gửi",
      "Kiểm tra tấn công: an toàn (model 0,03)",
      "Phân loại: VPN — LLM 0,95, model 0,97",
      "Chẩn đoán: dùng 2 dữ kiện",
      "Trả lời từ tài liệu: đã trả lời hướng dẫn",
      "Đánh giá rủi ro: cần duyệt — theo luật",
      "Gửi duyệt: chờ duyệt — Lê Thu Hà (l1_01)",
      "Duyệt: đã đồng ý — Lê Thu Hà (l1_01)",
      "Thực thi: gia hạn chứng chỉ — thành công",
      "Kết cục: xử lý sau khi IT duyệt",
    ]);
    expect(screen.getByTestId("trace-facts").textContent).toContain("cert_expired, device_registered");
    expect(screen.getByTestId("trace-sources").textContent).toBe("Nguồn KB KB-VPN-001 — Gia hạn chứng chỉ VPN");
    expect(screen.getByTestId("trace-model-probs").textContent?.replace(NBSP, " ")).toBe("Model: vpn 0,97 · account 0,02");
    expect(screen.getByTestId("trace-calls").textContent).toBe("renew_vpn_cert: thành công");
    expect(calls).toStrictEqual(["GET /api/tickets/T-1/trace"]);
  });

  it("chính sách do mô hình: rủi ro + p thô / hiệu chỉnh", async () => {
    const policy = { rule_id: null, rule_description: null, policy_decision: null, risk_level: "low", decided_by: "llm" as const, raw_prob: 0.12, calibrated_prob: 0.09 };
    stub(() => json(200, { ...TRACE, steps: [step(1, "B13/B14", "risk_decided", { policy })] }));
    renderAt("/trace/T-1");
    const card = await screen.findByTestId("trace-step");
    expect(titles()).toStrictEqual(["Đánh giá rủi ro: rủi ro thấp — theo đánh giá của AI (không luật nào khớp)"]);
    expect(within(card).getByText("p rủi ro thô 0,12 · đã hiệu chỉnh 0,09")).toBeTruthy();
  });

  it("thân sai hình dạng → câu riêng, KHÔNG thẻ nào", async () => {
    stub(() => json(200, { ...TRACE, steps: [{ ...TRACE.steps[0], query: "Tôi quên mật khẩu" }] }));
    renderAt("/trace/T-1");
    expect((await screen.findByTestId("trace-error")).textContent).toBe(TRACE_INVALID_TEXT);
    expect(screen.queryAllByTestId("trace-step")).toHaveLength(0);
    expect(document.body.textContent).not.toContain("Tôi quên mật khẩu");
  });

  it("403 → câu riêng về quyền (không phải câu lỗi chung)", async () => {
    stub(() => json(403, { detail: "forbidden" }));
    renderAt("/trace/T-1");
    expect((await screen.findByTestId("trace-error")).textContent).toBe(TRACE_FORBIDDEN_TEXT);
  });

  it("404 → câu riêng (không có / không được đọc là một)", async () => {
    stub(() => json(404, { detail: "not_found" }));
    renderAt("/trace/T-404");
    expect((await screen.findByTestId("trace-error")).textContent).toBe(TRACE_NOT_FOUND_TEXT);
  });

  it("nhân viên (không có ticket:read:any) → trang 403, không gọi API", () => {
    const calls = stub(() => json(200, TRACE));
    renderAt("/trace/T-1", EMP);
    expect(screen.getByText("Bạn không có quyền xem trang này")).toBeTruthy();
    expect(calls).toStrictEqual([]);
  });

  it("mã ticket sai mẫu → không gọi API", () => {
    const calls = stub(() => json(200, TRACE));
    renderAt("/trace/a%20b");
    expect(screen.getByRole("alert").textContent).toBe("Mã yêu cầu không hợp lệ.");
    expect(calls).toStrictEqual([]);
  });

  it("ticket cha: danh sách con có link; ticket con: link về cha", async () => {
    const parent: TicketTrace = {
      ticket_id: "P-1",
      is_parent: true,
      parent_ticket_id: null,
      steps: [step(1, "B5", "split_into_2_children", { classify: { intent: null, confidence: null, model_probs: null, model_version: null, is_multi: true } })],
      children: [
        { ticket_id: "P-1-1", intent: "vpn", exit_code: null },
        { ticket_id: "P-1-2", intent: "account", exit_code: "E1" },
      ],
    };
    stub(() => json(200, parent));
    renderAt("/trace/P-1", L2);
    const kids = await screen.findAllByTestId("trace-child");
    // N-NGU: loại yêu cầu + mã kết thúc dạng "Nhãn · mã" (gợi ý của mã kết thúc nằm trong sr-only).
    expect(kids.map((k) => k.textContent)).toStrictEqual([
      "P-1-1 · VPN · vpn",
      "P-1-2 · Tài khoản · account · Ngoài phạm vi hoặc chưa rõ yêu cầu (Không thuộc 4 loại việc, hoặc chưa xác định được ý định) · E1",
    ]);
    expect(kids.map((k) => k.querySelector("a")?.getAttribute("href"))).toStrictEqual(["/trace/P-1-1", "/trace/P-1-2"]);
    expect(titles()).toStrictEqual(["Phân loại: chưa rõ · nhiều ý"]);
    cleanup();
    stub(() => json(200, { ...TRACE, ticket_id: "P-1-1", parent_ticket_id: "P-1" }));
    renderAt("/trace/P-1-1", L2);
    const up = await screen.findByTestId("trace-parent");
    expect(up.querySelector("a")?.getAttribute("href")).toBe("/trace/P-1");
  });
});

describe("nút Nhật ký quyết định ở 3 màn", () => {
  const href = () => screen.getByTestId("trace-link").getAttribute("href");

  it("xem ticket (Trưởng BP IT / L1): link theo mã trong đường dẫn", () => {
    renderAt("/approvals/ticket/T-9");
    expect(screen.getByTestId("trace-link").textContent).toBe("Nhật ký quyết định");
    expect(href()).toBe("/trace/T-9");
  });

  it("phiếu duyệt L1: mã ticket từ CHÍNH truy vấn phiếu của màn (cùng khoá cache → vẫn một GET)", async () => {
    const calls = stub(() => json(200, {
        approval_id: "42",
        ticket_id: "T-42",
        risk: null,
        risk_view: null,
        // F6 #76: getApproval kiểm chặt `affected` (fail-closed) — thân phiếu tối thiểu vẫn phải có đủ.
        affected: { user_id: "u-1", is_requester: true, department: null, manager: { status: "unknown", user_id: null, full_name: null } },
      }));
    renderAt("/approvals/42", L1, undefined, <ApprovalPageStandIn />);
    expect((await screen.findByTestId("trace-link")).getAttribute("href")).toBe("/trace/T-42");
    expect(screen.getByTestId("stand-in").textContent).toBe("T-42");
    expect(calls).toStrictEqual(["GET /api/approvals/42"]); // xem phiếu ghi `first_viewed_at` — không được gọi 2 lần
  });

  it("chi tiết escalate L2: mã ticket từ hàng đợi; ca không có → không hiện nút", () => {
    stub(() => json(500, {}));
    const item = { escalation_id: 7, ticket_id: "T-7" };
    renderAt("/escalations/7", L2, (c) => c.setQueryData(queueQuery().queryKey, { pages: [{ items: [item], next_cursor: null }], pageParams: [null] } as never));
    expect(href()).toBe("/trace/T-7");
    cleanup();
    renderAt("/escalations/8", L2, (c) => c.setQueryData(queueQuery().queryKey, { pages: [{ items: [item], next_cursor: null }], pageParams: [null] } as never));
    expect(screen.queryByTestId("trace-link")).toBeNull();
  });
});
