// N-PA P1 — kiểu + parser chặt cho route mới (hợp đồng chốt ĐP 26/10 17:30): cách xử lý (D-60), so sánh phương án, các
// luật khớp (phiếu duyệt + nhật ký), hàng đợi L2 `{items, next_cursor}` + đóng ca. Thân sai hình → ApiError(502, …).
import { afterEach, describe, expect, it, vi } from "vitest";
import { buildApprovalFixtures } from "../mocks/fixtures/approvals.ts";
import { buildStrategies, METRIC_KEYS } from "../mocks/fixtures/strategy.ts";
import { cellText, MIN_SAMPLE } from "../routes/manager/compare.ts";
import { reasonProblem } from "../routes/manager/strategyText.ts";
import { parseApprovalView } from "./approvals.ts";
import { createClient } from "./client.ts";
import { BAD_STRATEGIES, getStrategiesDashboard, parseStrategies, SOURCE_MISMATCH } from "./dashboard.ts";
import { ApiError } from "./errors.ts";
import { CLOSE_AVAILABLE, closeEscalation, getEscalationQueuePage, loadedItems, parseCloseResult, parseQueuePage, QUEUE_PAGE_LIMIT, queuePath } from "./escalations.ts";
import {
  getStrategy,
  getStrategyHistory,
  parseStrategyHistory,
  parseStrategyView,
  putStrategy,
  reasonLength,
  STRATEGY_HISTORY_LIMIT,
} from "./strategy.ts";
import { parseTrace } from "./trace.ts";
import type { ApprovalViewP4, EscalationQueuePage, StrategyView } from "./types.ts";

afterEach(() => vi.unstubAllGlobals());

/** Bản sao của object bỏ một khoá (thân thiếu khoá). */
const without = (o: object, k: string): Record<string, unknown> => Object.fromEntries(Object.entries(o).filter(([x]) => x !== k));

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function clientWith(res: () => Response) {
  const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => res());
  return { fetch, client: createClient({ fetch, readCookie: () => null, locks: null, channel: null, onSessionEnd: vi.fn() }) };
}

function bad(fn: () => unknown, code: string) {
  try {
    fn();
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError);
    expect([(e as ApiError).status, (e as ApiError).code]).toStrictEqual([502, code]);
    return;
  }
  throw new Error("không ném lỗi");
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => null,
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

const VIEW: StrategyView = {
  strategy: "hybrid",
  selectable: ["rule_only", "hybrid", "hybrid_guarded"],
  llm_calibrated: false,
  eval_mode: false,
  changed_by: null,
  changed_at: null,
  reason: null,
};

// ------------------------------------------------------------------------------------------------ t146

describe("t146: parseStrategyView — đủ khoá, enum chặt; thiếu llm_calibrated vẫn hợp lệ (màn coi CHƯA hiệu chỉnh)", () => {
  it("hợp lệ: thân đầy đủ; changed_* null; thiếu khoá llm_calibrated", () => {
    expect(parseStrategyView(VIEW)).toStrictEqual(VIEW);
    const noCal = without(VIEW, "llm_calibrated");
    expect(parseStrategyView(noCal).llm_calibrated).toBeUndefined();
    expect(parseStrategyView({ ...VIEW, changed_by: "quan.tm", changed_at: "2026-10-26T10:00:00Z", reason: "x" }).changed_by).toBe("quan.tm");
  });

  it.each([
    ["mảng trần", []],
    ["strategy ngoài tập vận hành (llm_only)", { ...VIEW, strategy: "llm_only" }],
    ["selectable có giá trị lạ", { ...VIEW, selectable: ["hybrid", "full_auto"] }],
    ["selectable không phải mảng", { ...VIEW, selectable: "hybrid" }],
    ["llm_calibrated không phải boolean", { ...VIEW, llm_calibrated: "false" }],
    ["thiếu eval_mode", { ...VIEW, eval_mode: undefined }],
    ["changed_by là số", { ...VIEW, changed_by: 1 }],
    ["thiếu reason", without(VIEW, "reason")],
  ])("%s → 502 invalid_strategy_body", (_n, body) => bad(() => parseStrategyView(body), "invalid_strategy_body"));

  it("GET /api/admin/strategy qua client; thân sai → 502", async () => {
    const { fetch, client } = clientWith(() => json(200, VIEW));
    expect((await getStrategy(client)).strategy).toBe("hybrid");
    expect(fetch.mock.calls[0]![0]).toBe("/api/admin/strategy");
    const broken = clientWith(() => json(200, { strategy: "hybrid" }));
    expect((await rejection(getStrategy(broken.client))).code).toBe("invalid_strategy_body");
  });
});

