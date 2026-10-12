import { MOCK_ENABLED } from "../mocks/flag.ts";

// KH 4.3 #4: màn đang dùng dữ liệu giả mang nhãn ở góc, CHỈ ở dev — để demo không trình bày sai với GVHD.
// Bản build: `MOCK_ENABLED` là `false` → không render.
export function MockDataBadge() {
  if (!MOCK_ENABLED) return null;
  return (
    <div role="note" className="fixed top-3 right-3 z-50 rounded-full bg-orange-bg px-3 py-1 text-label text-orange-ink">
      Dữ liệu minh hoạ
    </div>
  );
}
