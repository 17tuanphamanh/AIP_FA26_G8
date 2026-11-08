// N-NGU — bỏ mã nội bộ hiện trần trên giao diện (bảng từ ngữ ĐP 26/10 23:10 + [ĐX] duyệt 23:45). Nhân viên: chỉ chữ; nhân sự
// IT: "Nhãn · mã" (mã chữ nhỏ, màu nhạt); mã lạ → "Khác · mã". Không gọi backend: fetch giả.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ApprovalViewP4, EscalationQueueItem, Me, TicketView } from "../api/types.ts";
import { AuthContext, type AuthValue } from "../auth/context.ts";
import {
  BEN_QUYET_DINH,
  BUOC,
  caSo,
  DUONG_XU_LY,
  GOI_Y_TRONG_SO,
  HUONG_XU_LY,
  MA_KET_THUC,
  maKetThuc,
  NHAN_VIEN_KHAC,
  nhanIT,
  nhanNhanVien,
  SU_KIEN,
  TRANG_THAI,
} from "../lib/nhan.ts";
import { buildApprovalFixtures } from "../mocks/fixtures/approvals.ts";
import { createMulti, readMulti } from "../mocks/fixtures/multi.ts";
import { ChatRoute } from "./employee/ChatPage.tsx";
import { sessionTickets } from "./employee/sessionTickets.ts";
import { STATUS_LABEL } from "./employee/status.ts";
import { ApprovalDetailRoute } from "./l1/ApprovalDetail.tsx";
import { TicketOverrideRoute } from "./l1/TicketOverride.tsx";
import { EscalationDetailRoute } from "./l2/EscalationDetail.tsx";
import { EscalationQueue } from "./l2/EscalationQueue.tsx";
import { DashboardPage } from "./manager/DashboardPage.tsx";
import { AI_METRICS, ALERT_LABEL } from "./manager/metrics.ts";
import { METRIC_LABEL } from "./manager/strategyLabels.ts";
import { TicketTraceRoute } from "./shared/TicketTrace.tsx";

const clients: QueryClient[] = [];
afterEach(() => {
  cleanup();
  for (const c of clients.splice(0)) c.clear();
  sessionTickets.clear();
  vi.unstubAllGlobals();
});

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
/** Mã nội bộ không được lộ ở màn nhân viên. */
const MA_NOI_BO = /\bE\d\b|\bB\d{1,2}\b|\bR\d+\b|S_[A-Z]/;
const BASE = ["ticket:create", "ticket:read:own", "ticket:message", "ticket:confirm"];
const L1: Me = { user_id: "l1_01", role: "l1", permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "escalation:handle"] };
const MGR: Me = { user_id: "mgr", role: "manager", permissions: [...BASE, "ticket:read:any", "approval:decide", "decision:override", "policy:read", "dashboard:read:all", "alert:read"] };
const signedIn = (me: Me): AuthValue => ({ state: { status: "signedIn", me }, signIn: vi.fn(), signOut: vi.fn(async () => true) });

function mount(path: string, route: string, element: React.ReactNode, me: Me = L1) {
  const client = new QueryClient();
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AuthContext value={signedIn(me)}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={element} />
          </Routes>
        </MemoryRouter>
      </AuthContext>
    </QueryClientProvider>,
  );
}
/** Các nút chữ nối bằng dấu cách — `textContent` dính liền chữ hai phần tử ("…tiếp.E5Tạo") làm `\b` của regex mù mã. */
function spaced(el: Node): string {
  const out: string[] = [];
  const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) out.push(n.textContent ?? "");
  return out.join(" ");
}
const bodyText = () => spaced(document.body);
/** Chữ của phần tử, bỏ các span mã (MaNhan) — phần còn lại không được có mã trần. */
function withoutCodes(el: Element): string {
  const clone = el.cloneNode(true) as Element;
  for (const m of clone.querySelectorAll('[data-testid="ma"], .sr-only')) m.remove();
  return clone.textContent ?? "";
}
const withoutCodesSpaced = (el: Element): string => {
  const clone = el.cloneNode(true) as Element;
  for (const m of clone.querySelectorAll('[data-testid="ma"], .sr-only')) m.remove();
  return spaced(clone);
};

// ------------------------------------------------------------------------------------------------ t191

