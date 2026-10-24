import { http } from "msw";
import { POLICY_MAX_BYTES, utf8Bytes } from "../../api/policy.ts";
import type { Issue } from "../../api/errors.ts";
import { DEMO_UPDATED_AT, DEMO_VERSION, POLICY_DEMO } from "../fixtures/policy.ts";
import { readJson, reply, requireAny } from "./shared.ts";

// `GET /api/policy`, `GET /api/policy/versions`, `POST /api/policy/validate` — route ĐÃ CÓ ở backend (F7,
// backend/app/api/policy.py). Handler này KHÔNG nạp ở dev:mock (không có trong handlers/index.ts — route thật đi thẳng
// backend); chỉ để test chạy bằng `getResponse` với ĐÚNG hình dạng thật:
// - đọc cần `policy:read`; validate cần `policy:edit` (không phải policy:read) → thiếu → 403 `forbidden`.
// - `/versions` trả MẢNG TRẦN; bản file: `version_id` 0, `updated_by` null, `restored_from` null.
// - validate: thân > 64 KB → 413 `payload_too_large` (middleware, TRƯỚC quyền) → quyền → thân sai hình dạng (không phải
//   object đúng 1 khoá `content` là object) → 422 `invalid_request` `fields` → kiểm NGHĨA GIẢ tối thiểu (demo; luật thật
//   là của server) → 422 `invalid_policy` `errors[{loc, msg}]` → 200 `{valid: true, version_preview}`. Không lưu gì.
// Không có PUT / restore / simulate (backend: 405 / 404).

const RULE_TYPES = ["allow", "approval_required", "deny"];

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const clone = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

/**
 * Kiểm nghĩa GIẢ (demo), `loc` tính từ gốc nội dung như lỗi Pydantic của server: hằng số THRESHOLD_* là số trong [0, 1]
 * (lỗi trường → `["constants", khoá]`); THRESHOLD_LOW < THRESHOLD_HIGH (lỗi mức model → `["constants"]`);
 * `rules[i].type` ∈ allow | approval_required | deny; mỗi luật có `id`.
 */
export function policyIssues(content: Record<string, unknown>): Issue[] {
  const issues: Issue[] = [];
  const c = content.constants;
  if (!isRecord(c)) {
    issues.push({ loc: ["constants"], msg: "Field required" });
  } else {
    const ok = (key: string) => {
      const v = c[key];
      if (typeof v === "number" && v >= 0 && v <= 1) return true;
      issues.push({ loc: ["constants", key], msg: `${key} phải là số trong khoảng 0–1` });
      return false;
    };
    const low = ok("THRESHOLD_LOW");
    const high = ok("THRESHOLD_HIGH");
    if (low && high && !((c.THRESHOLD_LOW as number) < (c.THRESHOLD_HIGH as number))) {
      issues.push({ loc: ["constants"], msg: "Value error, THRESHOLD_LOW phải nhỏ hơn THRESHOLD_HIGH" });
    }
  }
  const rules = content.rules;
  if (!Array.isArray(rules)) {
    issues.push({ loc: ["rules"], msg: "Input should be a valid list" });
  } else {
    rules.forEach((rule, i) => {
      if (!isRecord(rule)) {
        issues.push({ loc: ["rules", i], msg: "Input should be a valid dictionary" });
        return;
      }
      if (!RULE_TYPES.includes(rule.type as string)) issues.push({ loc: ["rules", i, "type"], msg: "Input should be 'allow', 'approval_required' or 'deny'" });
      if (typeof rule.id !== "string" || !rule.id) issues.push({ loc: ["rules", i, "id"], msg: "Field required" });
    });
  }
  return issues;
}

/** "file-" + 8 hex (FNV-1a của JSON) — chỉ để có giá trị đúng dạng, không so được với băm của server. */
function preview(content: unknown): string {
  let h = 0x811c9dc5;
  for (const ch of JSON.stringify(content)) h = Math.imul(h ^ ch.charCodeAt(0), 0x01000193) >>> 0;
  return `file-${h.toString(16).padStart(8, "0")}`;
}

export const policyHandlers = [
  http.get("/api/policy", async ({ request }) => {
    const who = await requireAny(request, ["policy:read"]);
    if ("response" in who) return who.response;
    return reply({ version_id: 0, version: DEMO_VERSION, content: clone(POLICY_DEMO), updated_by: null, updated_at: DEMO_UPDATED_AT, is_current: true });
  }),

  http.get("/api/policy/versions", async ({ request }) => {
    const who = await requireAny(request, ["policy:read"]);
    if ("response" in who) return who.response;
    return reply([{ version_id: 0, version: DEMO_VERSION, updated_by: null, updated_at: DEMO_UPDATED_AT, is_current: true, restored_from: null }]);
  }),

  http.post("/api/policy/validate", async ({ request }) => {
    if (utf8Bytes(await request.clone().text()) > POLICY_MAX_BYTES) return reply({ detail: "payload_too_large" }, 413);
    const who = await requireAny(request, ["policy:edit"]);
    if ("response" in who) return who.response;
    const body = await readJson(request);
    if (!isRecord(body)) return reply({ error: "invalid_request", fields: [] }, 422);
    const fields = [...Object.keys(body).filter((k) => k !== "content").map(() => "<extra>"), ...(isRecord(body.content) ? [] : ["content"])];
    if (fields.length > 0) return reply({ error: "invalid_request", fields }, 422);
    const content = body.content as Record<string, unknown>;
    const issues = policyIssues(content);
    if (issues.length > 0) return reply({ error: "invalid_policy", errors: issues }, 422);
    return reply({ valid: true, version_preview: preview(content) });
  }),
];
