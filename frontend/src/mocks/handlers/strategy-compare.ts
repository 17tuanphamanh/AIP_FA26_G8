import { http } from "msw";
import { buildStrategies } from "../fixtures/strategy.ts";
import { invalid, reply, requireAny } from "./shared.ts";

// So sánh phương án — `GET /api/dashboard/strategies` CHƯA CÓ ở backend (be-tuan8; hợp đồng N-PA §2). Xoá khi be-tuan8 merge.
// CHỈ route này: `/api/dashboard/business`, `/ai` là route thật M9 A3 — không handler nào (t118).
export const strategyCompareHandlers = [
  http.get("/api/dashboard/strategies", async ({ request }) => {
    const who = await requireAny(request, ["dashboard:read:all"]);
    if ("response" in who) return who.response;
    const q = new URL(request.url).searchParams;
    const from = q.get("from");
    const to = q.get("to");
    const source = q.get("source") ?? "real";
    const fields: string[] = [];
    if (!from || Number.isNaN(Date.parse(from)) || !/(Z|[+-]\d\d:\d\d)$/.test(from)) fields.push("query.from");
    if (!to || Number.isNaN(Date.parse(to)) || !/(Z|[+-]\d\d:\d\d)$/.test(to)) fields.push("query.to");
    if (source !== "real" && source !== "sim") fields.push("query.source");
    if (fields.length > 0) return invalid(fields);
    return reply({ ...buildStrategies(source as "real" | "sim", new Date(from!).toISOString(), new Date(to!).toISOString()) });
  }),
];
