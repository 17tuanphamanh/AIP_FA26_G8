import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Outlet, RouterProvider } from "react-router";
import { MockDataBadge } from "./components/MockDataBadge.tsx";
import { Sidebar } from "./components/Sidebar.tsx";

const queryClient = new QueryClient();

// F0: khung — thanh bên rỗng + vùng nội dung. Từ F1: đăng nhập, mục theo quyền, các màn theo vai trò.
// F0 nhãn "Dữ liệu minh hoạ" đặt ở khung để kiểm cờ mock; từ F3 chỉ màn dùng handler giả mới đặt.
function Shell() {
  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="min-w-0 grow">
        <Outlet />
      </main>
      <MockDataBadge />
    </div>
  );
}

function Placeholder() {
  return (
    <div className="px-12 py-10">
      <h1 className="text-title">ServiceDesk AI</h1>
      <p className="mt-2 text-ink-2">Khung F0 — các màn được thêm từ F1.</p>
    </div>
  );
}

const router = createBrowserRouter([{ element: <Shell />, children: [{ index: true, element: <Placeholder /> }] }]);

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  );
}