// ------------------------------------------------------------------------------------------------ t147

describe("t147: lịch sử đổi — {items, truncated}, thứ tự server, limit=50", () => {
  const item = { changed_at: "2026-10-26T10:00:00Z", changed_by: "quan.tm", strategy_from: "hybrid", strategy_to: "rule_only", reason: "Thử chỉ luật một tuần." };
  it("hợp lệ: giữ ĐÚNG thứ tự server (không sắp lại)", () => {
    const older = { ...item, changed_at: "2026-10-20T10:00:00Z", strategy_from: "rule_only", strategy_to: "hybrid" };
    const body = { items: [older, item], truncated: true }; // server cố ý trả cũ trước → FE không tự đảo
    expect(parseStrategyHistory(body).items.map((i) => i.changed_at)).toStrictEqual([older.changed_at, item.changed_at]);
  });
  it.each([
    ["mảng trần", [item]],
    ["thiếu truncated", { items: [item] }],
    ["phần tử strategy_to lạ", { items: [{ ...item, strategy_to: "manual" }], truncated: false }],
    ["changed_by null", { items: [{ ...item, changed_by: null }], truncated: false }],
  ])("%s → 502 invalid_strategy_history_body", (_n, body) => bad(() => parseStrategyHistory(body), "invalid_strategy_history_body"));
  it("URL có limit=50", async () => {
    const { fetch, client } = clientWith(() => json(200, { items: [], truncated: false }));
    await getStrategyHistory(client);
    expect(STRATEGY_HISTORY_LIMIT).toBe(50);
    expect(fetch.mock.calls[0]![0]).toBe("/api/admin/strategy/history?limit=50");
  });
});

// ------------------------------------------------------------------------------------------------ t148

describe("t148: putStrategy — PUT {strategy, reason đã cắt trắng}; CHỈ 200 là thành công; lỗi giữ nguyên mã", () => {
  it("200 → thân như GET; body gửi đi đúng 2 khoá, lý do đã cắt", async () => {
    const { fetch, client } = clientWith(() => json(200, { ...VIEW, strategy: "rule_only" }));
    expect((await putStrategy({ strategy: "rule_only", reason: "   Thử một tuần chỉ luật.  " }, client)).strategy).toBe("rule_only");
    const [url, init] = fetch.mock.calls[0]!;
    expect([url, init?.method]).toStrictEqual(["/api/admin/strategy", "PUT"]);
    expect(JSON.parse(init!.body as string)).toStrictEqual({ strategy: "rule_only", reason: "Thử một tuần chỉ luật." });
  });
  it("2xx khác 200 → 502 (không báo thành công giả); 200 thân sai → 502", async () => {
    expect((await rejection(putStrategy({ strategy: "rule_only", reason: "0123456789" }, clientWith(() => json(202, VIEW)).client))).code).toBe(
      "unexpected_strategy_status",
    );
    expect((await rejection(putStrategy({ strategy: "rule_only", reason: "0123456789" }, clientWith(() => json(200, {})).client))).code).toBe(
      "invalid_strategy_body",
    );
  });
  it.each([
    [409, { detail: "same_as_current" }, "same_as_current", []],
    [422, { error: "invalid_request", fields: ["reason"] }, "invalid_request", ["reason"]],
    [403, { detail: "forbidden" }, "forbidden", []],
  ])("%i → ApiError giữ mã + fields", async (status, body, code, fields) => {
    const e = await rejection(putStrategy({ strategy: "rule_only", reason: "0123456789" }, clientWith(() => json(status, body)).client));
    expect([e.status, e.code, e.fields]).toStrictEqual([status, code, fields]);
  });
});

// ------------------------------------------------------------------------------------------------ t149

