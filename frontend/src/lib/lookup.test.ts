// t120 (N-PROTO P1): tra bảng theo khoá RIÊNG — khoá của Object.prototype không bao giờ ra hàm/object.
import { describe, expect, it } from "vitest";
import { labelOf, ownEntry } from "./lookup.ts";

const PROTO_KEYS = ["__proto__", "constructor", "toString"] as const;

describe("t120: ownEntry / labelOf (lib/lookup.ts)", () => {
  const TABLE: Readonly<Record<string, string>> = { a: "Nhãn A" };

  it("khoá '__proto__' / 'constructor' / 'toString' → giá trị dự phòng; labelOf → chính khoá", () => {
    for (const key of PROTO_KEYS) {
      expect(ownEntry(TABLE, key, "dự phòng")).toBe("dự phòng");
      expect(ownEntry<string | null>(TABLE, key, null)).toBeNull();
      expect(labelOf(TABLE, key)).toBe(key);
    }
  });

  it("khoá hợp lệ → giá trị của bảng; khoá RIÊNG tên '__proto__' (từ JSON) → giá trị riêng đó", () => {
    expect(ownEntry(TABLE, "a", "dự phòng")).toBe("Nhãn A");
    expect(labelOf(TABLE, "a")).toBe("Nhãn A");
    expect(labelOf(TABLE, "b")).toBe("b");
    const own = JSON.parse('{"__proto__": "riêng", "constructor": "cũng riêng"}') as Record<string, string>;
    expect(ownEntry(own, "__proto__", "dự phòng")).toBe("riêng");
    expect(labelOf(own, "constructor")).toBe("cũng riêng");
    expect(labelOf(own, "toString")).toBe("toString");
  });
});
