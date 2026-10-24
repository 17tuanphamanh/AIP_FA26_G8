// t66 (N-POL1 P1): api/policy.ts gọi ĐÚNG route thật F7 (backend/app/api/policy.py) và fail-closed khi thân sai dạng —
// mỗi nhánh lỗi một test. Thân giả bám hình dạng thật: bản file `version_id` 0, `updated_by` null, `/versions` MẢNG TRẦN.
import { describe, expect, it, vi } from "vitest";
import { createClient } from "./client.ts";
import { ApiError } from "./errors.ts";
import { getPolicy, listPolicyVersions, POLICY_MAX_BYTES, validateBodyBytes, validatePolicy } from "./policy.ts";

const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const VIEW = {
  version_id: 0,
  version: "file-0a1b2c3d",
  content: { constants: { DEMO_LIMIT: 3 }, rules: [] },
  updated_by: null,
  updated_at: "2026-10-01T01:00:00Z",
  is_current: true,
};
const ITEM = { version_id: 0, version: "file-0a1b2c3d", updated_by: null, updated_at: "2026-10-01T01:00:00Z", is_current: true, restored_from: null };

/** Client thật trên fetch giả trả `res` cho MỌI lời gọi; giữ lại [url, init] để soát route. */
function clientWith(res: () => Response) {
  const fetch = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async () => res());
  return { fetch, client: createClient({ fetch, readCookie: () => null, locks: null, channel: null, onSessionEnd: vi.fn() }) };
}

async function rejection(promise: Promise<unknown>): Promise<ApiError> {
  const error = await promise.then(
    () => null,
    (e: unknown) => e,
  );
  expect(error).toBeInstanceOf(ApiError);
  return error as ApiError;
}

describe("t66a: GET /api/policy", () => {
  it("gọi GET /api/policy; thân thật (updated_by null, version_id 0) → trả nguyên", async () => {
    const { fetch, client } = clientWith(() => json(200, VIEW));
    expect(await getPolicy(client)).toStrictEqual(VIEW);
    expect(fetch.mock.calls.map(([url, init]) => [url, init?.method ?? "GET"])).toStrictEqual([["/api/policy", "GET"]]);
  });

  it.each([
    ["chuỗi", "0"],
    ["null", null],
    ["thiếu khoá", undefined],
    ["NaN (JSON null)", Number.NaN],
  ])("version_id không phải số (%s) → ApiError 502 invalid_policy_body", async (_name, versionId) => {
    const { client } = clientWith(() => json(200, { ...VIEW, version_id: versionId }));
    const error = await rejection(getPolicy(client));
    expect([error.status, error.code]).toStrictEqual([502, "invalid_policy_body"]);
  });

  it.each([
    ["mảng", []],
    ["null", null],
    ["chuỗi", "{}"],
    ["số", 1],
  ])("content không phải object (%s) → ApiError 502 invalid_policy_body", async (_name, content) => {
    const { client } = clientWith(() => json(200, { ...VIEW, content }));
    const error = await rejection(getPolicy(client));
    expect([error.status, error.code]).toStrictEqual([502, "invalid_policy_body"]);
  });

  it("thân không phải object (mảng) → invalid_policy_body", async () => {
    const { client } = clientWith(() => json(200, [VIEW]));
    expect((await rejection(getPolicy(client))).code).toBe("invalid_policy_body");
  });
});

describe("t66b: GET /api/policy/versions", () => {
  it("gọi GET /api/policy/versions; MẢNG TRẦN → trả nguyên (restored_from null hoặc không có khoá đều nhận)", async () => {
    const noRestored: Partial<typeof ITEM> = { ...ITEM };
    delete noRestored.restored_from;
    const body = [ITEM, { ...noRestored, version_id: 1, version: "file-11111111", updated_by: "it_mgr01", is_current: false }];
    const { fetch, client } = clientWith(() => json(200, body));
    expect(await listPolicyVersions(client)).toStrictEqual(body);
    expect(fetch.mock.calls.map(([url, init]) => [url, init?.method ?? "GET"])).toStrictEqual([["/api/policy/versions", "GET"]]);
  });

  it("dạng {items: [...]} (không phải mảng trần) → ApiError 502 invalid_versions_body", async () => {
    const { client } = clientWith(() => json(200, { items: [ITEM] }));
    const error = await rejection(listPolicyVersions(client));
    expect([error.status, error.code]).toStrictEqual([502, "invalid_versions_body"]);
  });

  it.each([
    ["version_id chuỗi", { ...ITEM, version_id: "0" }],
    ["thiếu is_current", { ...ITEM, is_current: undefined }],
    ["updated_by số", { ...ITEM, updated_by: 7 }],
    ["restored_from số", { ...ITEM, restored_from: 1 }],
    ["phần tử null", null],
  ])("phần tử sai dạng (%s) → invalid_versions_body", async (_name, item) => {
    const { client } = clientWith(() => json(200, [item]));
    expect((await rejection(listPolicyVersions(client))).code).toBe("invalid_versions_body");
  });
});

describe("t66c: POST /api/policy/validate", () => {
  const content = { constants: { DEMO_LIMIT: 3 }, rules: [] };

  it("gọi POST /api/policy/validate, thân ĐÚNG {content} (JSON); 200 → {valid, version_preview}", async () => {
    const { fetch, client } = clientWith(() => json(200, { valid: true, version_preview: "file-deadbeef" }));
    expect(await validatePolicy(content, client)).toStrictEqual({ valid: true, version_preview: "file-deadbeef" });
    const [url, init] = fetch.mock.calls[0]!;
    expect([url, init?.method]).toStrictEqual(["/api/policy/validate", "POST"]);
    expect(JSON.parse(String(init?.body))).toStrictEqual({ content });
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("200 mà thân sai dạng (valid khác true) → ApiError 502 invalid_validate_body", async () => {
    const { client } = clientWith(() => json(200, { valid: "yes", version_preview: "file-deadbeef" }));
    expect((await rejection(validatePolicy(content, client))).code).toBe("invalid_validate_body");
  });

  it("422 invalid_policy → ApiError có issues {loc, msg} (loc giữ số nguyên của mảng)", async () => {
    const errors = [
      { loc: ["rules", 0, "type"], msg: "Input should be 'allow', 'approval_required' or 'deny'" },
      { loc: [], msg: "NaN/Infinity không hợp lệ trong JSON policy" },
    ];
    const { client } = clientWith(() => json(422, { error: "invalid_policy", errors }));
    const error = await rejection(validatePolicy(content, client));
    expect([error.status, error.code, error.issues]).toStrictEqual([422, "invalid_policy", errors]);
  });

  it("403 forbidden → ApiError 403 (không nuốt)", async () => {
    const { client } = clientWith(() => json(403, { detail: "forbidden" }));
    const error = await rejection(validatePolicy(content, client));
    expect([error.status, error.code]).toStrictEqual([403, "forbidden"]);
  });

  it("trần 64 KB đếm BYTE UTF-8 của CẢ thân gửi đi (chữ có dấu 3 byte)", () => {
    expect(validateBodyBytes({})).toBe('{"content":{}}'.length);
    expect(validateBodyBytes({ a: "ệ" })).toBe('{"content":{"a":""}}'.length + 3);
    expect(POLICY_MAX_BYTES).toBe(64 * 1024);
  });
});
