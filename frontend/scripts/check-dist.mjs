// `npm run check:dist` (KH 4.3 #3, fail-closed): quét `dist/` sau `vite build`.
// 1. Dữ liệu giả không được lọt vào bản build: tên MỌI tệp không chứa `mockServiceWorker`/`msw`; nội dung tệp
//    văn bản không khớp /mockServiceWorker|\bmsw/i. Bỏ qua nội dung tệp nhị phân (font): grep thô 3 byte "msw"
//    trên woff2 có thể khớp ngẫu nhiên → báo đỏ nhầm (12b, tự quyết 4).
// 2. Fixture giả không lọt (Q-fe-29, lớp 2 — lớp 1 là plugin `no-mocks-in-build` ở vite.config.ts): nội dung tệp văn
//    bản không có mã fixture `apv-demo-` (phiếu duyệt F4), `tkt-demo-` (ticket F4, ca E3 + cảnh báo F5, hàng đợi L2 N-PA
//    `tkt-demo-esc-`), `npa-demo` (cách xử lý / so sánh phương án N-PA).
// 3. Không tải gì ngoài origin (KH 4.1 #7, CSP `default-src 'self'`): HTML/CSS không có src/href/url()/@import
//    trỏ tới `http(s)://` hay `//`.
// 4. Logo FPT (gói fe-logo-fpt): `src/assets/fpt-university-logo.png` phải ra `dist/assets/` thành tệp riêng, trùng
//    từng byte với nguồn (không nén lại / không inline — `assetsInlineLimit: 0`); không tệp văn bản nào chứa `data:image/`.
// Có vi phạm → in từng tệp, thoát 1.
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const DIST = fileURLToPath(new URL("../dist/", import.meta.url));
const TEXT_EXT = new Set([".html", ".css", ".js", ".mjs", ".json", ".map", ".txt", ".svg", ".webmanifest", ".xml"]);
const MOCK_NAME = /mockServiceWorker|msw/i;
const MOCK_CONTENT = /mockServiceWorker|\bmsw/i;
const FIXTURE_CONTENT = /apv-demo-|tkt-demo-|npa-demo/;
const EXTERNAL =
  /\b(?:src|href)\s*=\s*["']?\s*(?:https?:)?\/\/|url\(\s*["']?\s*(?:https?:)?\/\/|@import\s+(?:url\()?\s*["']?\s*(?:https?:)?\/\//i;

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? walk(path) : [path];
  });
}

if (!existsSync(DIST)) {
  console.error("check:dist: không thấy dist/ — chạy `vite build` trước.");
  process.exit(1);
}

const files = walk(DIST);
const problems = [];
for (const file of files) {
  const name = relative(DIST, file);
  if (MOCK_NAME.test(name)) problems.push(`${name}: tên tệp của MSW`);
  const ext = extname(file).toLowerCase();
  if (!TEXT_EXT.has(ext)) continue;
  const text = readFileSync(file, "utf8");
  const mock = text.match(MOCK_CONTENT);
  if (mock) problems.push(`${name}: chứa "${mock[0]}"`);
  const fixture = text.match(FIXTURE_CONTENT);
  if (fixture) problems.push(`${name}: chứa mã fixture "${fixture[0]}"`);
  if (ext === ".html" || ext === ".css") {
    const external = text.match(EXTERNAL);
    if (external) problems.push(`${name}: tải ngoài origin "${external[0]}"`);
  }
}

const sha256 = (path) => createHash("sha256").update(readFileSync(path)).digest("hex");
const FPT_LOGO_SRC = fileURLToPath(new URL("../src/assets/fpt-university-logo.png", import.meta.url));
const fptLogos = files.filter((file) => /^assets[\\/]fpt-university-logo-[\w-]+\.png$/.test(relative(DIST, file)));
if (fptLogos.length !== 1) problems.push(`logo FPT: cần đúng 1 tệp dist/assets/fpt-university-logo-*.png, thấy ${fptLogos.length}`);
else if (sha256(fptLogos[0]) !== sha256(FPT_LOGO_SRC)) problems.push(`${relative(DIST, fptLogos[0])}: khác byte với src/assets/fpt-university-logo.png`);
for (const file of files) {
  if (TEXT_EXT.has(extname(file).toLowerCase()) && readFileSync(file, "utf8").includes("data:image/")) {
    problems.push(`${relative(DIST, file)}: chứa ảnh nhúng "data:image/"`);
  }
}

if (problems.length > 0) {
  console.error(`check:dist: ĐỎ — ${problems.length} vi phạm trong dist/:`);
  for (const problem of problems) console.error(`  - ${problem}`);
  process.exit(1);
}
console.log(`check:dist: sạch (${files.length} tệp trong dist/, không có msw/mockServiceWorker, không mã fixture, không tải ngoài origin, logo FPT ở dist/assets trùng byte nguồn, không data:image/).`);
