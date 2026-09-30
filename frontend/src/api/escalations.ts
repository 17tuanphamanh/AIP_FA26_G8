// Hàng đợi L2 (KH 1.1; backend/app/api/escalations.py) — route THẬT. Đóng ca (`/close`) CHƯA CÓ ở backend (Phase 7,
// T31): chỉ gọi được khi MSW bật (mocks/handlers/escalation-close.ts), không bao giờ gửi tới backend thật.
import { queryOptions } from "@tanstack/react-query";
import { MOCK_ENABLED } from "../mocks/flag.ts";
import { ApiError } from "./errors.ts";
import { api } from "./http.ts";
import type { EscalationCloseIn, EscalationQueueItem } from "./types.ts";

/** Trần `limit` của backend (`QUEUE_LIMIT_MAX`). Hàng đợi và chi tiết dùng chung MỘT truy vấn (cùng cache): chi tiết
 *  chưa có route riêng (`GET /api/escalations/{id}` — Phase 7) nên tìm ca trong hàng đợi theo `escalation_id`. */
export const QUEUE_LIMIT = 200;
export const QUEUE_REFRESH_MS = 15_000;
/** Ghi chú đóng: bắt buộc, sau khi cắt khoảng trắng 1…1000 ký tự. */
export const CLOSE_NOTE_MAX = 1000;
/** Đóng ca chỉ có khi MSW bật (dev + `VITE_API_MOCK=1`). Bản build: hằng `false`. */
export const CLOSE_AVAILABLE: boolean = MOCK_ENABLED;

export async function getEscalationQueue(limit = QUEUE_LIMIT): Promise<EscalationQueueItem[]> {
  const { data } = await api.request<unknown>(`/api/escalations/queue?limit=${limit}`);
  // Route trả list[dict] (chưa có response_model) — phần tử kiểm dạng lúc hiện (routes/l2/queue.ts), ở đây chỉ chặn
  // thân không phải mảng để màn không vỡ.
  if (!Array.isArray(data)) throw new ApiError(502, "invalid_queue_body");
  return data as EscalationQueueItem[];
}

const is403 = (error: unknown) => error instanceof ApiError && error.status === 403;

export const queueQuery = () =>
  queryOptions({
    queryKey: ["escalations", "queue", QUEUE_LIMIT] as const,
    queryFn: () => getEscalationQueue(QUEUE_LIMIT),
    retry: false,
  });

/** Nhịp tự tải lại của màn hàng đợi; 403 (mất quyền) → dừng. */
export const queueRefetchInterval = (error: unknown): number | false => (is403(error) ? false : QUEUE_REFRESH_MS);

export async function closeEscalation(id: number, body: EscalationCloseIn): Promise<void> {
  // Lớp chặn thứ hai (lớp đầu: nút gửi khoá). Route chưa tồn tại → tuyệt đối không gửi khi MSW tắt.
  if (!CLOSE_AVAILABLE) throw new Error("Đóng ca chưa có ở backend (Phase 7)");
  await api.request<unknown>(`/api/escalations/${id}/close`, { method: "POST", json: body });
}
