// Cách xử lý của hệ thống (D-67) — route CHƯA CÓ ở backend (be-tuan8), hợp đồng chốt ĐP 26/10 17:30 §1:
// - `GET /api/admin/strategy` (`policy:read`) → `StrategyView`.
// - `PUT /api/admin/strategy` thân `{strategy, reason}` (manager, đăng nhập gần đây) → 200 thân như GET. Lỗi: 403
//   `reauth_required` (luồng xác nhận lại — useReauthRetry), 403 `forbidden`, 422 `fields:["reason"|"strategy"]`, 409
//   `same_as_current`.
// - `GET /api/admin/strategy/history?limit=` → `{items, truncated}`, mới nhất lên trước.
// Đọc chặt: thân sai hình dạng → ApiError 502 (không dựng màn từ dữ liệu không rõ). dev:mock: mocks/handlers/strategy.ts.
import { queryOptions } from "@tanstack/react-query";
import type { Client } from "./client.ts";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { RuntimeStrategy, StrategyChange, StrategyHistory, StrategyIn, StrategyView } from "./types.ts";

export const RUNTIME_STRATEGIES: readonly RuntimeStrategy[] = ["rule_only", "hybrid", "hybrid_guarded"];
/** Số dòng lịch sử xin mỗi lần (backend: 1–200, mặc định 50). */
export const STRATEGY_HISTORY_LIMIT = 50;
/** `reason`: 10–500 ký tự sau khi cắt khoảng trắng (đếm ký tự như `len()` của Python — theo code point). */
export const REASON_MIN = 10;
export const REASON_MAX = 500;

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const isStrategy = (v: unknown): v is RuntimeStrategy => typeof v === "string" && (RUNTIME_STRATEGIES as readonly string[]).includes(v);
const isNullableString = (v: unknown) => v === null || typeof v === "string";

/** Số ký tự (code point) của lý do sau khi cắt khoảng trắng hai đầu. */
export const reasonLength = (reason: string): number => Array.from(reason.trim()).length;

export function parseStrategyView(body: unknown): StrategyView {
  const ok =
    isRecord(body) &&
    isStrategy(body.strategy) &&
    Array.isArray(body.selectable) &&
    body.selectable.every(isStrategy) &&
    (body.llm_calibrated === undefined || typeof body.llm_calibrated === "boolean") &&
    typeof body.eval_mode === "boolean" &&
    isNullableString(body.changed_by) &&
    isNullableString(body.changed_at) &&
    isNullableString(body.reason);
  if (!ok) throw new ApiError(502, "invalid_strategy_body");
  return body as StrategyView;
}

const isChange = (v: unknown): v is StrategyChange =>
  isRecord(v) &&
  typeof v.changed_at === "string" &&
  typeof v.changed_by === "string" &&
  isStrategy(v.strategy_from) &&
  isStrategy(v.strategy_to) &&
  typeof v.reason === "string";

export function parseStrategyHistory(body: unknown): StrategyHistory {
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isChange) || typeof body.truncated !== "boolean") {
    throw new ApiError(502, "invalid_strategy_history_body");
  }
  return body as StrategyHistory;
}

export async function getStrategy(client: Client = api): Promise<StrategyView> {
  return parseStrategyView((await client.request<unknown>("/api/admin/strategy")).data);
}

export async function getStrategyHistory(client: Client = api): Promise<StrategyHistory> {
  return parseStrategyHistory((await client.request<unknown>(`/api/admin/strategy/history?limit=${STRATEGY_HISTORY_LIMIT}`)).data);
}

/**
 * Đổi cách xử lý. CHỈ 200 (mã duy nhất route trả khi ghi) là đã đổi; 2xx khác → 502 (không chắc đã ghi → không báo thành
 * công giả; gửi lại sẽ ra 409 `same_as_current` — đúng sự thật). Lý do gửi đi đã cắt khoảng trắng.
 */
export async function putStrategy(body: StrategyIn, client: Client = api): Promise<StrategyView> {
  const sent: StrategyIn = { strategy: body.strategy, reason: body.reason.trim() };
  const res = await client.request<unknown>("/api/admin/strategy", { method: "PUT", json: sent });
  if (res.status !== 200) throw new ApiError(502, "unexpected_strategy_status");
  return parseStrategyView(res.data);
}

export const strategyQuery = (client: Client = api) =>
  queryOptions({ queryKey: ["strategy", "current"] as const, queryFn: () => getStrategy(client), retry: false });
export const strategyHistoryQuery = (client: Client = api) =>
  queryOptions({ queryKey: ["strategy", "history"] as const, queryFn: () => getStrategyHistory(client), retry: false });
