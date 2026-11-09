// `npm run check:style`: tự động hoá các grep của KH mục 7 ("Mọi chặng") và mục 8 (#1, #2, #8).
// 1. Không mã màu / cỡ chữ ngoài token 4.5 trong src/routes, src/components: mã hex, rgb()/hsl()/oklch(),
//    giá trị tuỳ ý của Tailwind cho màu/cỡ (`text-[…]`, `bg-[…]`…). Token chỉ khai ở src/styles/tokens.css.
// 2. Không Local/SessionStorage, không dangerouslySetInnerHTML trong src (KH 4.1 #1, #5).
// 3. Không Google Fonts / CDN trong src, index.html (KH 4.1 #7).
// 4. Không plugin / API dựng HTML thô trong package.json, src (KH 4.1 #5). react-markdown 10 tự hiện HTML thô thành
//    CHỮ — lớp bảo vệ đó mất ngay khi thêm plugin parse HTML (rehype-raw…), bật `allowDangerousHtml`, dùng thư viện
//    biến chuỗi HTML thành phần tử React, hoặc ghi thẳng vào DOM (innerHTML…). Luật này giữ nó bằng máy.
// Có kết quả → in `tệp:dòng`, thoát 1.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const CODE_EXT = new Set([".ts", ".tsx", ".js", ".jsx", ".css", ".html"]);

const RULES = [
  {
    name: "màu/cỡ chữ ngoài token 4.5",
    paths: ["src/routes", "src/components"],
    pattern:
      /#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{3,4})\b|\b(?:rgba?|hsla?|oklch|oklab)\(|\b(?:text|bg|border|fill|stroke|ring|outline|decoration|caret|accent|from|via|to|shadow)-\[/i,
  },
  {
    name: "lưu trữ trình duyệt",
    paths: ["src"],
    // Test được nhắc tới Storage để gài spy chứng minh code KHÔNG dùng (t5) — chỉ miễn cho *.test.*.
    // NGOẠI LỆ DUY NHẤT (ĐP 26/10 N-TB P3): src/lib/lastSeen.ts — mốc ISO "đã xem thông báo", không token (lý do ở đầu
    // file đó; eslint.config.js miễn đúng file này). Không thêm file nào khác.
    skip: /\.test\.[jt]sx?$|[\\/]src[\\/]lib[\\/]lastSeen\.ts$/,
    pattern: /localStorage|sessionStorage/,
  },
  {
    name: "HTML thô",
    paths: ["src"],
    skip: /\.test\.[jt]sx?$/,
    pattern: /dangerouslySetInnerHTML/,
  },
  {
    name: "Google Fonts / CDN",
    paths: ["src", "index.html"],
    pattern: /fonts\.googleapis|fonts\.gstatic|cdn\./i,
  },
  {
    name: "plugin/API dựng HTML thô",
    paths: ["package.json", "src"],
    exts: new Set([...CODE_EXT, ".json"]),
    pattern:
      /rehype-raw|rehype-dom-raw|allowDangerousHtml|remark-html|html-react-parser|react-html-parser|\binnerHTML\b|\bouterHTML\b|insertAdjacentHTML|document\.write\b/,
  },
];

function walk(path) {
  if (!existsSync(path)) return [];
  if (statSync(path).isFile()) return [path];
  return readdirSync(path, { withFileTypes: true }).flatMap((entry) => walk(join(path, entry.name)));
}

const hits = [];
for (const rule of RULES) {
  for (const file of rule.paths.flatMap((p) => walk(join(ROOT, p)))) {
    if (!(rule.exts ?? CODE_EXT).has(extname(file)) || rule.skip?.test(file)) continue;
    readFileSync(file, "utf8")
      .split("\n")
      .forEach((line, i) => {
        if (rule.pattern.test(line)) hits.push(`${relative(ROOT, file)}:${i + 1}  [${rule.name}]  ${line.trim()}`);
      });
  }
}

if (hits.length > 0) {
  console.error(`check:style: ĐỎ — ${hits.length} dòng vi phạm:`);
  for (const hit of hits) console.error(`  ${hit}`);
  process.exit(1);
}
console.log("check:style: sạch (không mã màu ngoài token, không Storage/HTML thô, không CDN, không plugin HTML thô).");
