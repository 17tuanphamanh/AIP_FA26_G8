import { http } from "msw";
import { POLICY_MAX_BYTES, utf8Bytes } from "../../api/policy.ts";
import type { Issue } from "../../api/errors.ts";
import { buildPolicyVersions, type PolicyVersionRecord } from "../fixtures/policy.ts";
import { invalid, readJson, reply, requireAny } from "./shared.ts";

// `GET/PUT /api/policy`, `GET /api/policy/versions`, `POST /api/policy/versions/{id}/restore` — route CHƯA CÓ (Phase 7).
// Hình dạng [Đề xuất F5 — Q-fe-26; PLAN-fe mục 7 #20]. Quyền hỏi backend thật: đọc `policy:read`, ghi `policy:edit`.
// - PUT: thân đúng 2 khoá `{content, base_version_id}` → base ≠ bản đang áp dụng → 409 `version_conflict` → kiểm NGHĨA
//   GIẢ tối thiểu (chỉ để demo — luật thật là của server Phase 7) → 422 `invalid_policy` `errors[{loc, msg}]` → 201.
// - Quay lui = TẠO phiên bản mới chép nội dung bản chọn (append-only, `restored_from`), bản cũ giữ nguyên → 201.
// - KHÔNG giả lập 403 `reauth_required` (verify không nhập được OTP) — luồng đó kiểm bằng vitest t61 + F4-6.
// Trạng thái chỉ trong bộ nhớ trang (tải lại trang → về 4 phiên bản gốc).
// Xoá khi: Phase 7 có route (gen:api) — xoá cùng mocks/fixtures/policy.ts.

const RULE_TYPES = ["allow", "approval_required", "deny"];
const PUT_KEYS = ["base_version_id", "content"];

let store: PolicyVersionRecord[] | null = null;
const versions = () => (store ??= buildPolicyVersions(Date.now()));
const current = () => versions().find((v) => v.is_current)!;

/** Chỉ cho test: dựng lại dữ liệu. */
export const resetPolicy = (now: number = Date.now()) => {
  store = buildPolicyVersions(now);
};

const isRecord = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);

/**
 * Kiểm nghĩa GIẢ (demo): THRESHOLD_LOW < THRESHOLD_HIGH; `rules[i].type` ∈ allow | approval_required | deny; id luật không
 * trùng. `loc` tính từ gốc nội dung, như lỗi Pydantic (Q-fe-26).
 */
export function policyIssues(content: unknown): Issue[] {
  if (!isRecord(content)) return [{ loc: [], msg: "Nội dung chính sách phải là một object JSON" }];
  const issues: Issue[] = [];
  const c = content.constants;
  if (!isRecord(c)) {
    issues.push({ loc: ["constants"], msg: "Thiếu khối constants (object)" });
  } else {
    const low = c.THRESHOLD_LOW;
    const high = c.THRESHOLD_HIGH;
    if (typeof low !== "number") issues.push({ loc: ["constants", "THRESHOLD_LOW"], msg: "THRESHOLD_LOW phải là số" });
    if (typeof high !== "number") issues.push({ loc: ["constants", "THRESHOLD_HIGH"], msg: "THRESHOLD_HIGH phải là số" });
    if (typeof low === "number" && typeof high === "number" && !(low < high)) {
      issues.push({ loc: ["constants", "THRESHOLD_LOW"], msg: `Ngưỡng dưới ${low} phải nhỏ hơn ngưỡng trên ${high}` });
    }
  }
  const rules = content.rules;
  if (!Array.isArray(rules)) {
    issues.push({ loc: ["rules"], msg: "Thiếu danh sách rules (mảng)" });
  } else {
    const seen = new Map<string, number>();
    rules.forEach((rule, i) => {
      if (!isRecord(rule)) {
        issues.push({ loc: ["rules", i], msg: "Mỗi luật phải là một object" });
        return;
      }
      if (!RULE_TYPES.includes(rule.type as string)) {
        issues.push({ loc: ["rules", i, "type"], msg: `type "${String(rule.type)}" không hợp lệ — chỉ allow, approval_required, deny` });
      }
      if (typeof rule.id !== "string" || !rule.id) {
        issues.push({ loc: ["rules", i, "id"], msg: "Thiếu id luật" });
      } else if (seen.has(rule.id)) {
        issues.push({ loc: ["rules", i, "id"], msg: `id "${rule.id}" trùng với luật thứ ${seen.get(rule.id)! + 1}` });
      } else {
        seen.set(rule.id, i);
      }
    });
  }
  return issues;
}

