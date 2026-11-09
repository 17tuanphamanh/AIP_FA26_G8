// F6 #76 — parseApprovalView: thân xem phiếu thiếu / sai kiểu người bị ảnh hưởng hoặc mức rủi ro → 502 invalid_approval_body
// (fail-closed: màn không hiện phiếu, không có thanh quyết định). Thân đúng → trả NGUYÊN object.
import { describe, expect, it } from "vitest";
import { parseApprovalView } from "./approvals.ts";
import { ApiError } from "./errors.ts";

const RISK = { decided_by: "rule", matched_rule_id: "R-demo", reason: "Luật minh hoạ", thresholds: null };
const RISK_VIEW = {
  decided_by: "rule",
  policy_decision: "approval_required",
  matched_rule_id: "R-demo",
  raw_prob: null,
  calibrated_prob: null,
  p_method: null,
  risk_level: "medium",
  route: "HITL",
  reason: "Luật minh hoạ",
  thresholds: null,
  calibrated: false,
  auto_allowed: false,
};
const AFFECTED = { user_id: "u-1", is_requester: true, department: "Finance", manager: { status: "known", user_id: "m-1", full_name: "Quản lý Một" } };
const body = (over: Record<string, unknown> = {}) => ({ approval_id: "a", risk: RISK, risk_view: RISK_VIEW, affected: AFFECTED, ...over });

const rejects = (value: unknown) => {
  try {
    parseApprovalView(value);
  } catch (e) {
    return e instanceof ApiError && e.status === 502 && e.code === "invalid_approval_body";
  }
  return false;
};

describe("t140: parseApprovalView — thân đúng đi qua nguyên vẹn", () => {
  it("đủ affected + risk_view; risk_view null chỉ khi risk null; llm chưa hiệu chỉnh hợp lệ", () => {
    const ok = body();
    expect(parseApprovalView(ok)).toBe(ok);
    const none = body({ risk: null, risk_view: null });
    expect(parseApprovalView(none)).toBe(none);
    const llm = body({
      risk_view: { ...RISK_VIEW, decided_by: "llm", policy_decision: null, matched_rule_id: null, raw_prob: 0.6, p_method: "self_report", risk_level: "high" },
    });
    expect(parseApprovalView(llm)).toBe(llm);
    const calibrated = body({ risk_view: { ...RISK_VIEW, calibrated_prob: 0.4, calibrated: true, thresholds: [0.3, 0.7] } });
    expect(parseApprovalView(calibrated)).toBe(calibrated);
  });

  it("quản lý: known không tên (sếp chưa đăng nhập) và unknown đều hợp lệ; phòng ban null hợp lệ", () => {
    const noName = body({ affected: { ...AFFECTED, manager: { status: "known", user_id: "m-1", full_name: null } } });
    expect(parseApprovalView(noName)).toBe(noName);
    const unknown = body({ affected: { ...AFFECTED, department: null, is_requester: false, manager: { status: "unknown", user_id: null, full_name: null } } });
    expect(parseApprovalView(unknown)).toBe(unknown);
  });
});

describe("t141: parseApprovalView — sai kiểu / thiếu → 502 invalid_approval_body", () => {
  it("không phải object", () => {
    for (const bad of [null, undefined, "x", 1, [], [body()]]) expect(rejects(bad)).toBe(true);
  });

  it("affected thiếu, null, sai kiểu từng trường", () => {
    const bads: unknown[] = [
      undefined,
      null,
      "nv001",
      [],
      { ...AFFECTED, user_id: 7 },
      { ...AFFECTED, user_id: "" },
      { ...AFFECTED, is_requester: "true" },
      { ...AFFECTED, is_requester: undefined },
      { ...AFFECTED, department: 3 },
      { ...AFFECTED, manager: undefined },
      { ...AFFECTED, manager: null },
      { ...AFFECTED, manager: { status: "none", user_id: null, full_name: null } }, // KHÔNG có giá trị "không có quản lý"
      { ...AFFECTED, manager: { status: "known", user_id: null, full_name: "X" } }, // known thiếu user_id
      { ...AFFECTED, manager: { status: "unknown", user_id: "m-1", full_name: null } }, // unknown mà có id
      { ...AFFECTED, manager: { status: "unknown", user_id: null, full_name: "X" } },
      { ...AFFECTED, manager: { status: "known", user_id: 5, full_name: null } },
    ];
    for (const affected of bads) expect(rejects(body({ affected })), JSON.stringify(affected)).toBe(true);
    expect(rejects({ approval_id: "a", risk: RISK, risk_view: RISK_VIEW })).toBe(true); // khoá `affected` vắng hẳn
  });

  it("risk_view sai enum / kiểu / cờ lệch trường gốc / null lệch risk", () => {
    const bads: unknown[] = [
      "medium",
      [],
      { ...RISK_VIEW, risk_level: "critical" },
      { ...RISK_VIEW, risk_level: undefined },
      { ...RISK_VIEW, route: "BLOCK" },
      { ...RISK_VIEW, decided_by: "human" },
      { ...RISK_VIEW, policy_decision: "maybe" },
      { ...RISK_VIEW, p_method: "guess" },
      { ...RISK_VIEW, reason: null },
      { ...RISK_VIEW, matched_rule_id: 1 },
      { ...RISK_VIEW, raw_prob: "0.5" },
      { ...RISK_VIEW, thresholds: [0.3] },
      { ...RISK_VIEW, thresholds: ["a", "b"] },
      { ...RISK_VIEW, calibrated: "no" },
      { ...RISK_VIEW, calibrated: true }, // calibrated_prob null mà cờ true
      { ...RISK_VIEW, calibrated_prob: 0.4 }, // có xác suất mà cờ false
      { ...RISK_VIEW, auto_allowed: true }, // route HITL mà cờ true
      { ...RISK_VIEW, route: "AUTO" }, // route AUTO mà cờ false
    ];
    for (const risk_view of bads) expect(rejects(body({ risk_view })), JSON.stringify(risk_view)).toBe(true);
    expect(rejects(body({ risk_view: null }))).toBe(true); // risk có mà risk_view null
    expect(rejects(body({ risk: null }))).toBe(true); // risk_view có mà risk null
    expect(rejects(body({ risk: "x" }))).toBe(true);
    expect(rejects(body({ risk: undefined, risk_view: null }))).toBe(true);
  });
});