describe("t149: lý do 10–500 ký tự SAU khi cắt trắng, đếm theo ký tự (code point)", () => {
  it.each([
    ["9 ký tự", "123456789", false],
    ["10 ký tự", "1234567890", true],
    ["10 ký tự + khoảng trắng hai đầu", "  1234567890 \n", true],
    ["chỉ khoảng trắng", "            ", false],
    ["500 ký tự", "a".repeat(500), true],
    ["501 ký tự", "a".repeat(501), false],
    ["tiếng Việt có dấu (dựng sẵn) 10 ký tự", "Đổi lý do ", false], // 9 sau khi cắt
    ["biểu tượng ngoài BMP: 5 × '😀' + 5 chữ = 10 ký tự", "😀😀😀😀😀abcde", true],
  ])("%s → hợp lệ %s", (_n, reason, ok) => {
    expect(reasonProblem(reason) === null).toBe(ok);
  });
  it("đếm code point (không phải UTF-16): '😀' = 1", () => {
    expect(reasonLength("😀")).toBe(1);
    expect(reasonLength("  ab  ")).toBe(2);
  });
  it("câu lỗi không nhắc lại nội dung đã gõ", () => {
    expect(reasonProblem("bí mật 1")).toBe("Lý do cần ít nhất 10 ký tự (hiện có 8).");
  });
});

// ------------------------------------------------------------------------------------------------ t150

describe("t150: parseStrategies — khung + source khớp nguồn đã gửi + ô đúng dạng; giữ thứ tự server", () => {
  const body = () => buildStrategies("sim", "2026-10-20T00:00:00Z", "2026-10-26T00:00:00Z");
  it("hợp lệ: 17 khoá đúng thứ tự, strategies + metrics giữ thứ tự", () => {
    const parsed = parseStrategies(body(), "sim");
    expect(parsed.metrics.map((m) => m.key)).toStrictEqual([...METRIC_KEYS]);
    const reversed = { ...body(), metrics: [...body().metrics].reverse(), strategies: ["hybrid_guarded", "hybrid", "rule_only"] };
    expect(parseStrategies(reversed, "sim").metrics[0]!.key).toBe("llm_cost_per_ticket");
  });
  it("source lệch nguồn đã gửi → 502 strategies_source_mismatch", () => bad(() => parseStrategies(body(), "real"), SOURCE_MISMATCH));
  it.each([
    ["source 'all'", { ...body(), source: "all" }],
    ["strategies trùng", { ...body(), strategies: ["hybrid", "hybrid"] }],
    ["kind lạ", { ...body(), metrics: [{ ...body().metrics[1]!, kind: "score" }] }],
    ["values thiếu một chiến lược", { ...body(), metrics: [{ ...body().metrics[1]!, values: { rule_only: null, hybrid: null } }] }],
    ["values thừa chiến lược", { ...body(), metrics: [{ ...body().metrics[1]!, values: { rule_only: null, hybrid: null, hybrid_guarded: null, x: null } }] }],
    ["ratio num > den", { ...body(), metrics: [{ key: "auto_rate", kind: "ratio", values: { rule_only: { num: 5, den: 3 }, hybrid: null, hybrid_guarded: null } }] }],
    ["ratio số âm", { ...body(), metrics: [{ key: "auto_rate", kind: "ratio", values: { rule_only: { num: -1, den: 3 }, hybrid: null, hybrid_guarded: null } }] }],
    ["value thiếu khoá value", { ...body(), metrics: [{ key: "tickets", kind: "value", values: { rule_only: { n: 3 }, hybrid: null, hybrid_guarded: null } }] }],
    ["value có điểm tổng (khoá lạ)", { ...body(), metrics: [{ key: "tickets", kind: "value", values: { rule_only: { value: 1, score: 9 }, hybrid: null, hybrid_guarded: null } }] }],
    ["intent_mix khoá chiến lược lạ", { ...body(), intent_mix: { manual: { vpn: 1 } } }],
    ["intent_mix số âm", { ...body(), intent_mix: { hybrid: { vpn: -1 } } }],
    ["thiếu unavailable", { ...body(), unavailable: undefined }],
  ])("%s → 502 invalid_strategies_body", (_n, b) => bad(() => parseStrategies(b, "sim"), BAD_STRATEGIES));
  it("URL: from, to, source", async () => {
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        return json(200, buildStrategies("sim", "a", "b"));
      }),
    );
    await getStrategiesDashboard({ from: "2026-10-20T00:00:00.000+07:00", to: "2026-10-26T00:00:00.000+07:00" }, "sim");
    expect(calls[0]).toBe("/api/dashboard/strategies?from=2026-10-20T00%3A00%3A00.000%2B07%3A00&to=2026-10-26T00%3A00%3A00.000%2B07%3A00&source=sim");
  });
});

