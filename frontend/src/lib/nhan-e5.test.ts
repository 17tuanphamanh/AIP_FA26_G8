// M2 (ĐP 08/11): nhãn kết thúc E5 tách theo lý do — luật cấm (`policy_deny`) khác lớp AI lỗi (`llm_layer_disabled`). Không lộ tên
// lỗi nội bộ trong chữ; không tách "chưa bật" và "sập" (một nhãn cho mọi lỗi lớp AI).
import { describe, expect, it } from "vitest";
import { exitNhan } from "../routes/l2/queue.ts";
import { MA_KET_THUC, maKetThuc, nhanIT, nhanNhanVien } from "./nhan.ts";

const AI_LOI = "Chưa đánh giá được rủi ro — chuyển kỹ thuật viên";
const CAM = "Không được phép theo chính sách";
// Dáng tên lỗi/khoá nội bộ: snake_case, mã E*, tên lớp lỗi Python/LLM.
const DANG_NOI_BO = /[a-z]+_[a-z_]+|\bE\d\b|LLM|Estimator|Unavailable|SchemaError|Budget/;

describe("M2: nhãn kết thúc E5 theo lý do", () => {
  it("E5 + llm_layer_disabled → chưa đánh giá được rủi ro", () => {
    expect(maKetThuc("E5", "llm_layer_disabled")?.nhan).toBe(AI_LOI);
    expect(exitNhan({ exit_code: "E5", reason_detail: "llm_layer_disabled" })).toMatchObject({ nhan: AI_LOI, ma: "E5" });
  });

  it("E5 + policy_deny → không được phép theo chính sách", () => {
    expect(maKetThuc("E5", "policy_deny")?.nhan).toBe(CAM);
    expect(exitNhan({ exit_code: "E5", reason_detail: "policy_deny" })).toMatchObject({ nhan: CAM, ma: "E5" });
  });

  it("E5 lý do khác / không lý do → nhãn E5 chung như cũ; lý do trên mã khác không đổi nhãn mã đó", () => {
    for (const reason of [null, undefined, "llm_high_risk", "recheck_failed", "approval_target_unverified"]) {
      expect(maKetThuc("E5", reason)).toBe(MA_KET_THUC.E5);
    }
    expect(maKetThuc("E2", "llm_layer_disabled")).toBe(MA_KET_THUC.E2);
    expect(maKetThuc("E2", "policy_deny")).toBe(MA_KET_THUC.E2);
  });

  it("chữ nhãn và gợi ý không lộ tên lỗi nội bộ", () => {
    for (const reason of ["llm_layer_disabled", "policy_deny"]) {
      const n = maKetThuc("E5", reason);
      expect(n).not.toBeNull();
      expect(n?.nhan).not.toMatch(DANG_NOI_BO);
      expect(n?.goiY ?? "").not.toMatch(DANG_NOI_BO);
    }
  });

  it("lý do policy_deny có nhãn ở bảng lý do (IT) và chữ cho nhân viên", () => {
    expect(nhanIT("ly_do", "policy_deny")).toStrictEqual({ nhan: CAM, ma: "policy_deny" });
    expect(nhanNhanVien("ly_do", "policy_deny")).toBe(CAM);
  });
});
