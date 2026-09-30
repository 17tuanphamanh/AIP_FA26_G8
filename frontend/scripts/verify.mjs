// `npm run verify` (Q-fe-12, KH 12b): agent tự kiểm, người chỉ gõ một lệnh.
// Chạy tuần tự, dừng ở bước đỏ đầu tiên (riêng dọn dẹp LUÔN chạy):
//   a) lint → typecheck → vitest → build → check:dist → check:style (gọi đúng script trong package.json)
//   b) Playwright, Chromium headless, mỗi kịch bản một browser context MỚI (không còn service worker cũ):
//      F0-1 dev không mock · F0-2 dev:mock · F0-3 preview (0 request ngoài origin, font từ /assets/)
//      F1-1…6 đăng nhập thật qua dev server → backend — chỉ BỎ QUA khi GET http://127.0.0.1:8000/api/health ≠ 200
//   c) dọn dẹp: tắt mọi server đã mở, đóng trình duyệt — kể cả khi lỗi hay Ctrl+C.
// Đầu ra: .verify/summary.txt (bảng), .verify/run-<giờ>.log (chi tiết), .verify/<giờ>-<bước>.png khi FAIL,
//         .verify/login.png, login-otp.png, sidebar-<user>.png (1440×900, để so Bản 4).
// Mật khẩu demo đọc LÚC CHẠY từ mock_services/README.md mục "Dữ liệu demo" — không ghi cứng, không in;
// mọi dòng ghi log/summary đi qua redact(). Không đọc .env.
/* global document, indexedDB -- chỉ dùng bên trong page.evaluate (chạy ở trình duyệt); localStorage, sessionStorage
   đã là biến toàn cục của Node ≥ 22 nhưng ở đây cũng chỉ đọc bên trong page.evaluate */
import { spawn, spawnSync } from "node:child_process";
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const FE = fileURLToPath(new URL("../", import.meta.url));
const REPO = join(FE, "..");
const OUT = join(FE, ".verify");
const VITE = join(FE, "node_modules", "vite", "bin", "vite.js");

// Chặng đã dựng xong (ghi vào summary). Kịch bản của chặng chưa dựng thì chưa có ở đây.
const BUILT = "F1";

const DEV = "http://localhost:5173";
const PREVIEW = "http://localhost:4173";
const HEALTH = "http://127.0.0.1:8000/api/health";
const MOCK_LABEL = "Dữ liệu minh hoạ";
const NAV = { name: "Điều hướng chính" };
const LOGIN_HEADING = { name: "Đăng nhập", level: 1 };
const OTP_HEADING = { name: "Nhập mã xác thực", level: 1 };
const VIEWPORT = { width: 1440, height: 900 }; // khung Bản 4

// Tài khoản demo (KH 1.1) → điều thanh bên PHẢI có / KHÔNG được có theo permissions (P6 §5.1, 12b Q-fe-8).
const ACCOUNTS = {
  "an.nv": { home: "/chat", has: ["Yêu cầu mới"], lacks: ["Tổng quan", "Chính sách", "Chờ tôi duyệt", "Hàng đợi escalate"] },
  "ha.lt": { home: "/approvals", has: ["Chờ tôi duyệt", "Hàng đợi escalate"], lacks: ["Chính sách", "Tổng quan", "Cảnh báo"] },
  "long.nh": { home: "/escalations", has: ["Hàng đợi escalate"], lacks: ["Chờ tôi duyệt", "Chính sách", "Tổng quan"] },
};

const pad = (n) => String(n).padStart(2, "0");
const started = new Date();
const STAMP =
  `${started.getFullYear()}${pad(started.getMonth() + 1)}${pad(started.getDate())}` +
  `-${pad(started.getHours())}${pad(started.getMinutes())}${pad(started.getSeconds())}`;
mkdirSync(OUT, { recursive: true });
const LOG = join(OUT, `run-${STAMP}.log`);

// ---------------------------------------------------------------- log, che bí mật