/** Tên sự kiện gặp trong backend (graph/**, audit, api — đọc chỉ đọc 26/10) + hằng (closed, injection_suspected, …). */
const BACKEND_EVENTS = (
  "action_built action_plan_changed_since_approval approval_target_unverified approval_timeout approved approver_lookup_error " +
  "approver_no_longer_valid approver_sync_unavailable asked cannot_answer child_not_runnable child_started children_aggregated " +
  "clarification_exhausted clarify_timeout classifier_unavailable deflected_info_only diagnosed diagnosis_skipped digest_sent exec_failed " +
  "exec_interrupted executed_ok execution_failed execution_interrupted guard_unavailable identity_established identity_unverifiable " +
  "injection_detected injection_in_reply intent_classified intent_low_confidence intent_not_enabled intent_out_of_scope invalid_citation " +
  "llm_layer_disabled llm_schema_error llm_unavailable max_clarification_reached max_loops_exceeded needs_action new_slot_rediagnose " +
  "no_evidence no_procedure no_valid_approver off_topic_twice output_guard_block override_recorded parent_woken person_no_longer_valid " +
  "queued rag_system_error recheck_failed recursion_limit rejected reply_timeout retrieval_error retrieved risk_decided role_unmappable " +
  "screened split split_span_invalid target_check_error tool_system_error turn_budget_exceeded unhandled_exception user_confirmed " +
  "user_replied user_reported_unresolved closed injection_suspected recover_exhausted late_event privacy_secret_redacted finalize_failed_permanent"
).split(" ");

describe("t191: bao phủ bảng — mọi mã của bảng ĐP có nhãn, đúng chữ", () => {
  it("mã kết thúc E0–E9 + tooltip; E1 + injection_suspected", () => {
    expect(Object.fromEntries(Object.entries(MA_KET_THUC).map(([k, v]) => [k, v.nhan]))).toStrictEqual({
      E0: "Nghi tấn công, đã chặn",
      E1: "Ngoài phạm vi hoặc chưa rõ yêu cầu",
      E2: "Lỗi khi xử lý (AI hoặc công cụ)",
      E3: "Thiếu tài liệu hướng dẫn",
      E4: "Thiếu thông tin từ người dùng",
      E5: "Không đủ điều kiện tự xử lý",
      E6: "Quá hạn chờ duyệt",
      E7: "Thực hiện không thành công",
      E8: "Người dùng báo chưa giải quyết",
      E9: "Lỗi hệ thống bất ngờ",
    });
    for (const v of Object.values(MA_KET_THUC)) expect(v.goiY?.length).toBeGreaterThan(5);
    expect(maKetThuc("E1", "injection_suspected")?.nhan).toBe("Nghi tấn công, cần người xem");
    expect(maKetThuc("E1", "out_of_scope")?.nhan).toBe("Ngoài phạm vi hoặc chưa rõ yêu cầu");
  });
  it("4 lý do E5, route, bên quyết định, bước, trạng thái", () => {
    expect(["recheck_failed", "llm_layer_disabled", "llm_high_risk", "approval_target_unverified"].map((k) => nhanIT("ly_do", k).nhan)).toStrictEqual([
      "Kiểm tra lại trước khi thực hiện không đạt",
      "Lớp AI không phản hồi",
      "AI đánh giá rủi ro cao",
      "Không xác minh được người hưởng lợi",
    ]);
    expect(HUONG_XU_LY).toStrictEqual({ AUTO: "Tự xử lý", HITL: "Chờ IT duyệt", ESCALATE_L2: "Chuyển kỹ thuật viên L2" });
    expect(BEN_QUYET_DINH).toStrictEqual({ rule: "Theo luật", llm: "Theo đánh giá của AI", model: "Theo model chặn tấn công" });
    expect(Object.keys(DUONG_XU_LY)).toStrictEqual(["auto", "approved", "rejected", "escalated", "deflected"]);
    const steps: Record<string, string> = {
      B1: "Xác thực người gửi", B2: "Kiểm tra tấn công", B3: "Phân loại và tách yêu cầu", B5: "Phân loại và tách yêu cầu",
      B6: "Chẩn đoán trên hệ thống", B7: "Chẩn đoán trên hệ thống", B8: "Tra cứu tài liệu", B9: "Tra cứu tài liệu",
      B10: "Trả lời từ tài liệu", B11: "Bổ sung thông tin", B12: "Đánh giá rủi ro", "B13/B14": "Đánh giá rủi ro", B15: "Phê duyệt",
      B16: "Phê duyệt", B17: "Thực hiện", B18: "Thực hiện", B19: "Xác nhận với người dùng", B20: "Ghi nhận và chuyển người",
      "B3/B4": "Phân loại và tách yêu cầu", B17_RECHECK: "Kiểm tra lại trước khi thực hiện", B15_APPROVER: "Tìm người duyệt",
      runner: "Điều phối hệ thống", OVERRIDE: "Ghi đè của IT",
    }; // prettier-ignore
    for (const [k, v] of Object.entries(steps)) expect([k, BUOC[k]]).toStrictEqual([k, v]);
    expect(TRANG_THAI.S_RESOLVED).toBe("Đã giải quyết");
    expect(TRANG_THAI.S_ESCALATED).toBe("Đã chuyển kỹ thuật viên");
    expect(TRANG_THAI.S_PENDING_APPROVAL).toBe("Chờ IT duyệt");
    expect(TRANG_THAI.S_REJECTED).toBe("Bị từ chối");
    expect(Object.keys(TRANG_THAI)).toHaveLength(14);
  });
  it("mọi sự kiện backend đều có câu (không cái nào rơi vào 'Khác'); 3 câu của bảng", () => {
    expect(BACKEND_EVENTS.filter((e) => !Object.hasOwn(SU_KIEN, e))).toStrictEqual([]);
    expect([SU_KIEN.risk_decided, SU_KIEN.executed_ok, SU_KIEN.exec_failed]).toStrictEqual(["Đã đánh giá rủi ro", "Đã thực hiện", "Thực hiện lỗi"]);
    for (const v of Object.values(SU_KIEN)) expect(v).not.toMatch(MA_NOI_BO);
  });
});

