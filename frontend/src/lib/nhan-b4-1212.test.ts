// B4 (soát 12/11, agent 07): E1 `injection_suspected` có nhãn riêng trên dashboard (không rơi vào "Lý do khác"); sự kiện
// `followup_reply` (B19 — người dùng nhắn tiếp sau câu trả lời KB) có nhãn trong nhật ký.
import { describe, expect, it } from "vitest";
import { E1_LABEL } from "../routes/manager/metrics.ts";
import { SU_KIEN } from "./nhan.ts";

describe("B4 nhãn 12/11", () => {
  it("E1 injection_suspected có nhãn riêng trên dashboard", () => {
    expect(E1_LABEL.injection_suspected).toBe("Nghi tấn công / lừa hệ thống");
    expect(E1_LABEL.injection_suspected).not.toBe(E1_LABEL.other);
  });
  it("sự kiện followup_reply có nhãn", () => {
    expect(SU_KIEN.followup_reply).toBe("Người dùng nhắn tiếp sau câu trả lời");
  });
});
