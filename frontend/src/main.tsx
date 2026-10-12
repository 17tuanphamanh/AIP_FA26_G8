import "@fontsource/be-vietnam-pro/400.css";
import "@fontsource/be-vietnam-pro/600.css";
import "@fontsource/be-vietnam-pro/700.css";
import "./styles/tokens.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App.tsx";
import { MOCK_ENABLED } from "./mocks/flag.ts";

async function startMocking(): Promise<void> {
  // `import.meta.env.DEV` viết ngay tại đây (không chỉ qua cờ) để bản build loại hẳn nhánh này và
  // `import()` của msw, kể cả khi bundler không suy được hằng qua module khác (KH 4.3, fail-closed).
  if (import.meta.env.DEV && MOCK_ENABLED) {
    const { worker } = await import("./mocks/browser.ts");
    await worker.start({ onUnhandledFrame: "bypass" });
  }
}

const root = document.getElementById("root");
if (!root) throw new Error("Thiếu phần tử #root trong index.html");

void startMocking().then(() => {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
});
