// Hàm thuần cho verify F3-1 (12b Q-fe-23, phương án D). Không đụng trình duyệt — verify.mjs chụp số liệu từ màn rồi
// gọi các hàm này; vitest (t38) kiểm các nhánh. Lý do tồn tại: backend chỉ cho `limit ≤ 200`, sắp `priority` →
// `created_at` tăng dần, không có phân trang (nợ API #10) → hàng đợi dev đầy ca CŨ hạng cao thì ca mới có thể nằm ngoài
// 200 ca đầu. Khi đó màn phải báo "quá 200 ca" — đó là hành vi đúng, không phải lỗi; còn dưới 200 ca mà thiếu = bug thật.

export const OUTSIDE_NOTE = "ngoài 200 ca — đã kiểm cảnh báo (nợ API #10)";

/**
 * Quyết định cho MỘT ticket mới trên hàng đợi đang hiện.
 * @param {{present: boolean, shown: number, limit: number, overflowShown: boolean}} input
 *   present: ticket có trong danh sách server trả · shown: số ca đang hiện · limit: trần (200) ·
 *   overflowShown: khung cảnh báo "quá 200 ca" có hiện không
 * @returns {{verdict: "present"} | {verdict: "outside", note: string} | {verdict: "fail", reason: string}}
 */
export function queueTicketVerdict({ present, shown, limit, overflowShown }) {
  if (present) return { verdict: "present" };
  if (shown >= limit) {
    return overflowShown
      ? { verdict: "outside", note: OUTSIDE_NOTE }
      : { verdict: "fail", reason: `không có trong ${shown} ca đang hiện và KHÔNG có cảnh báo "quá ${limit} ca"` };
  }
  return { verdict: "fail", reason: `không có trong hàng đợi dù chỉ ${shown} ca (< ${limit}) — bug thật` };
}

/**
 * Kiểm ảnh chụp hàng đợi của F3-1.
 * @param {object} input
 * @param {{priority: number, name: string, rows: {id: number, ticket: string, code: string}[]}[]} input.groups
 *   nhóm theo thứ tự HIỂN THỊ (đọc từ DOM)
 * @param {{escalation_id: number, ticket_id: string, priority: number}[]} input.items  thân JSON server trả
 * @param {number} input.limit
 * @param {boolean} input.overflowShown
 * @param {{id: string, code: string, from: string}[]} input.tickets  ticket mới cần tìm (vd E0 của F2-4, E3 của F2-2)
 * @returns {{problems: string[], notes: string[], shown: string[]}}  shown = ticket mới đang hiện (theo thứ tự `tickets`)
 */
export function checkQueueSnapshot({ groups, items, limit, overflowShown, tickets }) {
  const problems = [];
  const notes = [];
  const shown = [];

  // a) priority của các nhóm theo thứ tự hiển thị KHÔNG giảm; dòng trên màn = đúng thứ tự server.
  for (let i = 1; i < groups.length; i += 1) {
    if (groups[i].priority < groups[i - 1].priority) {
      problems.push(`nhóm #${i + 1} "${groups[i].name}" (priority ${groups[i].priority}) đứng sau nhóm priority ${groups[i - 1].priority}`);
    }
  }
  // Cảnh báo "quá 200 ca" hiện KHI VÀ CHỈ KHI server trả đủ trần.
  if ((items.length >= limit) !== overflowShown) {
    problems.push(`${items.length} ca mà cảnh báo "quá ${limit} ca" ${overflowShown ? "có" : "không"} hiện`);
  }
  const dom = groups.flatMap((g) => g.rows.map((r) => r.id));
  const server = items.map((i) => i.escalation_id);
  if (JSON.stringify(dom) !== JSON.stringify(server)) {
    problems.push(`thứ tự ${dom.length} dòng trên màn khác thứ tự server (${server.length} ca)`);
  }

  // b) từng ticket mới: có mặt → đúng nhóm, đúng mã; vắng → theo queueTicketVerdict.
  const groupIndex = {};
  for (const t of tickets) {
    const item = items.find((i) => i.ticket_id === t.id);
    const result = queueTicketVerdict({ present: !!item, shown: items.length, limit, overflowShown });
    if (result.verdict === "fail") {
      problems.push(`${t.code} (${t.from}) ${t.id}: ${result.reason}`);
      continue;
    }
    if (result.verdict === "outside") {
      notes.push(`${t.code} (${t.from}): ${result.note}`);
      continue;
    }
    const g = groups.findIndex((grp) => grp.rows.some((r) => r.ticket === t.id));
    if (g < 0) {
      problems.push(`${t.code} (${t.from}): có trong JSON server nhưng không có dòng trên màn`);
      continue;
    }
    const row = groups[g].rows.find((r) => r.ticket === t.id);
    if (row.code !== t.code) problems.push(`${t.code} (${t.from}): dòng mang mã ${row.code}`);
    if (groups[g].priority !== item.priority) {
      problems.push(`${t.code} (${t.from}): nằm ở nhóm priority ${groups[g].priority}, server trả priority ${item.priority}`);
    }
    groupIndex[t.code] = g;
    shown.push(t.id);
    notes.push(`${t.code} (${t.from}) ở nhóm #${g + 1} "${groups[g].name}"`);
  }
  if (groupIndex.E0 !== undefined && groupIndex.E3 !== undefined && !(groupIndex.E0 < groupIndex.E3)) {
    problems.push(`nhóm của ca E0 (#${groupIndex.E0 + 1}) phải đứng TRƯỚC nhóm của ca E3 (#${groupIndex.E3 + 1})`);
  }
  return { problems, notes, shown };
}
