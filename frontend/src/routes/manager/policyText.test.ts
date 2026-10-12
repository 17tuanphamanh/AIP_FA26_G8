// t59 (F5 P7; chốt DỪNG 1): bộ phân tích JSON có vị trí — CHỈ định vị. Hợp lệ hay không do JSON.parse quyết.
import { describe, expect, it } from "vitest";
import { checkPolicyText, duplicateText, type Located, locate, locLine, syntaxText } from "./policyText.ts";

const lines = (...rows: string[]) => rows.join("\n");

// Văn bản mẫu: "type" xuất hiện ở 3 cấp khác nhau (gốc, trong rules[0], trong rules[1]) — locLine phải đi đúng đường.
const SAMPLE = lines(
  "{", //                                   1
  '  "type": "goc",', //                    2
  '  "constants": {', //                    3
  '    "SLA_MINUTES": 30,', //              4
  '    "THRESHOLD_LOW": 0.85,', //          5
  '    "THRESHOLD_HIGH": 0.75', //          6
  "  },", //                                7
  '  "rules": [', //                        8
  "    {", //                               9
  '      "id": "R17",', //                  10
  '      "type": "approval_required"', //   11
  "    },", //                              12
  '    {"id": "R18", "type": "aproval_required",', // 13
  '     "nested": {"type": "x", "list": [1, {"type": "y"}]}}', // 14
  "  ]", //                                 15
  "}", //                                   16
);

describe("t59: locLine — loc (đường dẫn Pydantic, tính từ gốc nội dung) → số dòng", () => {
  it("khoá lồng: constants.THRESHOLD_LOW → dòng 5; constants → dòng 3", () => {
    expect(locLine(SAMPLE, ["constants", "THRESHOLD_LOW"])).toBe(5);
    expect(locLine(SAMPLE, ["constants", "THRESHOLD_HIGH"])).toBe(6);
    expect(locLine(SAMPLE, ["constants"])).toBe(3);
  });

  it("phần tử mảng: rules[0] → dòng bắt đầu phần tử (9); rules[1] → 13; rules[1].type → 13; số dạng chuỗi cũng nhận", () => {
    expect(locLine(SAMPLE, ["rules", 0])).toBe(9);
    expect(locLine(SAMPLE, ["rules", 1])).toBe(13);
    expect(locLine(SAMPLE, ["rules", 1, "type"])).toBe(13);
    expect(locLine(SAMPLE, ["rules", "0", "id"])).toBe(10);
  });

  it("khoá trùng TÊN ở cấp khác: type gốc (2) ≠ rules[0].type (11) ≠ rules[1].nested.type (14) ≠ …list[1].type (14)", () => {
    expect(locLine(SAMPLE, ["type"])).toBe(2);
    expect(locLine(SAMPLE, ["rules", 0, "type"])).toBe(11);
    expect(locLine(SAMPLE, ["rules", 1, "nested", "type"])).toBe(14);
    expect(locLine(SAMPLE, ["rules", 1, "nested", "list", 1, "type"])).toBe(14);
  });

  it("không tìm thấy / loc rỗng / sai kiểu bước / văn bản lỗi cú pháp → null (giao diện ghi 'Toàn tệp')", () => {
    expect(locLine(SAMPLE, [])).toBeNull();
    expect(locLine(SAMPLE, ["khong_co"])).toBeNull();
    expect(locLine(SAMPLE, ["rules", 5])).toBeNull();
    expect(locLine(SAMPLE, ["rules", -1])).toBeNull();
    expect(locLine(SAMPLE, ["constants", 0])).toBeNull();
    expect(locLine(SAMPLE, ["rules", "id"])).toBeNull();
    expect(locLine(SAMPLE, ["constants", "SLA_MINUTES", "x"])).toBeNull();
    expect(locLine('{"a": 1,}', ["a"])).toBeNull();
  });

  it("khoá có ký tự thoát được so sau khi giải mã; khoá trùng → lần cuối (giá trị server dùng)", () => {
    const text = lines("{", '  "a\\"b": 1,', '  "x": 1,', '  "\\u0078": 2', "}");
    expect(locLine(text, ['a"b'])).toBe(2);
    expect(locLine(text, ["x"])).toBe(4);
  });
});