// ------------------------------------------------------------------------------------------------ t151

describe("t151: cellText — 'tỉ lệ (a/b)', mẫu < 20 → chưa đủ dữ liệu, null → '—', đơn vị, n", () => {
  const ratio = { kind: "ratio" as const };
  it("ratio", () => {
    expect(MIN_SAMPLE).toBe(20);
    expect(cellText(ratio, { num: 63, den: 100 })).toBe("63\u00a0% (63/100)");
    expect(cellText(ratio, { num: 0, den: 20 })).toBe("0\u00a0% (0/20)");
    expect(cellText(ratio, { num: 2, den: 19 })).toBe("chưa đủ dữ liệu (n=19)");
    expect(cellText(ratio, { num: 0, den: 0 })).toBe("chưa đủ dữ liệu (n=0)");
    expect(cellText(ratio, null)).toBe("—");
  });
  it("value: count / s / min / usd / không đơn vị / n", () => {
    expect(cellText({ kind: "value", unit: "count" }, { value: 1234 })).toBe("1.234");
    expect(cellText({ kind: "value", unit: "s" }, { value: 9.84, n: 340 })).toBe("9,8\u00a0giây (n=340)");
    expect(cellText({ kind: "value", unit: "min" }, { value: 14.5, n: 20 })).toBe("14,5\u00a0phút (n=20)");
    expect(cellText({ kind: "value", unit: "min" }, { value: 14.5, n: 19 })).toBe("chưa đủ dữ liệu (n=19)");
    expect(cellText({ kind: "value", unit: "usd" }, { value: 0.0042, n: 340 })).toBe("0,0042\u00a0USD (n=340)");
    expect(cellText({ kind: "value" }, { value: 2.5 })).toBe("2,5");
    expect(cellText({ kind: "value", unit: "s" }, { value: null, n: 40 })).toBe("—");
    expect(cellText({ kind: "value", unit: "s" }, null)).toBe("—");
  });
  it("không chữ đánh giá / mũi tên trong mọi ô của fixture", () => {
    const d = buildStrategies("real", "a", "b");
    const all = d.metrics.flatMap((m) => d.strategies.map((s) => cellText(m, m.values[s] ?? null)));
    expect(all.filter((t) => /[↑↓▲▼]|tốt|xấu|điểm/i.test(t))).toStrictEqual([]);
  });
});

// ------------------------------------------------------------------------------------------------ t152, t153

const base = {
  escalation_id: 1,
  ticket_id: "t-1",
  exit_code: "E3",
  priority: 6,
  label: "Thường",
  reason_detail: null,
  is_deny_case: false,
  handoff_note: { request: "", done_so_far: "", why_escalated: "", next_for_l2: "" },
  assigned_to: null,
  created_at: "2026-10-26T01:00:00Z",
};
const closed = { ...base, escalation_id: 2, closed_at: "2026-10-26T02:00:00Z", close_result: "completed", closed_by: "long.nh" };

describe("t152: parseQueuePage — {items, next_cursor} đọc chặt theo trạng thái", () => {
  it("hợp lệ: mở; đóng (có / không close_note); next_cursor chuỗi hoặc null", () => {
    expect(parseQueuePage({ items: [base], next_cursor: "abc" }, "open").next_cursor).toBe("abc");
    expect(parseQueuePage({ items: [{ ...base, closed_at: null, close_result: null, closed_by: null }], next_cursor: null }, "open").items).toHaveLength(1);
    expect(parseQueuePage({ items: [closed, { ...closed, escalation_id: 3, close_note: null }, { ...closed, escalation_id: 4, close_note: "xong" }], next_cursor: null }, "closed").items).toHaveLength(3);
  });
  it.each([
    ["mảng trần (backend cũ)", [base], "open"],
    ["thiếu next_cursor", { items: [base] }, "open"],
    ["next_cursor rỗng", { items: [base], next_cursor: "" }, "open"],
    ["escalation_id không an toàn", { items: [{ ...base, escalation_id: 2 ** 53 }], next_cursor: null }, "open"],
    ["is_deny_case thiếu", { items: [{ ...base, is_deny_case: undefined }], next_cursor: null }, "open"],
    ["ca mở mang closed_at", { items: [{ ...base, closed_at: "2026-10-26T02:00:00Z" }], next_cursor: null }, "open"],
    ["ca đóng thiếu closed_by", { items: [{ ...closed, closed_by: undefined }], next_cursor: null }, "closed"],
    ["ca đóng closed_by null", { items: [{ ...closed, closed_by: null }], next_cursor: null }, "closed"],
    ["ca đóng thiếu close_result", { items: [{ ...closed, close_result: undefined }], next_cursor: null }, "closed"],
    ["close_result ngoài enum", { items: [{ ...closed, close_result: "resolved" }], next_cursor: null }, "closed"],
    ["close_note là số", { items: [{ ...closed, close_note: 1 }], next_cursor: null }, "closed"],
  ])("%s → 502 invalid_queue_body", (_n, body, status) => bad(() => parseQueuePage(body, status as "open" | "closed"), "invalid_queue_body"));
});

