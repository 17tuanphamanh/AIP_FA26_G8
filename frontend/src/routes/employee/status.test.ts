// t18–t20: nhãn trạng thái cho nhân viên (KH mục 5, 4.2) và nhịp polling [Chốt P10 §3.1].
import { describe, expect, it } from "vitest";
import {
  FINAL_NOTE,
  POLL_PROCESSING_MS,
  POLL_WAITING_MS,
  pollDelay,
  STATUS_LABEL,
  statusLabel,
  UNKNOWN_STATUS_LABEL,
} from "./status.ts";

// 14 trạng thái — backend/app/domain/states.py ALL_STATES.
const ALL_STATES = [
  "S_NEW", "S_SCREENING", "S_CLASSIFYING", "S_DIAGNOSING", "S_RETRIEVING", "S_CLARIFYING", "S_ASSESSING",
  "S_PENDING_APPROVAL", "S_EXECUTING", "S_CONFIRMING", "S_ESCALATED", "S_RESOLVED", "S_REJECTED", "S_BLOCKED",
];
const FINAL = ["S_RESOLVED", "S_ESCALATED", "S_REJECTED", "S_BLOCKED"];
const WAITING_FOR = ["clarify", "approval", "confirm", "reply"] as const;

describe("trạng thái ticket (nhân viên)", () => {
  it("t18: đủ nhãn cho 14 trạng thái; không nhãn / câu kết thúc nào chứa \"S_\"; trạng thái lạ không lộ mã", () => {
    expect(Object.keys(STATUS_LABEL).sort()).toEqual([...ALL_STATES].sort());
    for (const state of ALL_STATES) {
      expect(statusLabel(state).trim()).not.toBe("");
      expect(statusLabel(state)).not.toContain("S_");
    }
    for (const note of Object.values(FINAL_NOTE)) expect(note).not.toContain("S_");
    expect(statusLabel("S_TRANG_THAI_MOI")).toBe(UNKNOWN_STATUS_LABEL);
    expect(statusLabel(null)).toBe(UNKNOWN_STATUS_LABEL);
    expect(UNKNOWN_STATUS_LABEL).not.toContain("S_");
  });

  it("t19: E0 (S_BLOCKED) chỉ câu trung tính — không \"tấn công | injection | phát hiện | chặn\"", () => {
    const shown = [statusLabel("S_BLOCKED"), FINAL_NOTE.S_BLOCKED];
    expect(shown.every((text) => typeof text === "string" && text.length > 0)).toBe(true);
    for (const text of shown) expect(text).not.toMatch(/tấn công|injection|phát hiện|chặn/i);
  });

  it("t20: nhịp polling — 2 s đang xử lý, 10 s khi waiting_for ≠ null, dừng khi có final_state", () => {
    expect(pollDelay(undefined)).toBe(POLL_PROCESSING_MS); // lần tải đầu
    expect(pollDelay({ final_state: null, waiting_for: null })).toBe(POLL_PROCESSING_MS);
    expect(POLL_PROCESSING_MS).toBe(2_000);
    for (const waiting of WAITING_FOR) expect(pollDelay({ final_state: null, waiting_for: waiting })).toBe(POLL_WAITING_MS);
    expect(POLL_WAITING_MS).toBe(10_000);
    for (const final of FINAL) {
      expect(pollDelay({ final_state: final, waiting_for: null })).toBe(false);
      expect(pollDelay({ final_state: final, waiting_for: "confirm" })).toBe(false); // final thắng waiting_for cũ
    }
  });
});

// t122 (N-PROTO P2): trạng thái do server trả tra theo khoá riêng — khoá prototype = trạng thái lạ.
describe("t122: statusLabel — '__proto__' / 'constructor' / 'toString' → câu chung", () => {
  it("3 khoá prototype → UNKNOWN_STATUS_LABEL (chuỗi); trạng thái hợp lệ giữ nhãn cũ", () => {
    for (const status of ["__proto__", "constructor", "toString"]) expect(statusLabel(status)).toBe(UNKNOWN_STATUS_LABEL);
    expect(statusLabel("S_RESOLVED")).toBe("Đã hoàn tất");
  });
});
