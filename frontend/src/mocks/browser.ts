import { setupWorker } from "msw/browser";
import { handlers } from "./handlers/index.ts";

// Chỉ được nạp bằng `import()` động trong nhánh dev của `main.tsx` — không import tĩnh ở đâu khác.
export const worker = setupWorker(...handlers);
