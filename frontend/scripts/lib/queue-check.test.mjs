// t38 (12b Q-fe-23, phương án D): hàm quyết định của verify F3-1 — hàng đợi dev có thể quá 200 ca (nợ API #10).
// t106 (N-L2Q): màn chỉ hiện 10 ca đầu mỗi nhóm → kiểm theo trang; ticket mới tìm bằng ô tìm (checkSearchHit).
import { describe, expect, it } from "vitest";
// N-PA: màn bỏ trần 200 (phân trang theo `next_cursor`) — chữ màn thành hàm theo số ca đã tải; so tại N = 200 (verify F3 làm lại
// ở chặng nối thật sau khi be-tuan8 merge — FE-STATE).
import { GROUP_PAGE_SIZE, noMatchPartialText, searchScopeNote } from "../../src/routes/l2/queue.ts";
import {
  checkQueueSnapshot,
  checkSearchHit,
  noMatchFullText,
  OUTSIDE_NOTE,
  PAGE_SIZE,
  pagerLabel,
  queueTicketVerdict,
  searchCountText,
  serverGroups,
} from "./queue-check.mjs";

describe("t38: quyết định F3-1 cho một ticket mới", () => {
  it("có mặt → present (dù hàng đợi đủ 200 hay không)", () => {
    expect(queueTicketVerdict({ present: true, shown: 200, limit: 200, overflowShown: true })).toStrictEqual({ verdict: "present" });
    expect(queueTicketVerdict({ present: true, shown: 3, limit: 200, overflowShown: false })).toStrictEqual({ verdict: "present" });
  });

  it("vắng + đủ 200 + có cảnh báo → outside (PASS kèm ghi chú); thiếu cảnh báo → fail", () => {
    expect(queueTicketVerdict({ present: false, shown: 200, limit: 200, overflowShown: true })).toStrictEqual({
      verdict: "outside",
      note: OUTSIDE_NOTE,
    });
    expect(OUTSIDE_NOTE).toBe("ngoài 200 ca — đã kiểm cảnh báo (nợ API #10)");
    expect(queueTicketVerdict({ present: false, shown: 200, limit: 200, overflowShown: false }).verdict).toBe("fail");
  });

  it("vắng + dưới 200 → fail (bug thật)", () => {
    const r = queueTicketVerdict({ present: false, shown: 199, limit: 200, overflowShown: false });
    expect(r.verdict).toBe("fail");
    expect(r.reason).toContain("bug thật");
  });
});

