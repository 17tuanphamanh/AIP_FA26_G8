// Nhật ký quyết định — route thật backend/app/api/trace.py: `GET /api/tickets/{id}/trace` (chỉ đọc; L1, L2, Trưởng BP IT —
// quyền `ticket:read:any`; nhân viên 403; không có / không được đọc → CÙNG 404). Kiểu lấy thẳng từ `schema.gen.ts`
// (response_model `TicketTrace`). Thân sai hình dạng — thiếu khoá, THỪA khoá, sai kiểu, giá trị ngoài miền — → 502
// `invalid_trace_body`: màn không dựng gì từ dữ liệu không rõ (fail-closed, như llmStatus.ts).
import { queryOptions } from "@tanstack/react-query";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import { isMatchedRule } from "./matchedRules.ts";
import type { components } from "./schema.gen.ts";
import type { MatchedRule } from "./types.ts";

type S = components["schemas"];
// N-PA §3: khối `policy` (bước B13/B14) có `matched_rules` TUỲ CHỌN. openapi (be-thong-bao 56ea4d9) khai `| null` (Pydantic
// `list | None = None`) nhưng route thật BỎ khoá thay vì gửi null (`response_model_exclude_unset`, backend/app/api/trace.py)
// → giữ chặt: thiếu khoá = chưa có dữ liệu, null = 502 như mọi sai kiểu.
export type PolicyInfo = Omit<S["PolicyInfo"], "matched_rules"> & { matched_rules?: MatchedRule[] };
export type TraceStep = Omit<S["TraceStep"], "policy"> & { policy: PolicyInfo | null };
export type TicketTrace = Omit<S["TicketTrace"], "steps"> & { steps: TraceStep[] };
export type TraceChild = S["TraceChild"];
export type ScreenInfo = S["ScreenInfo"];
export type ClassifyInfo = S["ClassifyInfo"];
export type ApprovalInfo = S["ApprovalInfo"];
export type ExecutionInfo = S["ExecutionInfo"];
export type OutcomeInfo = S["OutcomeInfo"];

/** Ký tự của mã ticket thật (uuid), mã con `<cha>-<i>` và mã fixture; ≤ 64 (cột `tickets.ticket_id`). */
export const TRACE_TICKET_ID = /^[A-Za-z0-9._-]{1,64}$/;
export const tracePath = (ticketId: string): string => `/trace/${encodeURIComponent(ticketId)}`;

type Check = (value: unknown) => boolean;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const str: Check = (v) => typeof v === "string";
const bool: Check = (v) => typeof v === "boolean";
const prob: Check = (v) => typeof v === "number" && Number.isFinite(v) && v >= 0 && v <= 1;
const date: Check = (v) => typeof v === "string" && !Number.isNaN(Date.parse(v));
const nullable =
  (check: Check): Check =>
  (v) =>
    v === null || check(v);
const oneOf =
  (...allowed: string[]): Check =>
  (v) =>
    typeof v === "string" && allowed.includes(v);
const listOf =
  (check: Check): Check =>
  (v) =>
    Array.isArray(v) && v.every(check);
/** Đúng TẬP khoá (backend `extra="forbid"`) và từng khoá đúng kiểu. `optional`: khoá được vắng; có mặt thì phải đúng kiểu. */
const shape =
  (fields: Record<string, Check>, optional: Record<string, Check> = {}): Check =>
  (v) => {
    if (!isRecord(v)) return false;
    const keys = Object.keys(v);
    if (!Object.keys(fields).every((k) => Object.hasOwn(v, k))) return false;
    return keys.every((k) =>
      Object.hasOwn(fields, k) ? fields[k]!(v[k]) : Object.hasOwn(optional, k) ? optional[k]!(v[k]) : false,
    );
  };
const probMap: Check = (v) => isRecord(v) && Object.values(v).every(prob);

const screen = shape({
  layer: nullable(oneOf("regex", "model", "llm")),
  p_injection: nullable(prob),
  decision: nullable(oneOf("safe", "attack", "suspected", "unavailable")),
});
const classify = shape({
  intent: nullable(str),
  confidence: nullable(prob),
  model_probs: nullable(probMap),
  model_version: nullable(str),
  is_multi: nullable(bool),
});
const diagnose = shape({ fact_keys: listOf(str) });
const source = shape({ doc_id: str, title: nullable(str) });
const policy = shape({
  rule_id: nullable(str),
  rule_description: nullable(str),
  policy_decision: nullable(str),
  risk_level: nullable(str),
  decided_by: nullable(oneOf("rule", "llm")),
  raw_prob: nullable(prob),
  calibrated_prob: nullable(prob),
}, { matched_rules: listOf(isMatchedRule) });
const approval = shape({
  approver_id: nullable(str),
  approver_name: nullable(str),
  result: nullable(oneOf("pending", "approved", "rejected", "timeout")),
  at: nullable(date),
});
const execution = shape({
  action: nullable(str),
  success: nullable(bool),
  rollback_status: nullable(str),
  calls: listOf(shape({ name: str, result: oneOf("ok", "failed") })),
});
const outcome = shape({ route: nullable(str), exit_code: nullable(str) });
const step = shape({
  step: str,
  event: str,
  at: date,
  screen: nullable(screen),
  classify: nullable(classify),
  diagnose: nullable(diagnose),
  sources: nullable(listOf(source)),
  policy: nullable(policy),
  approval: nullable(approval),
  execution: nullable(execution),
  outcome: nullable(outcome),
});
const trace = shape({
  ticket_id: str,
  is_parent: bool,
  parent_ticket_id: nullable(str),
  steps: listOf(step),
  children: listOf(shape({ ticket_id: str, intent: nullable(str), exit_code: nullable(str) })),
});

export function parseTrace(body: unknown): TicketTrace {
  if (trace(body)) return body as TicketTrace;
  throw new ApiError(502, "invalid_trace_body");
}

export async function getTrace(ticketId: string): Promise<TicketTrace> {
  return parseTrace((await api.request<unknown>(`/api/tickets/${encodeURIComponent(ticketId)}/trace`)).data);
}

export const traceQuery = (ticketId: string) =>
  queryOptions({ queryKey: ["tickets", "trace", ticketId] as const, queryFn: () => getTrace(ticketId), retry: false });
