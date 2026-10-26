// Tổng quan Trưởng BP IT (F5) — route thật M9 A3 @3f15afb (backend/app/api/dashboard.py): `GET /api/dashboard/business`,
// `GET /api/dashboard/ai` → `{from, to, unavailable, [scope,] metrics}` (chỉ số nằm trong `metrics`, KHÔNG ở gốc). 503
// `monitor_unavailable` (fail-closed của M9) → "Số liệu tạm thời không có" — KHÔNG hiện số cũ (KH mục 5): không
// `placeholderData`, màn bỏ `data` khi có lỗi. `from`/`to` bắt buộc có múi giờ (thiếu → 422 `query.from`) — dựng ở
// routes/manager/range.ts. Thân sai hình dạng → 502 `invalid_dashboard_body`: không dựng màn từ dữ liệu không rõ.
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { AiDashboard, BusinessDashboard, StrategiesDashboard, StrategySource } from "./types.ts";

export type DashboardWindow = { from: string; to: string };
export type DashboardKind = "business" | "ai";

const query = (w: DashboardWindow) => `from=${encodeURIComponent(w.from)}&to=${encodeURIComponent(w.to)}`;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const isNumber = (value: unknown) => typeof value === "number";
const isNumberOrNull = (value: unknown) => value === null || typeof value === "number";
/** Object mà mọi giá trị qua `ok` (object rỗng hợp lệ). */
const isMapOf = (value: unknown, ok: (v: unknown) => boolean) => isRecord(value) && Object.values(value).every(ok);

/**
 * Chỉ số có hình dạng lồng: khoá CÓ MẶT thì phải đúng dạng (hoặc null); khoá THIẾU không làm hỏng cả màn — ô đó hiện
 * "Máy chủ không trả chỉ số này" (`metricText`). Chỉ số số đơn (tỉ lệ, đếm) không kiểm ở đây: `metricText` tự hiện.
 */
type Shape = (value: unknown) => boolean;
const nullable = (shape: Shape): Shape => (value) => value === null || shape(value);

const BUSINESS_SHAPES: Record<string, Shape> = {
  escalation_rate_weighted: nullable(
    (v) => isRecord(v) && isNumberOrNull(v.weighted) && isMapOf(v.by_group, isNumberOrNull) && isMapOf(v.sensitivity, isNumberOrNull),
  ),
  decided_by_distribution: nullable((v) => isMapOf(v, isNumber)),
  top_matched_rules: nullable((v) => Array.isArray(v) && v.every((r) => isRecord(r) && typeof r.rule_id === "string" && isNumber(r.count))),
  e1_split: nullable((v) => isRecord(v) && isNumber(v.total) && isMapOf(v.counts, isNumber)),
  e3_cases: nullable(
    (v) =>
      isRecord(v) &&
      typeof v.truncated === "boolean" &&
      Array.isArray(v.items) &&
      v.items.every(
        (c) =>
          isRecord(c) &&
          typeof c.ticket_id === "string" &&
          typeof c.created_at === "string" &&
          typeof c.request_excerpt === "string" &&
          (c.intent === null || c.intent === undefined || typeof c.intent === "string") &&
          (c.kb_version === null || c.kb_version === undefined || typeof c.kb_version === "string"),
      ),
  ),
};

const AI_SHAPES: Record<string, Shape> = {
  cost_per_day: nullable((v) => Array.isArray(v) && v.every((d) => isRecord(d) && typeof d.day_start === "string" && isNumber(d.cost_usd))),
  latency_p95_by_step: nullable((v) => isMapOf(v, isNumber)),
};

/** Khung chung: `from`/`to` chuỗi, `unavailable` mảng chuỗi, `metrics` object; khoá có mặt của `metrics` đúng `shapes`. */
function framed(body: unknown, shapes: Record<string, Shape>): body is { metrics: Record<string, unknown> } {
  if (!isRecord(body) || typeof body.from !== "string" || typeof body.to !== "string") return false;
  if (!Array.isArray(body.unavailable) || !body.unavailable.every((n) => typeof n === "string")) return false;
  const metrics = body.metrics;
  if (!isRecord(metrics)) return false;
  return Object.entries(shapes).every(([name, ok]) => metrics[name] === undefined || ok(metrics[name]));
}