describe("t38: checkQueueSnapshot (F3-1) — ảnh chụp mặc định: 10 ca đầu mỗi nhóm", () => {
  const row = (id, ticket, code) => ({ id, ticket, code });
  const E0 = { id: "t-e0", code: "E0", from: "F2-4" };
  const E3 = { id: "t-e3", code: "E3", from: "F2-2" };
  const items = [
    { escalation_id: 1, ticket_id: "t-a", priority: 1 },
    { escalation_id: 2, ticket_id: "t-e0", priority: 2 },
    { escalation_id: 3, ticket_id: "t-e3", priority: 6 },
  ];
  const group = (priority, name, rows, over = {}) => ({ priority, name, count: `· ${rows.length} ca`, expanded: true, rows, pager: null, ...over });
  const groups = [
    group(1, "Rất cao", [row(1, "t-a", "E7")]),
    group(2, "An ninh", [row(2, "t-e0", "E0")]),
    group(6, "Thường", [row(3, "t-e3", "E3")]),
  ];

  it("cả hai có mặt, E0 trước E3, priority không giảm, dòng = server → không lỗi; trả ticket có mặt để tìm", () => {
    const r = checkQueueSnapshot({ groups, items, limit: 200, overflowShown: false, tickets: [E0, E3] });
    expect(r.problems).toStrictEqual([]);
    expect(r.present.map((t) => [t.id, t.item.escalation_id])).toStrictEqual([
      ["t-e0", 2],
      ["t-e3", 3],
    ]);
    expect(r.outside).toStrictEqual([]);
  });

  it("priority giảm theo thứ tự hiển thị → lỗi; nhóm/dòng khác thứ tự server → lỗi", () => {
    const swapped = [groups[0], groups[2], groups[1]];
    const r = checkQueueSnapshot({ groups: swapped, items, limit: 200, overflowShown: false, tickets: [] });
    expect(r.problems.some((p) => p.includes("đứng sau nhóm priority 6"))).toBe(true);
    expect(r.problems.some((p) => p.includes("khác nhóm theo thứ tự server"))).toBe(true);
  });

  it("dòng trên màn = ĐÚNG 10 ca đầu của nhóm, đúng thứ tự; thiếu / thừa / lệch thứ tự / trang 2 → lỗi; thanh trang đúng chữ", () => {
    const big = Array.from({ length: 25 }, (_, i) => ({ escalation_id: 100 + i, ticket_id: `b-${i}`, priority: 6 }));
    const rows = (list) => list.map((i) => row(i.escalation_id, i.ticket_id, "E3"));
    const ok = { priority: 6, name: "Thường", count: "· 25 ca", expanded: true, rows: rows(big.slice(0, 10)), pager: "Ca 1–10 / 25 · trang 1/3" };
    const check = (over) => checkQueueSnapshot({ groups: [{ ...ok, ...over }], items: big, limit: 200, overflowShown: false, tickets: [] }).problems;
    expect(check({})).toStrictEqual([]);
    expect(check({ rows: rows(big.slice(0, 9)) }).some((p) => p.includes("9 dòng trên màn khác 10 ca đầu"))).toBe(true);
    expect(check({ rows: rows(big.slice(0, 11)) }).some((p) => p.includes("11 dòng"))).toBe(true);
    expect(check({ rows: rows([big[1], big[0], ...big.slice(2, 10)]) }).length).toBe(1);
    expect(check({ rows: rows(big.slice(10, 20)) }).length).toBe(1);
    expect(check({ pager: null })).toStrictEqual(['nhóm #1 "Thường": thanh trang "null", cần "Ca 1–10 / 25 · trang 1/3"']);
    expect(check({ pager: "Ca 11–20 / 25 · trang 2/3" }).length).toBe(1);
    expect(check({ count: "· 10 ca" })).toStrictEqual(['nhóm #1 "Thường": số ca "· 10 ca", cần "· 25 ca"']);
    expect(check({ expanded: false }).some((p) => p.includes("đang thu gọn"))).toBe(true);
    // Nhóm ≤ 10 ca mà có thanh trang → lỗi.
    const small = checkQueueSnapshot({ groups: [group(6, "Thường", [row(3, "t-e3", "E3")], { pager: "Ca 1–1 / 1 · trang 1/1" })], items: [items[2]], limit: 200, overflowShown: false, tickets: [] });
    expect(small.problems).toStrictEqual(['nhóm #1 "Thường": thanh trang "Ca 1–1 / 1 · trang 1/1", cần không có']);
  });

  it("E3 vắng khi đủ 200 ca + có cảnh báo → chỉ ghi chú (outside); vắng khi dưới 200 → lỗi", () => {
    // 199 ca cũ hạng 1 + ca E0 mới hạng 2 = đủ 200; ca E3 mới (hạng 6) nằm ngoài. E0 ở cuối hàng đợi, nhóm riêng.
    const old = Array.from({ length: 199 }, (_, i) => ({ escalation_id: 100 + i, ticket_id: `old-${i}`, priority: 1 }));
    const full = [...old, { escalation_id: 2, ticket_id: "t-e0", priority: 2 }];
    const fullGroups = [
      { priority: 1, name: "Rất cao", count: "· 199 ca", expanded: true, rows: old.slice(0, 10).map((i) => row(i.escalation_id, i.ticket_id, "E7")), pager: "Ca 1–10 / 199 · trang 1/20" },
      group(2, "An ninh", [row(2, "t-e0", "E0")]),
    ];
    const r = checkQueueSnapshot({ groups: fullGroups, items: full, limit: 200, overflowShown: true, tickets: [E0, E3] });
    expect(r.problems).toStrictEqual([]);
    expect(r.notes).toContain(`E3 (F2-2): ${OUTSIDE_NOTE}`);
    expect(r.present.map((t) => t.id)).toStrictEqual(["t-e0"]);
    expect(r.outside.map((t) => t.id)).toStrictEqual(["t-e3"]);

    const short = checkQueueSnapshot({ groups: groups.slice(0, 2), items: items.slice(0, 2), limit: 200, overflowShown: false, tickets: [E3] });
    expect(short.problems.some((p) => p.includes("bug thật"))).toBe(true);
  });

  it("cảnh báo 'quá 200 ca' lệch với số ca → lỗi", () => {
    const r = checkQueueSnapshot({ groups, items, limit: 200, overflowShown: true, tickets: [] });
    expect(r.problems).toContain('3 ca mà cảnh báo "quá 200 ca" có hiện');
  });

  it("nhóm của E0 đứng SAU nhóm của E3 → lỗi", () => {
    const flipped = [
      { escalation_id: 3, ticket_id: "t-e3", priority: 2 },
      { escalation_id: 2, ticket_id: "t-e0", priority: 6 },
    ];
    const flippedGroups = [group(2, "A", [row(3, "t-e3", "E3")]), group(6, "B", [row(2, "t-e0", "E0")])];
    const r = checkQueueSnapshot({ groups: flippedGroups, items: flipped, limit: 200, overflowShown: false, tickets: [E0, E3] });
    expect(r.problems).toStrictEqual(["nhóm của ca E0 (#2) phải đứng TRƯỚC nhóm của ca E3 (#1)"]);
  });

  it("có mặt nhưng sai nhóm / sai mã (sau khi gõ ô tìm) → lỗi", () => {
    const base = { ticket: E0, item: items[1], total: 3, limit: 200, countText: "Khớp 1 / 3 ca", overflowShown: false, noMatchFullShown: false };
    expect(checkSearchHit({ ...base, rows: [{ ticket: "t-e0", code: "E0", priority: 2 }] })).toStrictEqual([]);
    expect(checkSearchHit({ ...base, rows: [{ ticket: "t-e0", code: "E0", priority: 4 }] })).toStrictEqual([
      "E0 (F2-4): nằm ở nhóm priority 4, server trả priority 2",
    ]);
    expect(checkSearchHit({ ...base, rows: [{ ticket: "t-e0", code: "E2", priority: 2 }] })).toStrictEqual(["E0 (F2-4): dòng mang mã E2"]);
  });
});