describe("t153: URL hàng đợi — status, limit 50 (≤ 100), after nguyên chuỗi mờ (mã hoá)", () => {
  it("trang đầu không có after; trang sau after = next_cursor", async () => {
    expect(QUEUE_PAGE_LIMIT).toBe(50);
    expect(queuePath("open", null)).toBe("/api/escalations/queue?status=open&limit=50");
    expect(queuePath("closed", "a+b/=")).toBe("/api/escalations/queue?status=closed&limit=50&after=a%2Bb%2F%3D");
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        calls.push(url);
        return json(200, { items: [], next_cursor: null });
      }),
    );
    await getEscalationQueuePage("closed", "cur-50");
    expect(calls).toStrictEqual(["/api/escalations/queue?status=closed&limit=50&after=cur-50"]);
  });
  it("loadedItems: nối các trang theo thứ tự, bỏ trùng id (giữ lần đầu)", () => {
    const page = (ids: number[], next: string | null): EscalationQueuePage => ({ items: ids.map((i) => ({ ...base, escalation_id: i })), next_cursor: next });
    const data = { pages: [page([5, 3, 9], "x"), page([9, 1], null)], pageParams: [null, "x"] };
    expect(loadedItems(data)!.map((i) => i.escalation_id)).toStrictEqual([5, 3, 9, 1]);
    expect(loadedItems(undefined)).toBeUndefined();
  });
});

// ------------------------------------------------------------------------------------------------ t154

describe("t154: closeEscalation — CLOSE_AVAILABLE false → không gọi mạng", () => {
  it("vitest (không DEV-mock): ném 'close_unavailable', 0 fetch", async () => {
    const fetch = vi.fn();
    vi.stubGlobal("fetch", fetch);
    expect(CLOSE_AVAILABLE).toBe(false);
    await expect(closeEscalation(1, { close_result: "completed", note: "x" })).rejects.toThrow("close_unavailable");
    expect(fetch).not.toHaveBeenCalled();
  });
});

// ------------------------------------------------------------------------------------------------ t155, t156

const approval = (): ApprovalViewP4 => {
  const f = buildApprovalFixtures(Date.parse("2026-10-26T01:00:00Z")).find((x) => x.approval_id === "apv-demo-01")!;
  return f.view as ApprovalViewP4;
};

describe("t155: parseApprovalView + matched_rules (khoá gốc, tuỳ chọn) — sai KIỂU → 502 cả phiếu; sai SỐ applied → không 502", () => {
  it("hợp lệ: có khoá (3 luật), thiếu khoá, mảng rỗng; 2 luật applied vẫn qua parser (màn báo tại bảng)", () => {
    expect(parseApprovalView(approval()).matched_rules).toHaveLength(3);
    const noKey = without(approval(), "matched_rules");
    expect(parseApprovalView(noKey).matched_rules).toBeUndefined();
    expect(parseApprovalView({ ...approval(), matched_rules: [] }).matched_rules).toStrictEqual([]);
    const two = approval().matched_rules!.map((r) => ({ ...r, applied: true }));
    expect(parseApprovalView({ ...approval(), matched_rules: two }).matched_rules).toHaveLength(3);
  });
  it.each([
    ["không phải mảng", { rule_id: "R1" }],
    ["null", null],
    ["decision lạ", [{ rule_id: "R1", description: null, decision: "maybe", applied: true }]],
    ["applied không phải boolean", [{ rule_id: "R1", description: null, decision: "allow", applied: "yes" }]],
    ["thiếu description", [{ rule_id: "R1", decision: "allow", applied: true }]],
    ["thừa khoá", [{ rule_id: "R1", description: null, decision: "allow", applied: true, score: 1 }]],
  ])("%s → 502 invalid_approval_body", (_n, rules) => bad(() => parseApprovalView({ ...approval(), matched_rules: rules }), "invalid_approval_body"));
});

