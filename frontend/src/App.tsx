import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ComponentType, useCallback, useRef } from "react";
import { createBrowserRouter, Navigate, Outlet, RouterProvider, useLocation } from "react-router";
import { AuthProvider } from "./auth/AuthProvider.tsx";
import { LoginPage } from "./auth/LoginPage.tsx";
import { CHAT_NAV, homePath, STAFF_NAV } from "./auth/permissions.ts";
import { RequireAuth, RequirePerm } from "./auth/RequireAuth.tsx";
import { useAuth, useMe } from "./auth/useAuth.ts";
import { FlashNotice } from "./components/FlashNotice.tsx";
import { HoursModeBanner } from "./components/HoursModeBanner.tsx";
import { MockDataBadge } from "./components/MockDataBadge.tsx";
import { MobileNavBar, NavDrawer } from "./components/MobileNav.tsx";
import { useEnterOnChange } from "./components/motion.ts";
import { PlacedBell } from "./components/PlacedBell.tsx";
import { Sidebar } from "./components/Sidebar.tsx";
import { useMobileNav } from "./components/useMobileNav.ts";
import { ChatHome } from "./routes/employee/ChatHome.tsx";
import { ChatRoute } from "./routes/employee/ChatPage.tsx";
import { sessionTickets } from "./routes/employee/sessionTickets.ts";
import { ApprovalDetailRoute } from "./routes/l1/ApprovalDetail.tsx";
import { ApprovalQueue } from "./routes/l1/ApprovalQueue.tsx";
import { TicketOverrideRoute } from "./routes/l1/TicketOverride.tsx";
import { EscalationDetailRoute } from "./routes/l2/EscalationDetail.tsx";
import { EscalationQueue } from "./routes/l2/EscalationQueue.tsx";
import { Alerts } from "./routes/manager/Alerts.tsx";
import { DashboardPage } from "./routes/manager/DashboardPage.tsx";
import { LlmStatus } from "./routes/manager/LlmStatus.tsx";
import { PolicyEditor } from "./routes/manager/PolicyEditor.tsx";
import { ApprovalTraceLink, EscalationTraceLink, TicketTraceLink, TicketTraceRoute } from "./routes/shared/TicketTrace.tsx";
import { NotFound } from "./routes/NotFound.tsx";

const queryClient = new QueryClient();

// Vỏ nội dung `ref={content}` (hiệu ứng đổi màn, commit 0eb24d8) PHẢI có `h-full` + `overflow-y-auto`: vỏ này đứng giữa `main`
// và màn, không có chiều cao thì `h-full` / `min-h-full` của màn bên trong tính ra "auto" — chuỗi chiều cao đứt. Hậu quả
// (đã sửa): chat `/chat/:id` mất header và ô nhập dính đáy, phiếu duyệt `/approvals/:id` mất đầu phiếu và thanh quyết
// định dính đáy (cả hai trôi theo cuộn của cả trang), trang chủ chat `/chat` mất căn giữa dọc. Cuộn nằm ở vỏ (như `main`
// trước 0eb24d8) nên nút "Nhật ký quyết định" (`sticky`) vẫn dính suốt màn dài.
// Điện thoại (dưới 1024 px) — các lớp `max-lg:` chỉ chạy dưới 1024 px:
// - thanh bên thu vào nút menu (MobileNav.tsx), khung xếp dọc: thanh đầu → nội dung; vỏ nội dung là cột flex;
// - `wrap-anywhere`: chuỗi dài không dấu cách (mã ticket, UUID) ngắt dòng thay vì đẩy tràn ngang;
// - không cuộn ngang cả trang: bảng rộng tự cuộn ngang TRONG khung của nó.
/** Khung sau đăng nhập. Xuất ra để test dựng đúng khung thật (Shell.test.tsx). */
export function Shell() {
  const me = useMe();
  const { signOut } = useAuth();
  const content = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  useEnterOnChange(content, pathname); // đổi màn → nội dung trượt nhẹ vào, không dựng lại màn
  const { open, toggle, close, buttonRef, drawerRef } = useMobileNav(pathname);
  return (
    <div className="flex h-full max-lg:flex-col">
      <MobileNavBar open={open} onToggle={toggle} buttonRef={buttonRef}>
        <PlacedBell me={me} where="header" />
      </MobileNavBar>
      <NavDrawer open={open} onClose={close} drawerRef={drawerRef}>
        <Sidebar me={me} onSignOut={signOut} />
      </NavDrawer>
      <main inert={open} className="min-w-0 grow overflow-y-auto max-lg:min-h-0">
        <div ref={content} className="h-full overflow-y-auto motion-safe:animate-fade-in max-lg:flex max-lg:flex-col max-lg:overflow-x-hidden max-lg:wrap-anywhere">
          <HoursModeBanner />
          <FlashNotice />
          <Outlet />
        </div>
      </main>
    </div>
  );
}

function Home() {
  return <Navigate to={homePath(useMe())} replace />;
}

