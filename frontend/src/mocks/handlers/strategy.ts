import { http } from "msw";
import { REASON_MAX, REASON_MIN, reasonLength, RUNTIME_STRATEGIES } from "../../api/strategy.ts";
import type { RuntimeStrategy, StrategyChange, StrategyView } from "../../api/types.ts";
import { initialHistory, initialStrategy } from "../fixtures/strategy.ts";
import { invalid, readJson, reply, requireAny } from "./shared.ts";

// Cách xử lý của hệ thống (D-67) — route CHƯA CÓ ở backend (be-tuan8; hợp đồng N-PA §1). Xoá file này khi be-tuan8 merge.
// Quyền hỏi backend THẬT (`/api/auth/me` — requireAny). Trạng thái chỉ trong bộ nhớ của trang (tải lại trang → về đầu).
// Thứ tự kiểm của PUT (phỏng theo hợp đồng): quyền → thân (422 `strategy`/`reason`) → 409 `same_as_current` → 200.
// Không giả 403 `reauth_required` (luồng xác nhận lại đã có vitest; demo không cần).

let state: StrategyView = initialStrategy();
let history: StrategyChange[] = initialHistory(Date.now());

/** Chỉ cho test: đặt lại trạng thái giữa các ca. */
export function resetStrategyMock(view: Partial<StrategyView> = {}, now = Date.now()) {
  state = { ...initialStrategy(), ...view };
  history = initialHistory(now);
}

const BODY_KEYS = new Set(["strategy", "reason"]);

export const strategyHandlers = [
  http.get("/api/admin/strategy", async ({ request }) => {
    const who = await requireAny(request, ["policy:read"]);
    if ("response" in who) return who.response;
    return reply(state);
  }),

  http.get("/api/admin/strategy/history", async ({ request }) => {
    const who = await requireAny(request, ["policy:read"]);
    if ("response" in who) return who.response;
    const raw = new URL(request.url).searchParams.get("limit");
    const limit = raw === null ? 50 : Number(raw);
    if (!Number.isInteger(limit) || limit < 1 || limit > 200) return invalid(["query.limit"]);
    return reply({ items: history.slice(0, limit), truncated: history.length > limit });
  }),

  http.put("/api/admin/strategy", async ({ request }) => {
    const who = await requireAny(request, ["policy:edit"]);
    if ("response" in who) return who.response;
    const body = await readJson(request);
    if (body === null || typeof body !== "object" || Array.isArray(body)) return invalid(["body"]);
    const b = body as Record<string, unknown>;
    const fields = Object.keys(b).filter((k) => !BODY_KEYS.has(k));
    const strategy = b.strategy;
    const okStrategy = typeof strategy === "string" && (RUNTIME_STRATEGIES as readonly string[]).includes(strategy) && state.selectable.includes(strategy as RuntimeStrategy);
    if (!okStrategy) fields.push("strategy");
    const reason = typeof b.reason === "string" ? b.reason.trim() : "";
    const n = reasonLength(reason);
    if (n < REASON_MIN || n > REASON_MAX) fields.push("reason");
    if (fields.length > 0) return invalid(fields);
    if (strategy === state.strategy) return reply({ detail: "same_as_current" }, 409);
    const at = new Date().toISOString();
    history = [{ changed_at: at, changed_by: who.me.user_id, strategy_from: state.strategy, strategy_to: strategy as RuntimeStrategy, reason }, ...history];
    state = { ...state, strategy: strategy as RuntimeStrategy, changed_by: who.me.user_id, changed_at: at, reason };
    return reply(state);
  }),
];