describe("t156: parseTrace — policy.matched_rules TUỲ CHỌN ở bước B13/B14; khoá lạ khác vẫn 502", () => {
  const policy = { rule_id: "R18", rule_description: "x", policy_decision: "approval_required", risk_level: "medium", decided_by: "rule", raw_prob: null, calibrated_prob: null };
  const EMPTY = { screen: null, classify: null, diagnose: null, sources: null, approval: null, execution: null, outcome: null };
  const trace = (p: unknown) => ({
    ticket_id: "t-1",
    is_parent: false,
    parent_ticket_id: null,
    children: [],
    steps: [{ step: "B13/B14", event: "risk_decided", at: "2099-09-26T01:00:00Z", ...EMPTY, policy: p }],
  });
  const rule = { rule_id: "R18", description: null, decision: "approval_required", applied: true };
  it("thiếu khoá / mảng rỗng / có luật → hợp lệ", () => {
    expect(parseTrace(trace(policy)).steps[0]!.policy!.matched_rules).toBeUndefined();
    expect(parseTrace(trace({ ...policy, matched_rules: [] })).steps[0]!.policy!.matched_rules).toStrictEqual([]);
    expect(parseTrace(trace({ ...policy, matched_rules: [rule] })).steps[0]!.policy!.matched_rules).toStrictEqual([rule]);
  });
  it.each([
    ["matched_rules null", { ...policy, matched_rules: null }],
    ["luật sai kiểu", { ...policy, matched_rules: [{ ...rule, applied: 1 }] }],
    ["khoá lạ khác trong policy", { ...policy, extra: 1 }],
    ["thiếu khoá bắt buộc", without(policy, "rule_id")],
  ])("%s → 502 invalid_trace_body", (_n, p) => bad(() => parseTrace(trace(p)), "invalid_trace_body"));
});

// ------------------------------------------------------------------------------------------------ t187, t188 (hợp đồng sửa 21:15/21:30)

describe("t187: matched_rules.decision null (luật đã xoá khỏi chính sách) → parser NHẬN (không 502 cả phiếu / nhật ký)", () => {
  const nullRule = { rule_id: "R99", description: null, decision: null, applied: false };
  it("phiếu duyệt + nhật ký", () => {
    expect(parseApprovalView({ ...approval(), matched_rules: [nullRule] }).matched_rules).toStrictEqual([nullRule]);
    const step = { step: "B13/B14", event: "risk_decided", at: "2099-09-26T01:00:00Z", screen: null, classify: null, diagnose: null, sources: null, approval: null, execution: null, outcome: null };
    const policy = { rule_id: null, rule_description: null, policy_decision: null, risk_level: "high", decided_by: "llm", raw_prob: 0.9, calibrated_prob: null, matched_rules: [nullRule] };
    const t = parseTrace({ ticket_id: "t", is_parent: false, parent_ticket_id: null, children: [], steps: [{ ...step, policy }] });
    expect(t.steps[0]!.policy!.matched_rules).toStrictEqual([nullRule]);
  });
  it("decision là chuỗi lạ vẫn 502", () => bad(() => parseApprovalView({ ...approval(), matched_rules: [{ ...nullRule, decision: "x" }] }), "invalid_approval_body"));
});

describe("t188: parseCloseResult — 200 `{…, new_ticket_id}`: chuỗi mã hợp lệ → giữ; thiếu / null / sai kiểu → null (không làm vỡ)", () => {
  it.each([
    [{ escalation_id: 1, close_result: "reopened_as_new", new_ticket_id: "tkt-moi-1" }, "tkt-moi-1"],
    [{ escalation_id: 1, close_result: "completed", new_ticket_id: null }, null],
    [{ escalation_id: 1, close_result: "completed" }, null],
    [{ new_ticket_id: 5 }, null],
    [{ new_ticket_id: "<b>x</b>" }, null],
    [null, null],
    ["ok", null],
  ])("%j → %s", (body, expected) => {
    expect(parseCloseResult(body).new_ticket_id).toBe(expected);
  });
});