// ------------------------------------------------------------------------------------------------ t192

describe("t192: mã lạ — IT 'Khác · mã'; nhân viên câu chung, không bao giờ có mã", () => {
  it("nhanIT / nhanNhanVien", () => {
    expect(nhanIT("ma_ket_thuc", "E42")).toStrictEqual({ nhan: "Khác", ma: "E42" });
    for (const k of ["__proto__", "constructor", "toString"]) {
      expect(nhanIT("su_kien", k)).toStrictEqual({ nhan: "Khác", ma: k });
      expect(nhanNhanVien("trang_thai", k)).toBe(NHAN_VIEN_KHAC);
    }
    for (const loai of ["ma_ket_thuc", "buoc", "su_kien", "trang_thai", "ly_do"] as const) {
      for (const ma of ["E5", "B13/B14", "R18", "S_ESCALATED", "zz_moi", null]) expect(nhanNhanVien(loai, ma)).not.toMatch(MA_NOI_BO);
    }
    expect(caSo(1253)).toBe("Ca \u00231253"); // \u0023 = dấu thăng (check:style coi chuỗi thăng + số là mã màu)
  });
});

// ------------------------------------------------------------------------------------------------ t193

const TID = "0811f300-6bb8-4cd1-8366-a6dcb8a17655";
const ticket = (over: Partial<TicketView>): TicketView => ({
  ticket_id: TID,
  status: "S_ESCALATED",
  waiting_for: null,
  conversation: [{ role: "user", text: "Không vào được VPN" }, { role: "assistant", kind: "escalation", text: "Đã chuyển kỹ thuật viên hỗ trợ.", ref: null }],
  exit_code: "E5",
  close_reason: null,
  final_state: "S_ESCALATED",
  created_at: "2026-09-30T13:00:00Z",
  closed_at: "2026-09-30T13:01:00Z",
  ...over,
});

async function renderChat(v: TicketView) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => (url === `/api/tickets/${v.ticket_id}` ? json(200, v) : json(404, { detail: "Not Found" }))),
  );
  mount(`/chat/${v.ticket_id}`, "/chat/:ticketId", <ChatRoute />);
  await screen.findByText(/./, { selector: "[data-testid='ticket-status'], main, body" }).catch(() => null);
  await waitFor(() => expect(document.body.textContent?.length ?? 0).toBeGreaterThan(20));
}

