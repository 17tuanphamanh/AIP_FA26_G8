// Điều hướng theo `permissions` từ /api/auth/me — KHÔNG so tên role (KH 4.1 #8, P10 §2). Ẩn mục chỉ để tiện;
// quyền thật do backend kiểm. Ma trận quyền: backend/app/auth/permissions.py (P6 §5.1).
import type { Me } from "../api/types.ts";

export type NavItem = { to: string; label: string; perm: string; stage: string };

// Khu IT, thứ tự theo Bản 4 (B4Sidebar). Chỉ mục CÓ màn trong kế hoạch F0–F6; mục Bản 4 không có màn nào
// (Tài liệu KB, Hiệu suất của tôi, Yêu cầu của tôi) bị ẩn (12b Q-fe-8). `stage`: chặng dựng màn đó.
export const STAFF_NAV: readonly NavItem[] = [
  { to: "/dashboard", label: "Tổng quan", perm: "dashboard:read:all", stage: "F5" },
  { to: "/alerts", label: "Cảnh báo", perm: "alert:read", stage: "F5" },
  { to: "/policy", label: "Chính sách", perm: "policy:read", stage: "F5" },
  { to: "/llm-status", label: "Trạng thái LLM", perm: "llm_status:read", stage: "I1" },
  { to: "/approvals", label: "Chờ tôi duyệt", perm: "approval:decide", stage: "F4" },
  { to: "/escalations", label: "Hàng đợi escalate", perm: "escalation:handle", stage: "F3" },
];

export const CHAT_NAV: NavItem = { to: "/chat", label: "Yêu cầu mới", perm: "ticket:create", stage: "F2" };

// Quyền nghiệp vụ: có bất kỳ quyền nào → khu IT; không có quyền nào → khu nhân viên (chat) (12b Q-fe-8).
const STAFF_PERMS = ["dashboard:read:all", "dashboard:read:own", "policy:read", "approval:decide", "escalation:handle"];

export const hasPerm = (me: Me, perm: string): boolean => me.permissions.includes(perm);
export const isStaff = (me: Me): boolean => STAFF_PERMS.some((perm) => hasPerm(me, perm));

/** Trang đầu (12b Q-fe-8): dashboard:read:all → approval:decide → escalation:handle → chat nhân viên. */
export function homePath(me: Me): string {
  for (const perm of ["dashboard:read:all", "approval:decide", "escalation:handle"]) {
    const item = STAFF_NAV.find((i) => i.perm === perm);
    if (item && hasPerm(me, perm)) return item.to;
  }
  return CHAT_NAV.to;
}

// Nhãn CHỈ để hiển thị (Q-fe-9: `me` chưa có tên) — không dùng để quyết quyền.
export const ROLE_LABEL: Record<Me["role"], string> = {
  employee: "Nhân viên",
  l1: "IT Helpdesk L1",
  l2: "Kỹ thuật viên L2",
  manager: "Trưởng bộ phận IT",
};
export const ROLE_HEADING: Record<Me["role"], string> = {
  employee: "",
  l1: "Người duyệt L1",
  l2: "Kỹ thuật viên L2",
  manager: "Trưởng bộ phận IT",
};
