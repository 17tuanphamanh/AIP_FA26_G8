// Trạng thái LLM (I1) — route thật backend/app/api/llm_status.py: `GET /api/admin/llm-status` (chỉ đọc, quyền
// `llm_status:read`, Trưởng BP IT). 503 `monitor_unavailable` (fail-closed của M9) → "Số liệu tạm thời không có" — màn bỏ
// `data` khi có lỗi, KHÔNG hiện số cũ. Thân sai hình dạng → 502 `invalid_llm_status_body`: không dựng màn từ dữ liệu không rõ.
// Không có khoá API trong thân: chỉ boolean `api_key_configured`.
import { queryOptions } from "@tanstack/react-query";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { LlmStatus } from "./types.ts";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const isNumber = (value: unknown): value is number => typeof value === "number" && Number.isFinite(value);
const isTextOrNull = (value: unknown) => value === null || typeof value === "string";
const oneOf = (value: unknown, allowed: readonly string[]) => typeof value === "string" && allowed.includes(value);

export function parseLlmStatus(body: unknown): LlmStatus {
  if (isRecord(body)) {
    const { models, spend, usage, kb } = body;
    if (
      typeof body.as_of === "string" &&
      (body.backend === null || oneOf(body.backend, ["scripted", "real"])) &&
      isRecord(models) &&
      isTextOrNull(models.fast) &&
      isTextOrNull(models.strong) &&
      typeof body.api_key_configured === "boolean" &&
      isRecord(spend) &&
      isNumber(spend.total_usd) &&
      isNumber(spend.cap_usd) &&
      isNumber(spend.percent) &&
      isNumber(spend.warn_percent) &&
      oneOf(spend.status, ["ok", "warn", "over"]) &&
      isRecord(usage) &&
      isNumber(usage.calls_total) &&
      isNumber(usage.calls_24h) &&
      isNumber(usage.tickets_with_calls) &&
      (usage.avg_cost_per_ticket_usd === null || isNumber(usage.avg_cost_per_ticket_usd)) &&
      isRecord(kb) &&
      typeof kb.alias === "string" &&
      isTextOrNull(kb.collection) &&
      oneOf(kb.status, ["ready", "missing", "unknown"])
    ) {
      return body as LlmStatus;
    }
  }
  throw new ApiError(502, "invalid_llm_status_body");
}

export async function getLlmStatus(): Promise<LlmStatus> {
  return parseLlmStatus((await api.request<unknown>("/api/admin/llm-status")).data);
}

export const llmStatusQuery = () =>
  queryOptions({ queryKey: ["admin", "llm-status"] as const, queryFn: getLlmStatus, retry: false });