describe("t59: vị trí lỗi cú pháp (dòng, cột) + JSON.parse là nguồn quyết hợp lệ", () => {
  const at = (text: string) => {
    const r = checkPolicyText(text);
    return r.valid ? null : { line: r.line, column: r.column, message: r.message };
  };

  it("thiếu dấu phẩy giữa hai khoá → chỉ đúng chỗ khoá thứ hai", () => {
    expect(at(lines("{", '  "a": 1', '  "b": 2', "}"))).toMatchObject({ line: 3, column: 3, message: expect.stringMatching(/Thiếu dấu phẩy hoặc \}/) });
  });

  it("chuỗi chưa đóng (xuống dòng giữa chuỗi) → dòng/cột mở chuỗi", () => {
    expect(at(lines("{", '  "a": "abc', "}"))).toMatchObject({ line: 2, column: 8, message: expect.stringMatching(/Chuỗi chưa đóng/) });
  });

  it("dấu phẩy thừa trước } và trước ]", () => {
    expect(at(lines("{", '  "a": 1,', "}"))).toMatchObject({ line: 3, column: 1, message: "Dấu phẩy thừa trước }" });
    expect(at(lines("[", "  1,", "  2,", "]"))).toMatchObject({ line: 4, column: 1, message: "Dấu phẩy thừa trước ]" });
  });

  it("hết tệp giữa chừng → vị trí cuối tệp", () => {
    expect(at(lines("{", '  "a": [1, 2'))).toMatchObject({ line: 2, column: 13, message: expect.stringMatching(/thiếu \]/) });
    expect(at("")).toMatchObject({ line: 1, column: 1, message: "Nội dung trống" });
  });

  it("syntaxText: 'Dòng N, cột M · …' hoặc 'Toàn tệp · …'", () => {
    const r = checkPolicyText(lines("{", '  "a": 1', '  "b": 2', "}"));
    expect(r.valid).toBe(false);
    if (!r.valid) expect(syntaxText(r)).toMatch(/^Dòng 3, cột 3 · /);
    expect(syntaxText({ valid: false, line: null, column: null, message: "X" })).toBe("Toàn tệp · X");
  });

  // Bộ mẫu: bộ tự viết phải chấp nhận ĐÚNG những gì JSON.parse chấp nhận (kể cả ca biên RFC 8259).
  const CORPUS = [
    "{}", "[]", "0", "-0", "1e5", "1E-5", "-12.5e+3", '"\\u00e9"', '"\\ud83d\\ude00"', '" "', " \t\r\n{} ", "null", "true",
    '{"a":{"b":[1,{"c":null}]}}', "01", "1.", ".5", "-", "+1", "1e", '"\\u12"', '"\\x"', '"a\tb"', "[1,]", '{"a":1,}', '{"a" 1}',
    '{a:1}', "nul", "truex", "[1 2]", '["a" "b"]', "{}{}", "", "   ", "'a'", "NaN", "Infinity", '{"a":1}x', "[", "{", '"', "﻿{}",
  ];
  it.each(CORPUS.map((t) => [JSON.stringify(t), t]))("%s: locate.ok === JSON.parse thành công", (_label, text) => {
    let parsed = true;
    try {
      JSON.parse(text);
    } catch {
      parsed = false;
    }
    expect(locate(text).ok).toBe(parsed);
    expect(checkPolicyText(text).valid).toBe(parsed);
  });

  it("JSON.parse OK mà bộ tự viết báo lỗi → VẪN hợp lệ (không khoá Lưu), chỉ không có cây để đánh dấu dòng", () => {
    const broken = (): Located => ({ ok: false, line: 1, column: 1, message: "bộ định vị hỏng" });
    const r = checkPolicyText('{"a": 1}', broken);
    expect(r).toStrictEqual({ valid: true, value: { a: 1 }, root: null, duplicates: [] });
  });

  it("JSON.parse lỗi mà bộ tự viết không ra vị trí → 'Toàn tệp'", () => {
    const blind = (): Located => ({ ok: false, line: null, column: null, message: "Không định vị được lỗi" });
    const r = checkPolicyText("{", blind);
    expect(r.valid).toBe(false);
    if (!r.valid) expect(syntaxText(r)).toBe("Toàn tệp · Không định vị được lỗi");
  });
});

describe("t59: khoá trùng trong CÙNG object → cảnh báo vàng (không chặn Lưu); giá trị sau cùng được dùng", () => {
  const TEXT = lines(
    "{", //                              1
    '  "constants": {', //               2
    '    "SLA_MINUTES": 30,', //         3
    '    "THRESHOLD_LOW": 0.25,', //     4
    '    "SLA_MINUTES": 45', //          5
    "  },", //                           6
    '  "rules": [{"id": "R1"}, {"id": "R2"}]', // 7 — "id" ở hai object khác nhau: KHÔNG phải trùng
    "}", //                              8
  );

  it("phát hiện đúng khoá + các dòng; hợp lệ; JSON.parse lấy giá trị sau cùng", () => {
    const r = checkPolicyText(TEXT);
    expect(r.valid).toBe(true);
    if (!r.valid) return;
    expect(r.duplicates).toStrictEqual([{ key: "SLA_MINUTES", lines: [3, 5] }]);
    expect((r.value as { constants: { SLA_MINUTES: number } }).constants.SLA_MINUTES).toBe(45);
    expect(duplicateText(r.duplicates[0]!)).toBe('Khoá "SLA_MINUTES" lặp ở dòng 3 và 5 — hệ thống dùng giá trị sau cùng (dòng 5)');
    expect(locLine(TEXT, ["constants", "SLA_MINUTES"])).toBe(5);
  });

  it("ba lần lặp → liệt kê đủ dòng", () => {
    const r = checkPolicyText(lines("{", '"a": 1,', '"a": 2,', '"a": 3', "}"));
    if (!r.valid) throw new Error("phải hợp lệ");
    expect(duplicateText(r.duplicates[0]!)).toBe('Khoá "a" lặp ở dòng 2, 3 và 4 — hệ thống dùng giá trị sau cùng (dòng 4)');
  });
});
