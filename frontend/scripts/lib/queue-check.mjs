// Hàm thuần cho verify F3 (12b Q-fe-23, phương án D; N-L2Q). Không đụng trình duyệt — verify.mjs chụp số liệu từ màn rồi
// gọi các hàm này; vitest (t38, t106) kiểm các nhánh. Lý do tồn tại: backend chỉ cho `limit ≤ 200`, sắp `priority` →
// `created_at` tăng dần, không có phân trang (nợ API #10) → hàng đợi dev đầy ca CŨ hạng cao thì ca mới có thể nằm ngoài
// 200 ca đầu. Khi đó màn phải báo "quá 200 ca" — đó là hành vi đúng, không phải lỗi; còn dưới 200 ca mà thiếu = bug thật.
// N-L2Q: màn chỉ hiện 10 ca đầu mỗi nhóm (phân trang trong nhóm) và ca MỚI nằm cuối nhóm → verify tìm ticket bằng Ô TÌM.

export const OUTSIDE_NOTE = "ngoài 200 ca — đã kiểm cảnh báo (nợ API #10)";
/** Cỡ trang trong một nhóm — bằng `GROUP_PAGE_SIZE` của src/routes/l2/queue.ts (t106 so hai hằng). */
export const PAGE_SIZE = 10;

/** Chữ thanh trang của một nhóm: "Ca a–b / N · trang p/P". */
export const pagerLabel = (page, total, size = PAGE_SIZE) =>
  `Ca ${(page - 1) * size + 1}–${Math.min(page * size, total)} / ${total} · trang ${page}/${Math.max(1, Math.ceil(total / size))}`;

/** Dòng đếm khi đang tìm: "Khớp k / N ca", chạm trần thì thêm " · chỉ tìm trong 200 ca đã tải". */
export const searchCountText = (matched, total, limit) =>
  `Khớp ${matched} / ${total} ca${total >= limit ? ` · chỉ tìm trong ${limit} ca đã tải` : ""}`;

/** Câu khi 0 ca khớp mà hàng đợi đã chạm trần — không khẳng định ca không tồn tại. */
export const noMatchFullText = (limit) =>
  `Không có ca nào khớp trong ${limit} ca đã tải — ca cần tìm có thể nằm ngoài danh sách.`;

/** Gom các ca LIÊN TIẾP cùng `priority` của thân JSON server (viết lại độc lập với `groupQueue` của màn). */
export function serverGroups(items) {
  const groups = [];
  for (const item of items) {
    const last = groups.at(-1);
    if (last && last.priority === item.priority) last.items.push(item);
    else groups.push({ priority: item.priority, items: [item] });
  }
  return groups;
}

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
 * Kiểm ảnh chụp hàng đợi MẶC ĐỊNH (không tìm, mọi nhóm mở, trang 1, thẻ "Tất cả") của F3-1.
 * @param {object} input
 * @param {{priority: number, name: string, count: string, expanded: boolean, rows: {id: number, ticket: string, code: string}[],
 *   pager: string | null}[]} input.groups  nhóm theo thứ tự HIỂN THỊ (đọc từ DOM; `count` = chữ "· N ca", `pager` = chữ thanh
 *   trang hoặc null)
 * @param {{escalation_id: number, ticket_id: string, priority: number}[]} input.items  thân JSON server trả
 * @param {number} input.limit
 * @param {boolean} input.overflowShown
 * @param {{id: string, code: string, from: string}[]} input.tickets  ticket mới cần tìm (vd E0 của F2-4, E3 của F2-2)
 * @returns {{problems: string[], notes: string[], present: object[], outside: object[]}}
 *   present / outside: ticket (theo thứ tự `tickets`) có trong thân JSON / vắng nhưng hợp lệ (ngoài 200 ca) — verify gõ
 *   từng ticket vào ô tìm rồi kiểm bằng `checkSearchHit`.
 */
