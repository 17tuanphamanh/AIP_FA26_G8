import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useCallback } from "react";
import { createBrowserRouter, Navigate, Outlet, RouterProvider } from "react-router";
import { AuthProvider } from "./auth/AuthProvider.tsx";
import { LoginPage } from "./auth/LoginPage.tsx";
import { CHAT_NAV, homePath, STAFF_NAV } from "./auth/permissions.ts";
import { RequireAuth, RequirePerm } from "./auth/RequireAuth.tsx";
import { useAuth, useMe } from "./auth/useAuth.ts";
import { MockDataBadge } from "./components/MockDataBadge.tsx";
import { Sidebar } from "./components/Sidebar.tsx";
import { ChatHome } from "./routes/employee/ChatHome.tsx";
import { ChatRoute } from "./routes/employee/ChatPage.tsx";
import { sessionTickets } from "./routes/employee/sessionTickets.ts";
import { EscalationDetailRoute } from "./routes/l2/EscalationDetail.tsx";
import { EscalationQueue } from "./routes/l2/EscalationQueue.tsx";
import { NotFound } from "./routes/NotFound.tsx";
import { Pending } from "./routes/Pending.tsx";

const queryClient = new QueryClient();

function Shell() {
  const me = useMe();
  const { signOut } = useAuth();
  return (
    <div className="flex h-full">
      <Sidebar me={me} onSignOut={signOut} />
      <main className="min-w-0 grow overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

function Home() {
  return <Navigate to={homePath(useMe())} replace />;
}

// F2: chat nhân viên (API thật). F3: hàng đợi + chi tiết escalate (L1 + L2 — quyền escalation:handle). Màn của F4–F5
// chưa dựng: route + quyền có sẵn, nội dung là <Pending>. Chặng sau thay element, giữ RequirePerm.
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
        <EscalationDetailRoute />
      </RequirePerm>
    ),
  },
];

const featureRoutes = STAFF_NAV.filter((item) => item !== ESCALATIONS).map((item) => ({
  path: item.to.slice(1),
  element: (
    <RequirePerm perm={item.perm}>
      <Pending title={item.label} stage={item.stage} />
    </RequirePerm>
  ),
}));

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
      ...featureRoutes,
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
