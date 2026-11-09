// Q1 + Q12 (ĐP 09/11): loại yêu cầu mới `it_help` ("Hỏi đáp IT") và 3 sự kiện mới của luồng hỏi phân loại / chỉ-trả-lời.
// Test viết trước (DỪNG 1 phần 2) — đỏ tới khi nhan.ts có nhãn.
import { describe, expect, it } from "vitest";
import { LOAI_YEU_CAU, SU_KIEN, nhanIT } from "./nhan.ts";

const DANG_NOI_BO = /[a-z]+_[a-z_]+|\bB\d+\b|\bE\d\b/;

describe("Q12: nhãn loại yêu cầu it_help", () => {
  it("it_help → Hỏi đáp IT; 4 loại cũ giữ nguyên", () => {
    expect(LOAI_YEU_CAU.it_help).toBe("Hỏi đáp IT");
    expect(nhanIT("loai_yeu_cau", "it_help")).toEqual({ nhan: "Hỏi đáp IT", ma: "it_help" });
    expect({ vpn: LOAI_YEU_CAU.vpn, account: LOAI_YEU_CAU.account, software: LOAI_YEU_CAU.software, access: LOAI_YEU_CAU.access }).toEqual({
      vpn: "VPN",
      account: "Tài khoản",
      software: "Phần mềm",
      access: "Quyền truy cập",
    });
  });
});

describe("Q1 + Q12: nhãn sự kiện mới", () => {
  it.each(["triage_asked", "triage_reply", "diagnosis_not_applicable"])("%s có nhãn, không lộ mã nội bộ", (ev) => {
    const t = SU_KIEN[ev];
    expect(typeof t).toBe("string");
    expect(t).not.toMatch(DANG_NOI_BO);
    expect(nhanIT("su_kien", ev).nhan).toBe(t);
  });
});
