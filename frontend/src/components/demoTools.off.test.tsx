// Bản build thường (không VITE_DEMO_TOOLS=1): không có lối vào hệ thống giả lập nào — hệ thống thật không có trang giả lập.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import type { Me } from "../api/types.ts";
import { Sidebar } from "./Sidebar.tsx";

vi.mock("../lib/demoTools.ts", async (orig) => ({ ...(await orig<typeof import("../lib/demoTools.ts")>()), DEMO_TOOLS: false }));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("DEMO_TOOLS tắt → không có nhóm demo, không có link quản trị AD (kể cả Trưởng BP)", () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  const mgr: Me = { user_id: "it_mgr01", role: "manager", permissions: ["policy:read", "policy:edit", "dashboard:read:all", "alert:read"] };
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Sidebar me={mgr} onSignOut={async () => true} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  expect(screen.queryByTestId("demo-tools")).toBeNull();
  expect(screen.queryByTestId("nav-ad-admin")).toBeNull();
});
