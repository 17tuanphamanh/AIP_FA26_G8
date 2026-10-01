// Chính sách (F5): `GET/PUT /api/policy`, `GET /api/policy/versions`, `POST /api/policy/versions/{id}/restore` (P10 §3.3
// — chỉ có TÊN route; hình dạng là [Đề xuất F5 — chốt lại khi làm Phase 7], Q-fe-26, PLAN-fe mục 7 #20). Route CHƯA
// CÓ (Phase 7): MSW bật → mocks/handlers/policy.ts; tắt → backend 404 "Not Found" → "Chính sách có từ Phase 7".
// Lưu và quay lui cần đăng nhập ≤ 10 phút (P10 §3.3) → 403 `reauth_required` → hộp đăng nhập lại, gửi lại ĐÚNG 1 lần
// (components/useReauthRetry.tsx). Không tự lưu, không lưu nháp vào bộ nhớ trình duyệt.
import { queryOptions } from "@tanstack/react-query";
import type { Client } from "./client.ts";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { PolicyPutIn, PolicySaved, PolicyVersionItem, PolicyView } from "./types.ts";

/** Trần kích thước nội dung gửi đi [Đề xuất F5]: 64 KB tính bằng BYTE UTF-8 (chữ có dấu tốn 2–3 byte). */
export const POLICY_MAX_BYTES = 64 * 1024;
export const utf8Bytes = (text: string): number => new TextEncoder().encode(text).length;

export async function getPolicy(client: Client = api): Promise<PolicyView> {
  const data = (await client.request<unknown>("/api/policy")).data;
  const view = data as Partial<PolicyView> | null;
  if (view === null || typeof view !== "object" || typeof view.version_id !== "number" || view.content === null || typeof view.content !== "object") {
    throw new ApiError(502, "invalid_policy_body");
  }
  return data as PolicyView;
}

export async function listPolicyVersions(client: Client = api): Promise<PolicyVersionItem[]> {
  const res = await client.request<unknown>("/api/policy/versions");
  if (!Array.isArray(res.data)) throw new ApiError(502, "invalid_versions_body");
  return res.data as PolicyVersionItem[];
}

/** `client` mặc định là client dùng chung — CÙNG client với đăng nhập lại (403 `reauth_required`). */
export async function putPolicy(body: PolicyPutIn, client: Client = api): Promise<PolicySaved> {
  return (await client.request<PolicySaved>("/api/policy", { method: "PUT", json: body })).data;
}

export async function restorePolicyVersion(versionId: number, client: Client = api): Promise<PolicySaved> {
  const path = `/api/policy/versions/${encodeURIComponent(String(versionId))}/restore`;
  return (await client.request<PolicySaved>(path, { method: "POST" })).data;
}

export const policyQuery = (client: Client = api) =>
  queryOptions({ queryKey: ["policy", "current"] as const, queryFn: () => getPolicy(client), retry: false });
export const policyVersionsQuery = (client: Client = api) =>
  queryOptions({ queryKey: ["policy", "versions"] as const, queryFn: () => listPolicyVersions(client), retry: false });