export function checkQueueSnapshot({ groups, items, limit, overflowShown, tickets, pageSize = PAGE_SIZE }) {
  const problems = [];
  const notes = [];
  const present = [];
  const outside = [];

  // a) priority của các nhóm theo thứ tự hiển thị KHÔNG giảm.
  for (let i = 1; i < groups.length; i += 1) {
    if (groups[i].priority < groups[i - 1].priority) {
      problems.push(`nhóm #${i + 1} "${groups[i].name}" (priority ${groups[i].priority}) đứng sau nhóm priority ${groups[i - 1].priority}`);
    }
  }
  // Cảnh báo "quá 200 ca" hiện KHI VÀ CHỈ KHI server trả đủ trần.
  if ((items.length >= limit) !== overflowShown) {
    problems.push(`${items.length} ca mà cảnh báo "quá ${limit} ca" ${overflowShown ? "có" : "không"} hiện`);
  }
  // b) nhóm trên màn = nhóm liên tiếp theo thứ tự server; mỗi nhóm: "· N ca" đúng, đang mở, dòng = đúng `pageSize` ca ĐẦU của
  //    nhóm (đúng thứ tự), thanh trang có KHI VÀ CHỈ KHI nhóm > `pageSize` ca.
  const server = serverGroups(items);
  const shape = (list) => list.map((g) => g.priority).join(",");
  if (shape(groups) !== shape(server)) {
    problems.push(`nhóm trên màn [${shape(groups)}] khác nhóm theo thứ tự server [${shape(server)}]`);
  } else {
    server.forEach((s, i) => {
      const g = groups[i];
      const where = `nhóm #${i + 1} "${g.name}"`;
      const size = s.items.length;
      if (g.count !== `· ${size} ca`) problems.push(`${where}: số ca "${g.count}", cần "· ${size} ca"`);
      if (!g.expanded) problems.push(`${where}: đang thu gọn — mặc định mọi nhóm phải mở`);
      const want = s.items.slice(0, pageSize).map((item) => item.escalation_id);
      const got = g.rows.map((r) => r.id);
      if (JSON.stringify(got) !== JSON.stringify(want)) {
        problems.push(`${where}: ${got.length} dòng trên màn khác ${want.length} ca đầu của nhóm theo thứ tự server`);
      }
      const pager = size > pageSize ? pagerLabel(1, size, pageSize) : null;
      if (g.pager !== pager) problems.push(`${where}: thanh trang "${g.pager}", cần ${pager ? `"${pager}"` : "không có"}`);
    });
  }

  // c) từng ticket mới: có trong JSON → verify tìm bằng ô tìm; vắng → theo queueTicketVerdict.
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
      outside.push(t);
      continue;
    }
    const g = server.findIndex((grp) => grp.items.includes(item));
    groupIndex[t.code] = g;
    present.push({ ...t, item });
    notes.push(`${t.code} (${t.from}) ở nhóm #${g + 1} "${groups[g]?.name ?? "?"}" (vị trí ${server[g].items.indexOf(item) + 1}/${server[g].items.length})`);
  }
  if (groupIndex.E0 !== undefined && groupIndex.E3 !== undefined && !(groupIndex.E0 < groupIndex.E3)) {
    problems.push(`nhóm của ca E0 (#${groupIndex.E0 + 1}) phải đứng TRƯỚC nhóm của ca E3 (#${groupIndex.E3 + 1})`);
  }
  return { problems, notes, present, outside };
}

/**
 * Màn sau khi gõ ticket_id của MỘT ticket mới vào ô tìm.
 * @param {object} input
 * @param {{id: string, code: string, from: string}} input.ticket
 * @param {{priority: number} | undefined} input.item  ca của ticket trong thân JSON (undefined = vắng, chỉ hợp lệ khi đủ trần)
 * @param {number} input.total  số ca server trả · @param {number} input.limit
 * @param {string | null} input.countText  chữ dòng đếm (null = không hiện)
 * @param {{ticket: string, code: string, priority: number}[]} input.rows  các dòng đang hiện
 * @param {boolean} input.overflowShown  khung "quá 200 ca" · @param {boolean} input.noMatchFullShown  câu `noMatchFullText`
 * @returns {string[]} problems
 */
export function checkSearchHit({ ticket, item, total, limit, countText, rows, overflowShown, noMatchFullShown }) {
  const problems = [];
  const who = `${ticket.code} (${ticket.from})`;
  const count = searchCountText(item ? 1 : 0, total, limit);
  if (countText !== count) problems.push(`${who}: dòng đếm "${countText}", cần "${count}"`);
  if (item) {
    if (rows.length !== 1 || rows[0].ticket !== ticket.id) {
      problems.push(`${who}: gõ mã ticket mà màn hiện ${rows.length} dòng${rows.length ? ` (${rows.map((r) => r.ticket).join(", ")})` : ""}`);
      return problems;
    }
    if (rows[0].code !== ticket.code) problems.push(`${who}: dòng mang mã ${rows[0].code}`);
    if (rows[0].priority !== item.priority) {
      problems.push(`${who}: nằm ở nhóm priority ${rows[0].priority}, server trả priority ${item.priority}`);
    }
    return problems;
  }
  if (rows.length > 0) problems.push(`${who}: không có trong JSON mà màn hiện ${rows.length} dòng`);
  if (total < limit) problems.push(`${who}: không có trong hàng đợi dù chỉ ${total} ca (< ${limit}) — bug thật`);
  if (!overflowShown) problems.push(`${who}: vắng, ${total} ca mà KHÔNG có cảnh báo "quá ${limit} ca"`);
  if (!noMatchFullShown) problems.push(`${who}: vắng mà không có câu "${noMatchFullText(limit)}"`);
  return problems;
}