describe("t193: màn nhân viên — không chuỗi mã nội bộ nào (mọi trạng thái, mọi mã kết thúc, nhiều ý / tin tổng hợp)", () => {
  const states = Object.keys(STATUS_LABEL);
  it.each(states)("trạng thái %s (đang chạy và đã kết thúc)", async (status) => {
    const closed = ["S_RESOLVED", "S_ESCALATED", "S_REJECTED", "S_BLOCKED"].includes(status);
    await renderChat(ticket({ status, final_state: closed ? status : null, exit_code: closed ? "E5" : null }));
    await waitFor(() => expect(document.body.textContent).toContain("VPN"));
    expect(bodyText()).not.toMatch(MA_NOI_BO);
  });
  it.each(Object.keys(MA_KET_THUC))("mã kết thúc %s trong ticket view → không lộ", async (code) => {
    await renderChat(ticket({ exit_code: code, close_reason: "recheck_failed" }));
    await waitFor(() => expect(document.body.textContent).toContain("VPN"));
    expect(bodyText()).not.toMatch(MA_NOI_BO);
    expect(document.body.textContent).not.toContain("recheck_failed");
  });
  it("trạng thái lạ → câu chung, không mã", async () => {
    await renderChat(ticket({ status: "S_MOI_LA", final_state: null, exit_code: null }));
    await waitFor(() => expect(document.body.textContent).toContain("VPN"));
    expect(bodyText()).not.toMatch(MA_NOI_BO);
  });
  it("nhiều ý: đang xử lý + vòng hỏi có tin tổng hợp", async () => {
    const t = createMulti("tkt-demo-multi-1", Date.parse("2026-09-30T13:00:00Z"));
    for (const v of [readMulti(t), readMulti(t)]) {
      cleanup();
      await renderChat(v);
      await waitFor(() => expect(document.body.textContent?.length ?? 0).toBeGreaterThan(40));
      expect(bodyText()).not.toMatch(MA_NOI_BO);
    }
  });
});

// ------------------------------------------------------------------------------------------------ t194

describe("t194: nhật ký — mỗi thẻ 'Nhãn · mã'; ngoài span mã không còn mã trần; sự kiện lạ → 'Khác · tên'", () => {
  const E = { screen: null, classify: null, diagnose: null, sources: null, policy: null, approval: null, execution: null, outcome: null };
  const body = {
    ticket_id: "T-1",
    is_parent: false,
    parent_ticket_id: null,
    children: [],
    steps: [
      { ...E, step: "B17_RECHECK", event: "recheck_failed", at: "2099-09-26T01:00:00Z" },
      { ...E, step: "runner", event: "su_kien_moi_la", at: "2099-09-26T01:01:00Z" },
      { ...E, step: "B13/B14", event: "risk_decided", at: "2099-09-26T01:02:00Z", policy: { rule_id: "R18", rule_description: "Ngoài giờ cần duyệt", policy_decision: "approval_required", risk_level: "medium", decided_by: "rule", raw_prob: null, calibrated_prob: null } },
      { ...E, step: "B20", event: "closed", at: "2099-09-26T01:03:00Z", outcome: { route: "escalated", exit_code: "E5" } },
    ],
  };
  it("dòng mã, luật kèm mô tả, mã kết thúc có nhãn", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, body)));
    mount("/trace/T-1", "/trace/:ticketId", <TicketTraceRoute />);
    const cards = await screen.findAllByTestId("trace-step");
    expect(cards.map((c) => within(c).getByTestId("trace-step-codes").textContent)).toStrictEqual([
      "Kiểm tra lại trước khi thực hiện · B17_RECHECK · Kiểm tra lại trước khi thực hiện không đạt · recheck_failed",
      "Điều phối hệ thống · runner · Khác · su_kien_moi_la",
      "Đánh giá rủi ro · B13/B14 · Đã đánh giá rủi ro · risk_decided",
      "Ghi nhận và chuyển người · B20 · Đã ghi nhận và kết thúc · closed",
    ]);
    expect(within(cards[2]!).getByTestId("trace-rule").textContent).toBe("Luật Ngoài giờ cần duyệt · R18");
    expect(withoutCodes(within(cards[3]!).getByTestId("trace-exit"))).toBe("Mã kết thúc Không đủ điều kiện tự xử lý · ");
    for (const c of cards) expect(withoutCodesSpaced(c)).not.toMatch(/\bE\d\b|\bB\d{1,2}\b|\bR\d+\b|S_[A-Z]|[a-z]+_[a-z_]+/);
  });
});

// ------------------------------------------------------------------------------------------------ t195

let nextId = 9100;
const esc = (code: string, over: Partial<EscalationQueueItem> = {}): EscalationQueueItem => ({
  escalation_id: nextId++,
  ticket_id: `t-${nextId}`,
  exit_code: code,
  priority: 5,
  label: "Cao",
  reason_detail: null,
  is_deny_case: code === "E5",
  handoff_note: { request: "x", done_so_far: "y", why_escalated: "z", next_for_l2: "w" },
  assigned_to: null,
  created_at: "2026-09-30T13:00:00Z",
  ...over,
});

