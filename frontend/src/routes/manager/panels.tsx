import { ApiError, errorMessage } from "../../api/errors.ts";
import { MOCK_ENABLED } from "../../mocks/flag.ts";
import { MONITOR_DOWN_TEXT } from "./metrics.ts";

/** Route chưa có ở backend (404 "Not Found" của Starlette) → nói thật là chưa có, KHÔNG khối lỗi đỏ (F5 P5). */
export function MissingPanel({ testId, title, text }: { testId: string; title: string; text: string }) {
  return (
    <div data-testid={testId} className="flex flex-col gap-1 rounded-group bg-group px-5 py-4">
      <h2 className="text-heading">{title}</h2>
      <p className="text-ink-2">{text}</p>
    </div>
  );
}

/**
 * Lỗi tải số liệu. 503 `monitor_unavailable` (fail-closed của M9) → "Số liệu tạm thời không có". `invalid`: câu riêng cho
 * 422 (Tổng quan: cửa sổ from/to bị từ chối — không có ô nào để "đánh dấu" như câu 422 chung). Nơi gọi KHÔNG được hiện
 * kèm dữ liệu cũ (KH mục 5) — component này chỉ có chữ.
 */
export function LoadError({ error, what, invalid }: { error: unknown; what: string; invalid?: string }) {
  const api = error instanceof ApiError ? error : null;
  const down = api?.status === 503;
  const detail = down
    ? "Kết nối tới dữ liệu giám sát đang gián đoạn — thử tải lại sau."
    : api?.status === 422 && invalid
      ? invalid
      : errorMessage(api);
  return (
    <div role="alert" data-testid="load-error" className="flex flex-col gap-1 rounded-group bg-danger-bg px-5 py-4 text-danger-ink">
      <p className="font-semibold">{down ? MONITOR_DOWN_TEXT : `Chưa tải được ${what}`}</p>
      <p className="text-secondary">{detail}</p>
    </div>
  );
}

/** Nhãn tại chỗ cho phần đang dùng dữ liệu giả (KH 4.3 #4) — chỉ khi dev:mock. */
export function MockNote({ text }: { text: string }) {
  if (!MOCK_ENABLED) return null;
  return <span className="rounded-full bg-orange-bg px-3 py-1 text-label text-orange-ink">Dữ liệu minh hoạ — {text}</span>;
}
