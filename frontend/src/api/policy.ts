// Chính sách (F7, route THẬT — backend/app/api/policy.py, N-POL1): CHỈ ĐỌC + KIỂM.
// - `GET /api/policy` (`policy:read`) → `PolicyView`: bản ĐANG CHẠY nạp từ file (`version_id` 0, `version` "file-<sha8>",
//   `updated_by` null, `is_current` true).
// - `GET /api/policy/versions` (`policy:read`) → MẢNG TRẦN `PolicyVersionItem` (hiện đúng 1 mục; `restored_from` null).
// - `POST /api/policy/validate` (`policy:edit` — KHÔNG phải policy:read) → 200 `{valid: true, version_preview}`; 422
//   `{error: "invalid_policy", errors: [{loc, msg}]}` (`loc` tính từ gốc `content`) hoặc `{error: "invalid_request"}`
//   (thân sai hình dạng); 413 khi thân > 64 KB. Chỉ kiểm — không lưu, không đổi gì.
// Không có PUT / quay lui / mô phỏng (N-POL2). Thân sai hình dạng → ApiError 502 (fail-closed, không hiện dữ liệu dở).
import { queryOptions } from "@tanstack/react-query";
import type { Client } from "./client.ts";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { PolicyValidateIn, PolicyValidateOk, PolicyVersionItem, PolicyView } from "./types.ts";

/** Trần thân request của backend (`max_request_body_bytes`, mặc định 64 KB) — đếm BYTE UTF-8 của CẢ thân gửi đi. */
export const POLICY_MAX_BYTES = 64 * 1024;
export const utf8Bytes = (text: string): number => new TextEncoder().encode(text).length;
/** Số byte thân `POST /api/policy/validate` sẽ gửi (đúng chuỗi client gửi: `JSON.stringify` không thụt dòng). */
export const validateBodyBytes = (content: Record<string, unknown>): number => utf8Bytes(JSON.stringify({ content } satisfies PolicyValidateIn));

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isNullableString = (v: unknown) => v === null || typeof v === "string";

export async function getPolicy(client: Client = api): Promise<PolicyView> {
  const data = (await client.request<unknown>("/api/policy")).data;
  if (!isRecord(data) || !isNumber(data.version_id) || !isRecord(data.content)) throw new ApiError(502, "invalid_policy_body");
  return data as PolicyView;
}

function isVersionItem(v: unknown): boolean {
  if (!isRecord(v)) return false;
  return (
    isNumber(v.version_id) &&
    typeof v.version === "string" &&
    typeof v.updated_at === "string" &&
    typeof v.is_current === "boolean" &&
    isNullableString(v.updated_by) &&
    (v.restored_from === undefined || isNullableString(v.restored_from))
  );
}

export async function listPolicyVersions(client: Client = api): Promise<PolicyVersionItem[]> {
  const res = await client.request<unknown>("/api/policy/versions");
  if (!Array.isArray(res.data) || !res.data.every(isVersionItem)) throw new ApiError(502, "invalid_versions_body");
  return res.data as PolicyVersionItem[];
}

/** Chỉ KIỂM nội dung (server không lưu). Lỗi HTTP → ApiError của client (422 `invalid_policy` có `issues`). */
export async function validatePolicy(content: Record<string, unknown>, client: Client = api): Promise<PolicyValidateOk> {
  const body: PolicyValidateIn = { content };
  const data = (await client.request<unknown>("/api/policy/validate", { method: "POST", json: body })).data;
  if (!isRecord(data) || data.valid !== true || typeof data.version_preview !== "string") throw new ApiError(502, "invalid_validate_body");
  return data as PolicyValidateOk;
}

export const policyQuery = (client: Client = api) =>
  queryOptions({ queryKey: ["policy", "current"] as const, queryFn: () => getPolicy(client), retry: false });
export const policyVersionsQuery = (client: Client = api) =>
  queryOptions({ queryKey: ["policy", "versions"] as const, queryFn: () => listPolicyVersions(client), retry: false });