describe("t195: L2 — dòng + tiêu đề 'Nhãn · mã'; E1 nghi tấn công; 'Ca #'; lý do có nhãn; không 'Escalation #'", () => {
  function serveQueue(items: EscalationQueueItem[]) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url.startsWith("/api/escalations/queue") ? json(200, { items, next_cursor: null }) : json(200, ticket({ ticket_id: "x" })),
      ),
    );
  }
  it("hàng đợi", async () => {
    const items = [esc("E5", { reason_detail: "recheck_failed" }), esc("E1", { reason_detail: "injection_suspected", priority: 6 }), esc("E42", { priority: 7 })];
    serveQueue(items);
    mount("/escalations", "/escalations", <EscalationQueue />);
    await screen.findAllByTestId("queue-row");
    expect(screen.getAllByTestId("queue-exit").map((e) => e.textContent?.replace(/\s*\(.*?\)/, ""))).toStrictEqual([
      "Không đủ điều kiện tự xử lý · E5",
      "Nghi tấn công, cần người xem · E1",
      "Khác · E42",
    ]);
  });
  it("chi tiết: tiêu đề, Ca #, lý do", async () => {
    const it5 = esc("E5", { reason_detail: "llm_layer_disabled" });
    serveQueue([it5]);
    mount(`/escalations/${it5.escalation_id}`, "/escalations/:escalationId", <EscalationDetailRoute />);
    const h = await screen.findByTestId("detail-exit");
    expect(withoutCodes(h)).toBe("Chưa đánh giá được rủi ro — chuyển kỹ thuật viên · "); // M2 (ĐP 08/11): E5 + lớp AI lỗi
    expect(screen.getByTestId("ca-so").textContent).toBe(`Ca #${it5.escalation_id}`);
    expect(document.body.textContent).not.toContain("Escalation #");
    expect(document.body.textContent).toContain("Lý do Lớp AI không phản hồi · llm_layer_disabled");
  });
});

// ------------------------------------------------------------------------------------------------ t196, t197

const view01 = (): ApprovalViewP4 => buildApprovalFixtures(Date.now()).find((f) => f.approval_id === "apv-demo-01")!.view as ApprovalViewP4;

describe("t196: phiếu duyệt — hướng xử lý / nguồn / luật 'Nhãn · mã'; rủi ro thô trong 'Chi tiết kỹ thuật' (đóng sẵn); khoá hành động có nhãn", () => {
  it("apv-demo-01", async () => {
    const v = view01();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => (url === `/api/approvals/${v.approval_id}` ? json(200, v) : json(200, { items: [] }))),
    );
    mount(`/approvals/${v.approval_id}`, "/approvals/:approvalId", <ApprovalDetailRoute />);
    await screen.findByTestId("risk-summary");
    expect(screen.getByTestId("risk-route").textContent).toBe("Chờ IT duyệt · HITL");
    expect(screen.getByTestId("risk-source").textContent).toBe("Theo luật · rule");
    expect(screen.getByTestId("risk-rule").textContent).toBe("Yêu cầu gửi ngoài giờ hành chính cần người duyệt · R18");
    const raw = screen.getByTestId("risk-raw") as HTMLDetailsElement;
    expect(raw.tagName).toBe("DETAILS");
    expect(raw.open).toBe(false);
    expect(within(raw).getByText("Chi tiết kỹ thuật")).toBeTruthy();
    const type = screen.getAllByTestId("action-row").find((r) => r.dataset.key === "type")!;
    expect(type.querySelector("dt")!.textContent).toBe("Loại hành động · type");
    // giá trị đã băm giữ NGUYÊN (G4-13); B2: nhãn chỉ đi kèm, ở phần tử riêng
    expect(within(type).getByTestId("raw-value").textContent).toBe('"renew_vpn_cert"');
    expect(within(type).getByTestId("value-label").textContent).toBe("Cấp lại chứng chỉ VPN");
  });
});

describe("t197: xem ticket để ghi đè — trạng thái + kết thúc 'Nhãn · mã'", () => {
  it("S_ESCALATED + E5", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, ticket({ ticket_id: "tkt-x" }))));
    mount("/approvals/ticket/tkt-x", "/approvals/ticket/:ticketId", <TicketOverrideRoute />);
    const line = await screen.findByTestId("ticket-state");
    expect(line.textContent).toContain("Trạng thái Đã chuyển kỹ thuật viên · S_ESCALATED · Kết thúc Không đủ điều kiện tự xử lý");
    expect(withoutCodesSpaced(line)).not.toMatch(MA_NOI_BO);
  });
});

