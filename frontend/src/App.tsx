import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ComponentType, useCallback, useRef } from "react";
import { createBrowserRouter, Navigate, Outlet, RouterProvider, useLocation } from "react-router";
import { AuthProvider } from "./auth/AuthProvider.tsx";
import { LoginPage } from "./auth/LoginPage.tsx";
import { CHAT_NAV, homePath, STAFF_NAV } from "./auth/permissions.ts";
import { RequireAuth, RequirePerm } from "./auth/RequireAuth.tsx";
import { useAuth, useMe } from "./auth/useAuth.ts";
import { FlashNotice } from "./components/FlashNotice.tsx";
import { MockDataBadge } from "./components/MockDataBadge.tsx";
import { useEnterOnChange } from "./components/motion.ts";
import { Sidebar } from "./components/Sidebar.tsx";
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

function Shell() {
  const me = useMe();
  const { signOut } = useAuth();
  const content = useRef<HTMLDivElement>(null);
  useEnterOnChange(content, useLocation().pathname); // đổi màn → nội dung trượt nhẹ vào, không dựng lại màn
  return (
    <div className="flex h-full">
      <Sidebar me={me} onSignOut={signOut} />
      <main className="min-w-0 grow overflow-y-auto">
        <div ref={content} className="motion-safe:animate-fade-in">
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
