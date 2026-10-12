// t121 (N-PROTO P4): mã lỗi của server tra CODE_MESSAGES theo khoá riêng — mã "__proto__" / "constructor" / "toString"
// là mã lạ (câu chung theo status), không bao giờ là hàm của prototype.
import { describe, expect, it } from "vitest";
import { ApiError, errorMessage } from "./errors.ts";

const PROTO_KEYS = ["__proto__", "constructor", "toString"] as const;

describe("t121: errorMessage — mã lỗi trùng tên khoá prototype = mã lạ", () => {
  it.each([400, 404, 409, 422, 500, 503])("status %i: 3 mã prototype → đúng câu của mã lạ cùng status, luôn là chuỗi", (status) => {
    const unknown = errorMessage(new ApiError(status, "ma_la_chua_biet"));
    for (const code of PROTO_KEYS) {
      const message = errorMessage(new ApiError(status, code));
      expect(typeof message).toBe("string");
      expect(message).toBe(unknown);
      expect(message).not.toMatch(/function |\[object /);
    }
  });

  it("mã hợp lệ vẫn ra câu riêng", () => {
    expect(errorMessage(new ApiError(503, "ticket_busy"))).toBe("Hệ thống đang bận, sẽ tự thử lại.");
    expect(errorMessage(new ApiError(409, "plan_changed"))).toBe("Hành động đã thay đổi sau khi tạo phiếu — không thể duyệt");
  });
});
