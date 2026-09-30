// t38 (12b Q-fe-23, phương án D): hàm quyết định của verify F3-1 — hàng đợi dev có thể quá 200 ca (nợ API #10).
import { describe, expect, it } from "vitest";
import { checkQueueSnapshot, OUTSIDE_NOTE, queueTicketVerdict } from "./queue-check.mjs";

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

describe("t38: checkQueueSnapshot (F3-1)", () => {
  const row = (id, ticket, code) => ({ id, ticket, code });
  const E0 = { id: "t-e0", code: "E0", from: "F2-4" };
  const E3 = { id: "t-e3", code: "E3", from: "F2-2" };
  const groups = [
    { priority: 1, name: "Rất cao", rows: [row(1, "t-a", "E7")] },
    { priority: 2, name: "An ninh", rows: [row(2, "t-e0", "E0")] },
    { priority: 6, name: "Thường", rows: [row(3, "t-e3", "E3")] },
  ];
  const items = [
    { escalation_id: 1, ticket_id: "t-a", priority: 1 },
    { escalation_id: 2, ticket_id: "t-e0", priority: 2 },
    { escalation_id: 3, ticket_id: "t-e3", priority: 6 },
  ];

  it("cả hai có mặt, đúng nhóm, E0 trước E3, priority không giảm → không lỗi", () => {
    const r = checkQueueSnapshot({ groups, items, limit: 200, overflowShown: false, tickets: [E0, E3] });
    expect(r.problems).toStrictEqual([]);
    expect(r.shown).toStrictEqual(["t-e0", "t-e3"]);
  });

  it("priority giảm theo thứ tự hiển thị → lỗi; thứ tự dòng khác server → lỗi", () => {
    const swapped = [groups[0], groups[2], groups[1]];
    const r = checkQueueSnapshot({ groups: swapped, items, limit: 200, overflowShown: false, tickets: [] });
    expect(r.problems.some((p) => p.includes("đứng sau nhóm priority 6"))).toBe(true);
    expect(r.problems.some((p) => p.includes("khác thứ tự server"))).toBe(true);
  });

  it("E3 vắng khi đủ 200 ca + có cảnh báo → chỉ ghi chú; vắng khi dưới 200 → lỗi", () => {
    // 199 ca cũ hạng 1 + ca E0 mới hạng 2 = đủ 200; ca E3 mới (hạng 6) nằm ngoài.
    const old = Array.from({ length: 199 }, (_, i) => ({ escalation_id: 100 + i, ticket_id: `old-${i}`, priority: 1 }));
    const full = [...old, { escalation_id: 2, ticket_id: "t-e0", priority: 2 }];
    const fullGroups = [
      { priority: 1, name: "Rất cao", rows: old.map((i) => row(i.escalation_id, i.ticket_id, "E7")) },
      { priority: 2, name: "An ninh", rows: [row(2, "t-e0", "E0")] },
    ];
    const r = checkQueueSnapshot({ groups: fullGroups, items: full, limit: 200, overflowShown: true, tickets: [E0, E3] });
    expect(r.problems).toStrictEqual([]);
    expect(r.notes).toContain(`E3 (F2-2): ${OUTSIDE_NOTE}`);
    expect(r.shown).toStrictEqual(["t-e0"]);
    expect(r.problems.filter((p) => p.startsWith("E3"))).toStrictEqual([]);

    const short = checkQueueSnapshot({ groups: groups.slice(0, 2), items: items.slice(0, 2), limit: 200, overflowShown: false, tickets: [E3] });
    expect(short.problems.some((p) => p.includes("bug thật"))).toBe(true);
  });

  it("cảnh báo 'quá 200 ca' lệch với số ca → lỗi", () => {
    const r = checkQueueSnapshot({ groups, items, limit: 200, overflowShown: true, tickets: [] });
    expect(r.problems).toContain('3 ca mà cảnh báo "quá 200 ca" có hiện');
  });

  it("có mặt nhưng sai nhóm / sai mã → lỗi", () => {
    const wrong = [groups[0], { ...groups[1], priority: 4 }, groups[2]];
    const r = checkQueueSnapshot({ groups: wrong, items, limit: 200, overflowShown: false, tickets: [E0] });
    expect(r.problems.some((p) => p.includes("nhóm priority 4, server trả priority 2"))).toBe(true);
    const badCode = [groups[0], { ...groups[1], rows: [row(2, "t-e0", "E2")] }, groups[2]];
    expect(checkQueueSnapshot({ groups: badCode, items, limit: 200, overflowShown: false, tickets: [E0] }).problems).toContain(
      "E0 (F2-4): dòng mang mã E2",
    );
  });
});
