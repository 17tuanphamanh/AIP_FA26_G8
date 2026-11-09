// Điện thoại: mọi lớp `max-lg:` / `lg:` trong src phải BIÊN DỊCH được. Tailwind im lặng bỏ lớp gõ sai (`max-lg:min-h-111`,
// `max-lg:wrap-anywere`) — màn vẫn dựng, chỉ thiếu kiểu, và không test DOM nào thấy. Test này nạp ĐÚNG tokens.css (cùng khối
// @theme như bản build) vào trình biên dịch Tailwind rồi đòi: (1) lớp ra CSS; (2) lớp `max-lg:` nằm trong
// `@media (width < 64rem)` — dưới 1024 px mới chạy, từ 1024 px trở lên không có luật nào mới; (3) tokens.css khai đúng
// điểm 64rem cho cỡ chữ điện thoại; (4) vùng an toàn: lớp có `env(safe-area-inset-*)` biên dịch được, tên env đúng, và
// index.html bật `viewport-fit=cover` (không bật thì env() = 0, đệm vô nghĩa; bật mà không đệm thì nội dung chui dưới tai thỏ).
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { compile } from "tailwindcss";
import { describe, expect, it } from "vitest";

const BREAKPOINT = "@media (width < 64rem)";
// vitest biến mọi file .css thành chuỗi rỗng (kể cả `?raw`) → đọc thẳng bằng fs; cwd = frontend/ (`npm test`).
const tokens = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");
// Nguồn không phải test — cùng cách quét với src/mocks/handlers/manager.test.ts.
const sources = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}"], {
  query: "?raw",
  import: "default",
  eager: true,
});

/** Mọi token `max-lg:…` / `lg:…` trong mã nguồn. */
function usedClasses(): { max: string[]; lg: string[] } {
  const found = new Set<string>();
  for (const text of Object.values(sources)) {
    for (const match of text.matchAll(/(?<![\w:-])((?:max-lg|lg):[^\s"'`{}<>]+)/g)) found.add(match[1]!);
  }
  const all = [...found].sort();
  return { max: all.filter((c) => c.startsWith("max-lg:")), lg: all.filter((c) => c.startsWith("lg:")) };
}

/** Mọi token có `env(safe-area-inset-…)` trong mã nguồn (kể cả không có tiền tố `max-lg:`). */
function safeAreaClasses(): string[] {
  const found = new Set<string>();
  for (const text of Object.values(sources)) {
    for (const match of text.matchAll(/[^\s"'`{}<>]*env\(safe-area-inset[^\s"'`{}<>]*/g)) found.add(match[0]);
  }
  return [...found].sort();
}

/** Biên dịch ĐÚNG tokens.css (cùng khối @theme như bản build). `@import "tailwindcss"` đọc từ node_modules (cwd = frontend/). */
async function compiler() {
  const root = process.cwd();
  return compile(tokens, {
    base: resolve(root, "src/styles"),
    loadStylesheet: async (id, base) => {
      const path = id === "tailwindcss" ? resolve(root, "node_modules/tailwindcss/index.css") : resolve(base, id);
      return { path, base: dirname(path), content: readFileSync(path, "utf8") };
    },
  });
}

const selector = (cls: string) => `.${cls.replace(/[^a-zA-Z0-9_-]/g, (c) => `\\${c}`)}`;

describe("lớp max-lg: / lg: biên dịch được", () => {
  const { max, lg } = usedClasses();

  it("có lớp để kiểm (không quét rỗng)", () => {
    expect(max.length).toBeGreaterThan(20);
    expect(lg.length).toBeGreaterThan(0);
  });

  it("mọi lớp max-lg: ra CSS và nằm trọn trong @media (width < 64rem)", async () => {
    const tw = await compiler();
    const bad = max.filter((cls) => {
      const css = tw.build([cls]);
      const at = css.indexOf(BREAKPOINT);
      return at < 0 || !css.slice(at).includes(selector(cls)) || css.slice(0, at).includes(selector(cls));
    });
    expect(bad, `lớp không biên dịch (gõ sai?) hoặc nằm ngoài ${BREAKPOINT}`).toEqual([]);
  });

  it("mọi lớp lg: ra CSS", async () => {
    const tw = await compiler();
    const bad = lg.filter((cls) => !tw.build([cls]).includes(selector(cls)));
    expect(bad, "lớp lg: không biên dịch").toEqual([]);
  });

  it("tokens.css: cỡ chữ điện thoại chỉ nằm trong @media (width < 64rem), tối thiểu 14 px cho nhãn", () => {
    const css = tokens;
    const block = /@media \(width < 64rem\) \{\s*:root \{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(block).toMatch(/--text-label:\s*14px/);
    expect(block).toMatch(/--text-title:\s*28px/);
    // Khối @theme (khổ lớn) giữ nguyên giá trị gốc.
    expect(css).toMatch(/--text-label:\s*13px/);
    expect(css).toMatch(/--text-title:\s*34px/);
  });

  it("tokens.css: đệm trái/phải của body nằm trong @media (width < 64rem) — xoay ngang không chui dưới tai thỏ", () => {
    const block = /@media \(width < 64rem\) \{[\s\S]*?\n\}/.exec(tokens)?.[0] ?? "";
    expect(block).toMatch(/body \{[^}]*padding-right:\s*env\(safe-area-inset-right\)/);
    expect(block).toMatch(/body \{[^}]*padding-left:\s*env\(safe-area-inset-left\)/);
  });
});

describe("vùng an toàn (viewport-fit=cover)", () => {
  const classes = safeAreaClasses();
  const html = readFileSync(resolve(process.cwd(), "index.html"), "utf8");

  it("có lớp để kiểm: thanh đầu, ô chat, thanh quyết định", () => {
    expect(classes.some((c) => c.includes("safe-area-inset-top"))).toBe(true);
    expect(classes.some((c) => c.includes("safe-area-inset-bottom"))).toBe(true);
  });

  it("mọi lớp có env(safe-area-inset-…) biên dịch được và dùng đúng tên top|right|bottom|left", async () => {
    const names = classes.flatMap((c) => [...c.matchAll(/env\(safe-area-inset-([a-z]+)\)/g)].map((m) => m[1]));
    expect(names.filter((n) => !["top", "right", "bottom", "left"].includes(n!)), "tên env() sai — CSS vẫn hợp lệ nhưng đệm = 0").toEqual([]);
    const tw = await compiler();
    const bad = classes.filter((cls) => !tw.build([cls]).includes(selector(cls)));
    expect(bad, "lớp không biên dịch").toEqual([]);
  });

  it("index.html bật viewport-fit=cover (có đệm vùng an toàn thì phải bật; không thì env() luôn 0)", () => {
    expect(html).toMatch(/<meta name="viewport" content="[^"]*viewport-fit=cover/);
  });

  it("còn viewport-fit=cover thì còn đệm: thanh đầu đệm trên, ô chat + thanh quyết định đệm dưới", () => {
    const text = Object.values(sources).join("\n");
    expect(text).toMatch(/pt-\[env\(safe-area-inset-top\)\]/);
    expect(text).toMatch(/max-lg:pb-\[calc\(0\.75rem\+env\(safe-area-inset-bottom\)\)\]/);
  });
});