describe("t106: verify N-L2Q — nhóm theo server, chữ thanh trang / dòng đếm khớp màn, kết quả ô tìm", () => {
  it("hằng của verify = hằng của màn (cỡ trang, phần 'chỉ tìm trong 200 ca', câu không khớp khi chạm trần)", () => {
    expect(PAGE_SIZE).toBe(GROUP_PAGE_SIZE);
    expect(searchCountText(1, 200, 200)).toBe(`Khớp 1 / 200 ca${searchScopeNote(200)}`);
    expect(searchCountText(3, 199, 200)).toBe("Khớp 3 / 199 ca");
    expect(noMatchFullText(200)).toBe(noMatchPartialText(200));
  });

  it("serverGroups gom nhóm LIÊN TIẾP, giữ thứ tự; pagerLabel đúng chữ màn", () => {
    const items = [1, 1, 4, 4, 1].map((priority, i) => ({ escalation_id: i, priority }));
    expect(serverGroups(items).map((g) => [g.priority, g.items.map((i) => i.escalation_id)])).toStrictEqual([
      [1, [0, 1]],
      [4, [2, 3]],
      [1, [4]],
    ]);
    expect(serverGroups([])).toStrictEqual([]);
    expect([pagerLabel(1, 25), pagerLabel(2, 25), pagerLabel(3, 25), pagerLabel(1, 11)]).toStrictEqual([
      "Ca 1–10 / 25 · trang 1/3",
      "Ca 11–20 / 25 · trang 2/3",
      "Ca 21–25 / 25 · trang 3/3",
      "Ca 1–10 / 11 · trang 1/2",
    ]);
  });

  it("có mặt: dòng đếm phải 'Khớp 1 / N ca' (+ phần chạm trần), đúng 1 dòng của ticket", () => {
    const ticket = { id: "t-e3", code: "E3", from: "F2-2" };
    const base = { ticket, item: { priority: 6 }, total: 200, limit: 200, overflowShown: true, noMatchFullShown: false };
    const rows = [{ ticket: "t-e3", code: "E3", priority: 6 }];
    expect(checkSearchHit({ ...base, countText: "Khớp 1 / 200 ca · chỉ tìm trong 200 ca đã tải", rows })).toStrictEqual([]);
    expect(checkSearchHit({ ...base, countText: "Khớp 1 / 200 ca", rows })).toStrictEqual([
      'E3 (F2-2): dòng đếm "Khớp 1 / 200 ca", cần "Khớp 1 / 200 ca · chỉ tìm trong 200 ca đã tải"',
    ]);
    expect(checkSearchHit({ ...base, countText: "Khớp 1 / 200 ca · chỉ tìm trong 200 ca đã tải", rows: [] })).toStrictEqual([
      "E3 (F2-2): gõ mã ticket mà màn hiện 0 dòng",
    ]);
    expect(checkSearchHit({ ...base, countText: null, rows }).length).toBe(1);
  });

  it("vắng: hợp lệ CHỈ khi đủ 200 + cảnh báo + câu 'có thể nằm ngoài danh sách'; dưới 200 → bug thật", () => {
    const ticket = { id: "t-e3", code: "E3", from: "F2-2" };
    const full = { ticket, item: undefined, total: 200, limit: 200, countText: "Khớp 0 / 200 ca · chỉ tìm trong 200 ca đã tải", rows: [] };
    expect(checkSearchHit({ ...full, overflowShown: true, noMatchFullShown: true })).toStrictEqual([]);
    expect(checkSearchHit({ ...full, overflowShown: true, noMatchFullShown: false })).toStrictEqual([
      `E3 (F2-2): vắng mà không có câu "${noMatchPartialText(200)}"`,
    ]);
    expect(checkSearchHit({ ...full, overflowShown: false, noMatchFullShown: true }).some((p) => p.includes("KHÔNG có cảnh báo"))).toBe(true);
    const short = checkSearchHit({ ...full, total: 150, countText: "Khớp 0 / 150 ca", overflowShown: false, noMatchFullShown: false });
    expect(short.some((p) => p.includes("bug thật"))).toBe(true);
  });
});