const secrets = [];
const redact = (text) => secrets.reduce((t, s) => t.split(s).join("***"), String(text));
const log = (text) => appendFileSync(LOG, `${redact(text)}\n`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const lastLines = (text, n = 3) =>
  String(text).trim().split("\n").filter((l) => l.trim()).slice(-n).join(" / ");

// Mật khẩu demo — MỘT nguồn: mock_services/README.md, mục "## Dữ liệu demo", dòng "Mật khẩu demo …: `…`".
function readDemoPassword() {
  const readme = readFileSync(join(REPO, "mock_services", "README.md"), "utf8");
  const section = readme.split(/^## /m).find((part) => part.startsWith("Dữ liệu demo"));
  const value = section?.split("\n").find((l) => l.includes("Mật khẩu demo"))?.match(/`([^`]+)`/)?.[1];
  if (!value) throw new Error('không đọc được mật khẩu demo từ mock_services/README.md mục "Dữ liệu demo"');
  secrets.push(value);
  return value;
}

// ---------------------------------------------------------------- chạy script npm (bước a)

const npm = process.env.npm_execpath
  ? { cmd: process.execPath, pre: [process.env.npm_execpath], shell: false }
  : { cmd: process.platform === "win32" ? "npm.cmd" : "npm", pre: [], shell: process.platform === "win32" };
const QUIET = { FORCE_COLOR: "0", NO_COLOR: "1", npm_config_update_notifier: "false" };

function runScript(script, extra = []) {
  const args = [...npm.pre, "run", "--silent", script, ...(extra.length ? ["--", ...extra] : [])];
  log(`$ npm ${args.slice(npm.pre.length).join(" ")}`);
  return new Promise((resolve) => {
    const child = spawn(npm.cmd, args, { cwd: FE, env: { ...process.env, ...QUIET }, shell: npm.shell });
    let output = "";
    child.stdout.on("data", (d) => (output += d));
    child.stderr.on("data", (d) => (output += d));
    child.on("error", (e) => resolve({ code: -1, output: String(e) }));
    child.on("close", (code) => {
      log(output.trimEnd());
      resolve({ code, output });
    });
  });
}

// ---------------------------------------------------------------- server (bước b) + dọn dẹp (bước c)

const servers = new Set();
const exited = (child) => child.exitCode !== null || child.signalCode !== null;

async function responds(url) {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(1000) });
    return res.status > 0;
  } catch {
    return false;
  }
}

async function startServer(name, args, env, url) {
  // Cổng đang có server khác (vd dev server của người dùng) → báo rõ, không đo nhầm server đó.
  if (await responds(url)) throw new Error(`${url} đang có tiến trình khác — tắt nó rồi chạy lại verify`);
  const child = spawn(process.execPath, args, {
    cwd: FE,
    env: { ...process.env, ...QUIET, BROWSER: "none", ...env },
    detached: process.platform !== "win32", // nhóm tiến trình riêng → tắt được cả cây
    stdio: ["ignore", "pipe", "pipe"],
  });
  servers.add(child);
  let output = "";
  const onData = (d) => {
    output += d;
    for (const line of String(d).split("\n")) if (line.trim()) log(`[${name}] ${line}`);
  };
  child.stdout.on("data", onData);
  child.stderr.on("data", onData);
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (exited(child)) throw new Error(`${name} thoát sớm (mã ${child.exitCode}): ${lastLines(output)}`);
    if (await responds(url)) return child;
    await sleep(250);
  }
  throw new Error(`${name} không lên sau 30 s: ${lastLines(output)}`);
}

function signalTree(child, signal) {
  try {
    if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"]);
    else process.kill(-child.pid, signal);
  } catch {
    // đã chết
  }
}

async function stopServer(child) {
  if (!exited(child)) {
    const done = new Promise((r) => child.once("exit", () => r(true)));
    signalTree(child, "SIGTERM");
    if (!(await Promise.race([done, sleep(5000).then(() => exited(child))]))) {
      signalTree(child, "SIGKILL");
      await Promise.race([done, sleep(3000)]);
    }
  }
  if (exited(child)) servers.delete(child);
  return exited(child);
}

// Ctrl+C / thoát bất thường: giết cả cây server ngay (đồng bộ), không để tiến trình treo.
for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    for (const child of servers) signalTree(child, "SIGKILL");
    process.exit(130);
  });
}
process.on("exit", () => {
  for (const child of servers) signalTree(child, "SIGKILL");
});

// ---------------------------------------------------------------- bước + kết quả

const results = [];
let failedStep = null;

async function step(name, fn) {
  if (failedStep) {
    results.push({ name, status: "BỎ QUA", ms: 0, note: `không chạy — dừng sau bước đỏ "${failedStep}"` });
    return;
  }
  log(`\n=== ${name}`);
  const t0 = performance.now();
  try {
    const r = (await fn()) ?? {};
    results.push({ name, status: r.status ?? "PASS", ms: performance.now() - t0, note: r.note ?? "" });
    log(`--- ${r.status ?? "PASS"} ${r.note ?? ""}`);
  } catch (error) {
    failedStep = name;
    results.push({ name, status: "FAIL", ms: performance.now() - t0, note: String(error?.message ?? error).split("\n")[0] });
    log(`--- FAIL\n${error?.stack ?? error}`);
  }
}

function check(condition, message) {
  if (!condition) throw new Error(message);
}

const scriptStep = (script, extra, note) => async () => {
  const { code, output } = await runScript(script, extra);
  if (code !== 0) throw new Error(`exit ${code}: ${lastLines(output)}`);
  return { note: note ? note(output) : "exit 0" };
};

// ---------------------------------------------------------------- kịch bản trình duyệt

let browser = null;

function watch(page, id, consoleLines) {
  page.on("console", (m) => {
    const line = `[${m.type()}] ${m.text()}`;
    consoleLines.push(line);
    log(`[${id} console] ${line}`);
  });
  // Console chỉ ghi "Failed to load resource: 403" không kèm URL → ghi thêm phương thức + đường dẫn (không query, không thân).
  page.on("response", (r) => {
    if (r.status() >= 400) log(`[${id} http] ${r.request().method()} ${new URL(r.url()).pathname} → ${r.status()}`);
  });
  page.on("pageerror", (e) => {
    consoleLines.push(`[pageerror] ${e.message}`);
    log(`[${id} pageerror] ${e.message}`);
  });
}

async function scenario(id, fn) {
  const context = await browser.newContext({ viewport: VIEWPORT });
  const page = await context.newPage();
  const consoleLines = [];
  watch(page, id, consoleLines);
  // Tab thêm trong CÙNG context (dùng chung cookie) — cho kịch bản nhiều tab.
  const newTab = async () => {
    const tab = await context.newPage();
    watch(tab, `${id}/tab${context.pages().length}`, consoleLines);
    return tab;
  };
  try {
    const result = await fn({ page, consoleLines, newTab });
    const errors = consoleLines.filter((l) => l.startsWith("[pageerror]"));
    check(errors.length === 0, `lỗi JS trên trang: ${errors[0]}`);
    return result;
  } catch (error) {
    const shot = join(OUT, `${STAMP}-${id}.png`);
    await page.screenshot({ path: shot, fullPage: true }).catch(() => {});
    log(`ảnh chụp: ${shot}`);
    throw error;
  } finally {
    await context.close();
  }
}

const swCount = (page) => page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length);
const mswLines = (lines) => lines.filter((l) => l.includes("[MSW]"));
const shoot = (page, name) => page.screenshot({ path: join(OUT, name) });

// ---------------------------------------------------------------- đăng nhập (F1)

let password = null; // đọc lúc chạy, chỉ khi backend sống; đã nằm trong `secrets` → mọi log bị che

const isLoginCall = (r) => r.request().method() === "POST" && new URL(r.url()).pathname === "/api/auth/login";

/** Điền form, bấm "Đăng nhập", chờ backend trả lời `POST /api/auth/login`. Trả mã HTTP (không đọc thân). */
async function submitLogin(page, username, { screenshot } = {}) {
  await page.goto(`${DEV}/login`, { waitUntil: "load" });
  await page.getByRole("heading", LOGIN_HEADING).waitFor();
  if (screenshot) await shoot(page, screenshot);
  await page.getByLabel("Tên đăng nhập", { exact: true }).fill(username);
  await page.getByLabel("Mật khẩu", { exact: true }).fill(password);
  const [response] = await Promise.all([
    page.waitForResponse(isLoginCall, { timeout: 15_000 }),
    page.getByRole("button", { name: "Đăng nhập", exact: true }).click(),
  ]);
  log(`POST /api/auth/login (${username}) → ${response.status()}`);
  return response.status();
}

/**
 * Kết quả SAU KHI bấm đăng nhập: thanh bên, màn OTP, hoặc thông báo lỗi. Tiêu đề "Đăng nhập" KHÔNG phải trạng thái
 * cuối ở đây — nó vẫn hiện trong lúc chờ backend và chờ `/me`.
 */
async function afterSubmit(page, timeout = 15_000) {
  const nav = page.getByRole("navigation", NAV);
  const otp = page.getByRole("heading", OTP_HEADING);
  const alert = page.getByRole("alert");
  const settled = await nav.or(otp).or(alert).first().waitFor({ timeout }).then(
    () => true,
    () => false,
  );
  if (!settled) return `chưa có kết quả sau ${timeout / 1000} s`;
  if (await nav.isVisible()) return "signedIn";
  if (await otp.isVisible()) return "otp";
  return `lỗi: "${(await alert.textContent())?.trim()}"`;
}

async function signInAs(page, username, options) {
  const status = await submitLogin(page, username, options);
  const state = await afterSubmit(page);
  check(state === "signedIn", `${username}: không vào được (${state}; POST /api/auth/login → ${status})`);
}

/**
 * Sau khi TẢI trang (không bấm gì): chờ trạng thái rõ ràng — đã vào (thanh bên), bị đưa về màn đăng nhập, hoặc lỗi.
 * Lúc đang kiểm phiên, cả RequireAuth lẫn LoginPage chỉ hiện "Đang kiểm tra phiên…" (không có tiêu đề "Đăng nhập"),
 * nên tiêu đề đó chỉ xuất hiện khi đã chắc là hết phiên.
 */
async function landing(page, timeout = 15_000) {
  const nav = page.getByRole("navigation", NAV);
  const login = page.getByRole("heading", LOGIN_HEADING);
  const alert = page.getByRole("alert");
  await nav.or(login).or(alert).first().waitFor({ timeout });
  if (await nav.isVisible()) return "signedIn";
  if (await alert.isVisible()) return `lỗi: "${(await alert.textContent())?.trim()}"`;
  return "login";
}

async function expectSignedIn(page, who) {
  const state = await landing(page);
  check(state === "signedIn", `${who}: không vào được (${state})`);
}

async function expectStorageEmpty(page, who) {
  const s = await page.evaluate(async () => ({
    local: localStorage.length,
    session: sessionStorage.length,
    idb: (await indexedDB.databases()).length,
  }));
  check(s.local === 0 && s.session === 0 && s.idb === 0, `${who}: Storage không rỗng ${JSON.stringify(s)}`);
}

async function expectSidebar(page, username) {
  const expected = ACCOUNTS[username];
  const nav = page.getByRole("navigation", NAV);
  const link = (label) => nav.getByRole("link", { name: label, exact: true });
  for (const label of expected.has) check((await link(label).count()) === 1, `${username}: thiếu mục "${label}"`);
  for (const label of expected.lacks) check((await link(label).count()) === 0, `${username}: KHÔNG được có mục "${label}"`);
  const path = new URL(page.url()).pathname;
  check(path === expected.home, `${username}: trang đầu ${path}, cần ${expected.home}`);
}

let f1Server = null;
async function ensureF1Server() {
  f1Server ??= await startServer("dev(F1)", [VITE], { VITE_API_MOCK: "0" }, DEV);
}

async function backendUp() {
  try {
    const res = await fetch(HEALTH, { signal: AbortSignal.timeout(3000) });
    return res.status === 200;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------- chạy

log(`npm run verify — ${started.toISOString()} — chặng đã dựng: ${BUILT}`);

// a) kiểm tĩnh
await step("lint", scriptStep("lint"));
await step("typecheck", scriptStep("typecheck"));
await step(
  "vitest",
  scriptStep("test", ["--passWithNoTests"], (out) =>
    /No test files found/i.test(out) ? "0 test — chưa có (test viết từ F1)" : lastLines(out.match(/Tests?\s+.*/g)?.join("\n") ?? "exit 0", 1),
  ),
);
await step("build", scriptStep("build", [], () => "vite build exit 0"));
await step("check:dist", scriptStep("check:dist", [], (out) => lastLines(out, 1)));
await step("check:style", scriptStep("check:style", [], (out) => lastLines(out, 1)));

// b) trình duyệt
await step("Mở Chromium headless", async () => {
  try {
    browser = await chromium.launch({ headless: true });
  } catch (error) {
    throw new Error(`không mở được Chromium — chạy: npx playwright install chromium (${String(error.message).split("\n")[0]})`, {
      cause: error,
    });
  }
  return { note: `Chromium ${browser.version()}` };
});

await step("F0-1 dev không mock", async () => {
  const server = await startServer("dev", [VITE], { VITE_API_MOCK: "0" }, DEV);
  try {
    return await scenario("F0-1", async ({ page, consoleLines }) => {
      await page.goto(DEV, { waitUntil: "load" });
      await page.getByRole("heading", LOGIN_HEADING).waitFor(); // chưa đăng nhập → /login
      await page.waitForTimeout(1000); // chờ log muộn (nếu MSW lỡ bật)
      check(mswLines(consoleLines).length === 0, `console có "${mswLines(consoleLines)[0]}"`);
      check((await page.getByText(MOCK_LABEL).count()) === 0, `có nhãn "${MOCK_LABEL}"`);
      const sw = await swCount(page);
      check(sw === 0, `có ${sw} service worker`);
      return { note: 'không "[MSW]", không nhãn, 0 service worker' };
    });
  } finally {
    await stopServer(server);
  }
});

await step("F0-2 dev:mock", async () => {
  const server = await startServer("dev:mock", [join(FE, "scripts", "dev-mock.mjs")], {}, DEV);
  try {
    return await scenario("F0-2", async ({ page, consoleLines }) => {
      const enabled = page.waitForEvent("console", {
        predicate: (m) => m.text().includes("[MSW] Mocking enabled"),
        timeout: 15_000,
      });
      await Promise.all([enabled, page.goto(DEV, { waitUntil: "load" })]);
      await page.getByText(MOCK_LABEL).waitFor({ state: "visible", timeout: 5000 });
      const sw = await swCount(page);
      check(sw === 1, `có ${sw} service worker (cần 1)`);
      const worker = consoleLines.find((l) => l.includes("Worker script URL"))?.split("URL:")[1]?.trim() ?? "?";
      return { note: `"[MSW] Mocking enabled", có nhãn, 1 service worker (${worker})` };
    });
  } finally {
    await stopServer(server);
  }
});

await step("F0-3 preview", async () => {
  const server = await startServer("preview", [VITE, "preview", "--port", "4173", "--strictPort", "--host", "localhost"], {}, PREVIEW);
  try {
    return await scenario("F0-3", async ({ page, consoleLines }) => {
      const requests = [];
      page.on("request", (r) => requests.push(r.url()));
      await page.goto(PREVIEW, { waitUntil: "networkidle" });
      await page.getByRole("heading", LOGIN_HEADING).waitFor(); // chưa đăng nhập → /login
      // Trên Mac `-apple-system` đứng trước nên trình duyệt không cần Be Vietnam Pro → ép tải để chứng minh
      // font đi từ /assets/ cùng origin (KH 4.1 #7).
      const faces = await page.evaluate(async () => (await document.fonts.load('400 17px "Be Vietnam Pro"', "Tiếng Việt")).length);
      await page.waitForLoadState("networkidle");
      const origin = new URL(PREVIEW).origin;
      const outside = requests.filter((u) => {
        try {
          return new URL(u).origin !== origin;
        } catch {
          return true;
        }
      });
      check(outside.length === 0, `${outside.length} request ra ngoài origin: ${outside.slice(0, 3).join(", ")}`);
      const fonts = requests.filter((u) => /^\/assets\/be-vietnam-pro-[^/]+\.woff2$/.test(new URL(u).pathname));
      check(faces > 0 && fonts.length > 0, `không tải được Be Vietnam Pro từ /assets/ (faces=${faces})`);
      check(!requests.some((u) => u.includes("mockServiceWorker")), "bản build tải mockServiceWorker");
      check(mswLines(consoleLines).length === 0, `console có "${mswLines(consoleLines)[0]}"`);
      const sw = await swCount(page);
      check(sw === 0, `có ${sw} service worker`);
      return { note: `${requests.length} request, 0 ngoài origin; font từ /assets/: ${fonts.length} tệp woff2; 0 service worker` };
    });
  } finally {
    await stopServer(server);
  }
});

// F1 — đăng nhập thật qua dev server (proxy /api → backend). Lý do BỎ QUA duy nhất: backend tắt.
const backendOk = failedStep ? false : await backendUp();
if (backendOk) password = readDemoPassword();
const f1 = (name, fn) =>
  step(name, async () => {
    if (!backendOk) return { status: "BỎ QUA", note: "BỎ QUA — backend tắt" };
    await ensureF1Server();
    return fn();
  });

for (const [i, username] of Object.keys(ACCOUNTS).entries()) {
  await f1(`F1-${i + 1} ${username}: thanh bên đúng quyền`, () =>
    scenario(`F1-${i + 1}`, async ({ page }) => {
      await signInAs(page, username, { screenshot: i === 0 ? "login.png" : undefined });
      await expectSidebar(page, username);
      await expectStorageEmpty(page, username);
      await shoot(page, `sidebar-${username}.png`);
      const { has, home } = ACCOUNTS[username];
      return { note: `vào ${home}; có ${has.join(", ")}; không có mục ngoài quyền; Storage/IndexedDB rỗng` };
    }),
  );
}

await f1("F1-4 quan.tm không OTP → ô OTP", () =>
  scenario("F1-4", async ({ page }) => {
    // Chỉ thử MỘT lần mỗi lượt: nếu quan.tm chưa enroll MFA, backend đếm là 1 lần thất bại (5 lần/10 phút → khoá).
    const status = await submitLogin(page, "quan.tm");
    const state = await afterSubmit(page);
    if (state !== "otp") {
      throw new Error(`không sang bước OTP (${state}; POST /api/auth/login → ${status}) — nếu là "chưa được cài": enroll MFA cho quan.tm (CLI app.auth.mfa); mỗi lượt verify tính 1 lần thất bại`);
    }
    const boxes = await page.getByLabel(/^Chữ số \d$/).count();
    check(boxes === 6, `bước OTP có ${boxes} ô, cần 6`);
    await expectStorageEmpty(page, "quan.tm");
    await shoot(page, "login-otp.png");
    return { note: '401 mfa_required → màn "Nhập mã xác thực", 6 ô; không đăng nhập tiếp' };
  }),
);

await f1("F1-5 tải lại trang → vẫn đăng nhập", () =>
  scenario("F1-5", async ({ page }) => {
    await signInAs(page, "an.nv");
    await page.reload({ waitUntil: "load" });
    await expectSignedIn(page, "an.nv (sau tải lại)");
    check(new URL(page.url()).pathname !== "/login", "bị đưa về /login sau tải lại");
    await expectStorageEmpty(page, "an.nv (sau tải lại)");
    return { note: "F5 → refresh bằng cookie → vẫn ở trong; Storage/IndexedDB rỗng" };
  }),
);

await f1("F1-6 2 tab tải lại cùng lúc × 5", () =>
  scenario("F1-6", async ({ page, newTab }) => {
    await signInAs(page, "an.nv");
    const second = await newTab();
    await second.goto(`${DEV}/`, { waitUntil: "load" });
    await expectSignedIn(second, "tab 2");
    const ROUNDS = 5;
    for (let round = 1; round <= ROUNDS; round += 1) {
      // Tải lại CẢ HAI cùng lúc → 2 lời gọi refresh đua nhau. Không có khoá xuyên tab thì refresh token cũ bị trình
      // hai lần → backend thu hồi cả họ → cả 2 tab về /login. Chờ cả 2 vào xong mới sang vòng sau (không cắt ngang
      // một refresh đang bay).
      await Promise.all([page.reload({ waitUntil: "load" }), second.reload({ waitUntil: "load" })]);
      const states = await Promise.all([landing(page), landing(second)]);
      check(states.every((s) => s === "signedIn"), `vòng ${round}: tab 1 = ${states[0]}, tab 2 = ${states[1]}`);
    }
    await expectStorageEmpty(page, "tab 1");
    await expectStorageEmpty(second, "tab 2");
    return { note: `${ROUNDS} vòng tải lại đồng thời, cả 2 tab vẫn đăng nhập; Storage/IndexedDB rỗng` };
  }),
);

// c) dọn dẹp — luôn chạy
{
  const t0 = performance.now();
  const notes = [];
  try {
    await browser?.close();
  } catch (error) {
    notes.push(`đóng Chromium lỗi: ${error.message}`);
  }
  const left = [];
  for (const child of [...servers]) if (!(await stopServer(child))) left.push(child.pid);
  if (left.length) notes.push(`còn tiến trình: ${left.join(", ")}`);
  for (const url of [DEV, PREVIEW]) if (await responds(url)) notes.push(`${url} vẫn trả lời`);
  results.push({
    name: "Dọn dẹp",
    status: notes.length ? "FAIL" : "PASS",
    ms: performance.now() - t0,
    note: notes.length ? notes.join("; ") : "đã tắt mọi server, đóng Chromium; cổng 5173/4173 trống",
  });
  if (notes.length && !failedStep) failedStep = "Dọn dẹp";
}

// ---------------------------------------------------------------- summary

const git = (...args) => spawnSync("git", args, { cwd: REPO, encoding: "utf8" }).stdout?.trim() ?? "";
const head = `${git("rev-parse", "--short", "HEAD") || "?"}${git("status", "--porcelain", "--", "frontend") ? " (+ thay đổi chưa commit ở frontend/)" : ""}`;
const cell = (text) => redact(text).replaceAll("|", "/").replaceAll("\n", " ");
const lines = [
  `npm run verify — ${started.toLocaleString("vi-VN")} · HEAD ${head} · chặng đã dựng: ${BUILT} · Node ${process.version}`,
  `Log: frontend/.verify/run-${STAMP}.log`,
  "",
  "| Bước | PASS/FAIL/BỎ QUA | Thời gian | Ghi chú |",
  "|---|---|---|---|",
  ...results.map((r) => `| ${r.name} | ${r.status} | ${(r.ms / 1000).toFixed(1)} s | ${cell(r.note)} |`),
  "",
  failedStep ? `KẾT LUẬN: ĐỎ ở bước ${failedStep}` : "KẾT LUẬN: XANH",
];
const summary = lines.join("\n");
writeFileSync(join(OUT, "summary.txt"), `${summary}\n`);
log(`\n${summary}`);
console.log(redact(summary));
process.exitCode = failedStep ? 1 : 0;