// ------------------------------------------------------------------------------------------------ t198

describe("t198: Tổng quan / Cảnh báo — nhãn không chứa mã; tooltip 'Chuyển L2 (có trọng số)'; decided_by 'model' có nhãn", () => {
  it("bảng nhãn FE không còn '(E…)' / 'B…' trong chữ chính", () => {
    for (const t of [...Object.values(ALERT_LABEL), ...AI_METRICS.map((m) => m.label), ...Object.values(METRIC_LABEL)]) expect(t).not.toMatch(/\bE\d\b|\bB\d{1,2}\b/);
  });
  it("tooltip KPI + bên quyết định model", async () => {
    const metrics = {
      automation_rate: 0.5, escalation_rate_raw: 0.2, escalation_rate_weighted: { raw: 0.2, weighted: 0.15, by_group: {}, sensitivity: {} },
      deflection_rate: 0.1, approval_expired_count: 0, decided_by_distribution: { rule: 3, llm: 2, model: 1 }, top_matched_rules: [{ rule_id: "R18", count: 2 }],
      override_count: 0, e1_split: null, e3_cases: null,
    }; // prettier-ignore
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (url.startsWith("/api/dashboard/business")) return json(200, { from: "2026-10-20T00:00:00Z", to: "2026-10-26T00:00:00Z", unavailable: [], scope: "all", metrics });
        if (url.startsWith("/api/alerts")) return json(200, { items: [], truncated: false });
        if (url === "/api/policy") return json(200, { version_id: 0, version: "file-x", content: { rules: [{ id: "R18", description: "Ngoài giờ cần duyệt" }] }, updated_by: null, updated_at: "2026-10-01T00:00:00Z", is_current: true });
        return json(404, { detail: "Not Found" });
      }),
    );
    mount("/dashboard", "/dashboard", <DashboardPage />, MGR);
    const tip = await screen.findByTestId("kpi-goi-y");
    expect(tip.getAttribute("title")).toBe(GOI_Y_TRONG_SO);
    expect(GOI_Y_TRONG_SO).toBe("Tính theo tỉ lệ 70/20/10 giữa ca thường, ca cần duyệt và ca nhạy cảm.");
    await waitFor(() => expect(document.body.textContent).toContain("Theo model chặn tấn công"));
    await waitFor(() => expect(screen.getByTestId("rule-name").textContent).toBe("Ngoài giờ cần duyệt · R18"));
  });
});

// ------------------------------------------------------------------------------------------------ t199

describe("t199: quét tĩnh — không literal hiển thị nào chứa 'Escalation #' hay mã E/B lẫn trong câu (ngoài lib/nhan.ts)", () => {
  it("bỏ chú thích rồi tìm chuỗi có mã kèm chữ khác", () => {
    const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}", "!/src/mocks/**", "!/src/lib/nhan.ts", "!/src/api/schema.gen.ts"], {
      query: "?raw",
      import: "default",
      eager: true,
    });
    expect(Object.keys(sources).length).toBeGreaterThan(50);
    const strip = (code: string) =>
      code
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .split("\n")
        .map((l) => l.replace(/(^|[^:"'`])\/\/.*$/, "$1"))
        .join("\n");
    const hits: string[] = [];
    for (const [f, code] of Object.entries(sources)) {
      const c = strip(code);
      if (c.includes("Escalation #")) hits.push(`${f}: Escalation #`);
      // Chuỗi ("…", `…`) hoặc chữ JSX có mã E\d / B\d kèm ít nhất một chữ khác (mã đứng một mình như "E6" là giá trị so sánh).
      for (const m of c.matchAll(/"([^"\n]*)"|`([^`\n]*)`|>([^<>{}\n]+)</g)) {
        const t = (m[1] ?? m[2] ?? m[3] ?? "").trim();
        if (/\b[EB]\d{1,2}\b/.test(t) && !/^[EB]\d{1,2}$/.test(t) && /[\p{L}]{3,}/u.test(t.replace(/\b[EB]\d{1,2}\b/g, ""))) hits.push(`${f}: ${t}`);
      }
    }
    expect(hits).toStrictEqual([]);
  });
});