/** `scope` phải là "all" (`dashboard:read:all`): "own" (L1) có tập chỉ số khác — màn này không dựng từ nó. */
export function parseBusiness(body: unknown): BusinessDashboard {
  if (!framed(body, BUSINESS_SHAPES) || (body as { scope?: unknown }).scope !== "all") throw new ApiError(502, "invalid_dashboard_body");
  return body as unknown as BusinessDashboard;
}

export function parseAi(body: unknown): AiDashboard {
  if (!framed(body, AI_SHAPES)) throw new ApiError(502, "invalid_dashboard_body");
  return body as unknown as AiDashboard;
}

export async function getBusinessDashboard(w: DashboardWindow): Promise<BusinessDashboard> {
  return parseBusiness((await api.request<unknown>(`/api/dashboard/business?${query(w)}`)).data);
}

export async function getAiDashboard(w: DashboardWindow): Promise<AiDashboard> {
  return parseAi((await api.request<unknown>(`/api/dashboard/ai?${query(w)}`)).data);
}

// ---------------------------------------------------------------- So sánh phương án (route CHƯA CÓ — N-PA §2)
// `GET /api/dashboard/strategies?from=&to=&source=real|sim`. Đọc chặt: `source` trong thân PHẢI trùng `source` đã gửi
// (lệch → 502, không vẽ bảng); mỗi chỉ số có đủ ô cho MỌI chiến lược của `strategies` (không thừa, không thiếu); ô là
// null, ratio `{num, den}` (số nguyên ≥ 0, num ≤ den) hoặc value `{value: số|null, n?: số nguyên ≥ 0}`. Thứ tự giữ nguyên.

const isCount = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v) && v >= 0;
const sameKeys = (obj: Record<string, unknown>, keys: readonly string[]) =>
  Object.keys(obj).length === keys.length && keys.every((k) => Object.hasOwn(obj, k));

function isCell(kind: unknown, cell: unknown): boolean {
  if (cell === null) return true;
  if (!isRecord(cell)) return false;
  if (kind === "ratio") return sameKeys(cell, ["num", "den"]) && isCount(cell.num) && isCount(cell.den) && cell.num <= cell.den;
  if (kind !== "value") return false;
  const keys = Object.keys(cell);
  if (!keys.every((k) => k === "value" || k === "n") || !Object.hasOwn(cell, "value")) return false;
  const value = cell.value;
  return (value === null || (typeof value === "number" && Number.isFinite(value))) && (cell.n === undefined || isCount(cell.n));
}

export const BAD_STRATEGIES = "invalid_strategies_body";
/** Thân hợp lệ nhưng `source` khác nguồn đã gửi — câu riêng ở màn. */
export const SOURCE_MISMATCH = "strategies_source_mismatch";

export function parseStrategies(body: unknown, sent: StrategySource): StrategiesDashboard {
  const bad = () => new ApiError(502, BAD_STRATEGIES);
  if (!isRecord(body) || typeof body.from !== "string" || typeof body.to !== "string") throw bad();
  if (body.source !== "real" && body.source !== "sim") throw bad();
  const strategies = body.strategies;
  if (!Array.isArray(strategies) || !strategies.every((s) => typeof s === "string") || new Set(strategies).size !== strategies.length) throw bad();
  const names = strategies as string[];
  if (!Array.isArray(body.unavailable) || !body.unavailable.every((n) => typeof n === "string")) throw bad();
  const mix = body.intent_mix;
  if (!isRecord(mix) || !Object.entries(mix).every(([k, v]) => names.includes(k) && isMapOf(v, isCount))) throw bad();
  const metrics = body.metrics;
  const ok =
    Array.isArray(metrics) &&
    metrics.every(
      (m) =>
        isRecord(m) &&
        typeof m.key === "string" &&
        (m.kind === "ratio" || m.kind === "value") &&
        (m.unit === undefined || typeof m.unit === "string") &&
        isRecord(m.values) &&
        sameKeys(m.values, names) &&
        names.every((s) => isCell(m.kind, (m.values as Record<string, unknown>)[s])),
    );
  if (!ok) throw bad();
  if (body.source !== sent) throw new ApiError(502, SOURCE_MISMATCH);
  return body as unknown as StrategiesDashboard;
}

export async function getStrategiesDashboard(w: DashboardWindow, source: StrategySource): Promise<StrategiesDashboard> {
  return parseStrategies((await api.request<unknown>(`/api/dashboard/strategies?${query(w)}&source=${source}`)).data, source);
}