// F2: chat nhân viên (API thật). F3: hàng đợi + chi tiết escalate (L1 + L2 — quyền escalation:handle). F4: hộp thư duyệt,
// chi tiết phiếu (approval:decide — L1 + Trưởng BP IT; L2 không có → trang 403), xem ticket để ghi đè (decision:override).
// F5: Tổng quan (dashboard:read:all), Cảnh báo (alert:read), Chính sách (policy:read; sửa cần policy:edit) — Trưởng BP IT.
const chatRoutes = [
  {
    path: CHAT_NAV.to.slice(1),
    element: (
      <RequirePerm perm={CHAT_NAV.perm}>
        <ChatHome />
      </RequirePerm>
    ),
  },
  {
    path: `${CHAT_NAV.to.slice(1)}/:ticketId`,
    element: (
      <RequirePerm perm="ticket:read:own">
        <ChatRoute />
      </RequirePerm>
    ),
  },
];

const ESCALATIONS = STAFF_NAV.find((item) => item.to === "/escalations")!;
const escalationRoutes = [
  {
    path: ESCALATIONS.to.slice(1),
    element: (
      <RequirePerm perm={ESCALATIONS.perm}>
        <EscalationQueue />
      </RequirePerm>
    ),
  },
  {
    path: `${ESCALATIONS.to.slice(1)}/:escalationId`,
    element: (
      <RequirePerm perm={ESCALATIONS.perm}>
        <EscalationTraceLink />
        <EscalationDetailRoute />
      </RequirePerm>
    ),
  },
];

const ESCALATIONS_L3 = STAFF_NAV.find((item) => item.to === "/escalations-l3")!;
const escalationL3Routes = [
  {
    path: ESCALATIONS_L3.to.slice(1),
    element: (
      <RequirePerm perm={ESCALATIONS_L3.perm}>
        <EscalationQueue tier={3} />
      </RequirePerm>
    ),
  },
  {
    path: `${ESCALATIONS_L3.to.slice(1)}/:escalationId`,
    element: (
      <RequirePerm perm={ESCALATIONS_L3.perm}>
        <EscalationTraceLink tier={3} />
        <EscalationDetailRoute tier={3} />
      </RequirePerm>
    ),
  },
];

const APPROVALS = STAFF_NAV.find((item) => item.to === "/approvals")!;
const approvalRoutes = [
  {
    path: APPROVALS.to.slice(1),
    element: (
      <RequirePerm perm={APPROVALS.perm}>
        <ApprovalQueue />
      </RequirePerm>
    ),
  },
  {
    path: `${APPROVALS.to.slice(1)}/ticket/:ticketId`,
    element: (
      <RequirePerm perm="decision:override">
        <TicketTraceLink />
        <TicketOverrideRoute />
      </RequirePerm>
    ),
  },
  {
    path: `${APPROVALS.to.slice(1)}/:approvalId`,
    element: (
      <RequirePerm perm={APPROVALS.perm}>
        <ApprovalTraceLink />
        <ApprovalDetailRoute />
      </RequirePerm>
    ),
  },
];

// F5 (+ I1 Trạng thái LLM chỉ đọc) — Trưởng BP IT. Thiếu quyền → trang 403 TRƯỚC khi component mount → không gọi API nào (t64).
const MANAGER_SCREENS: Record<string, ComponentType> = {
  "/dashboard": DashboardPage,
  "/alerts": Alerts,
  "/policy": PolicyEditor,
  "/llm-status": LlmStatus,
};
const managerRoutes = STAFF_NAV.filter((item) => item.to in MANAGER_SCREENS).map((item) => {
  const Screen = MANAGER_SCREENS[item.to]!;
  return {
    path: item.to.slice(1),
    element: (
      <RequirePerm perm={item.perm}>
        <Screen />
      </RequirePerm>
    ),
  };
});

// Nhật ký quyết định (chỉ đọc) — L1, L2, Trưởng BP IT (`ticket:read:any`); nút mở nằm cạnh 3 màn trên.
const traceRoutes = [
  {
    path: "trace/:ticketId",
    element: (
      <RequirePerm perm="ticket:read:any">
        <TicketTraceRoute />
      </RequirePerm>
    ),
  },
];

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  {
    element: (
      <RequireAuth>
        <Shell />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Home /> },
      ...chatRoutes,
      ...escalationRoutes,
      ...escalationL3Routes,
      ...approvalRoutes,
      ...managerRoutes,
      ...traceRoutes,
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export function App() {
  // Hết phiên / đăng xuất → xoá dữ liệu đã tải và lịch sử "Gần đây" của người cũ.
  const clearCache = useCallback(() => {
    queryClient.clear();
    sessionTickets.clear();
  }, []);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider onSignedOut={clearCache}>
        <RouterProvider router={router} />
      </AuthProvider>
      {/* Nhãn toàn cục khi bật mock (KH 4.3 #4; verify F0-2 kiểm). Từ F3 phần dùng handler giả còn ghi "minh hoạ" tại chỗ
          (form đóng escalation) để biết đúng phần nào là giả. */}
      <MockDataBadge />
    </QueryClientProvider>
  );
}