const view = (v: PolicyVersionRecord) => ({
  version_id: v.version_id,
  version: v.version,
  content: v.content,
  updated_by: v.updated_by,
  updated_at: v.updated_at,
  is_current: v.is_current,
});
const item = (v: PolicyVersionRecord) => ({
  version_id: v.version_id,
  version: v.version,
  updated_by: v.updated_by,
  updated_at: v.updated_at,
  is_current: v.is_current,
  restored_from: v.restored_from,
});

/** Nối thêm một phiên bản (append-only) và đặt nó là bản đang áp dụng. */
function append(content: Record<string, unknown>, by: string, restoredFrom: string | null): PolicyVersionRecord {
  const list = versions();
  const next: PolicyVersionRecord = {
    version_id: Math.max(...list.map((v) => v.version_id)) + 1,
    version: String(Math.max(...list.map((v) => Number(v.version) || 0)) + 1),
    content: JSON.parse(JSON.stringify(content)) as Record<string, unknown>,
    updated_by: by,
    updated_at: new Date().toISOString(),
    is_current: true,
    restored_from: restoredFrom,
  };
  for (const v of list) v.is_current = false;
  list.push(next);
  return next;
}

export const policyHandlers = [
  http.get("/api/policy", async ({ request }) => {
    const who = await requireAny(request, ["policy:read"]);
    if ("response" in who) return who.response;
    return reply(view(current()));
  }),

  http.get("/api/policy/versions", async ({ request }) => {
    const who = await requireAny(request, ["policy:read"]);
    if ("response" in who) return who.response;
    return reply([...versions()].sort((a, b) => b.version_id - a.version_id).map(item));
  }),

  http.put("/api/policy", async ({ request }) => {
    const who = await requireAny(request, ["policy:edit"]);
    if ("response" in who) return who.response;
    const body = await readJson(request);
    if (!isRecord(body)) return invalid(["body"]);
    const fields = [
      ...Object.keys(body).filter((k) => !PUT_KEYS.includes(k)).map((k) => `body.${k}`),
      ...(Number.isSafeInteger(body.base_version_id) ? [] : ["body.base_version_id"]),
      ...(body.content === undefined ? ["body.content"] : []),
    ];
    if (fields.length > 0) return invalid(fields);
    if (utf8Bytes(JSON.stringify(body.content)) > POLICY_MAX_BYTES) return reply({ detail: "payload_too_large" }, 413);
    if (body.base_version_id !== current().version_id) return reply({ detail: "version_conflict" }, 409);
    const issues = policyIssues(body.content);
    if (issues.length > 0) return reply({ error: "invalid_policy", errors: issues }, 422);
    const saved = append(body.content as Record<string, unknown>, who.me.user_id, null);
    return reply({ version_id: saved.version_id, version: saved.version }, 201);
  }),

  http.post("/api/policy/versions/:id/restore", async ({ request, params }) => {
    const who = await requireAny(request, ["policy:edit"]);
    if ("response" in who) return who.response;
    const source = versions().find((v) => v.version_id === Number(params.id));
    if (!source) return reply({ detail: "not_found" }, 404);
    const saved = append(source.content, who.me.user_id, source.version);
    return reply({ version_id: saved.version_id, version: saved.version }, 201);
  }),
];
