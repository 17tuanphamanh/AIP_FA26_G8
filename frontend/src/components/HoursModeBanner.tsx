import { useQuery } from "@tanstack/react-query";
import type { Client } from "../api/client.ts";
import { api } from "../api/http.ts";
import { HOURS_MODE_HINT, HOURS_MODE_LABEL, hoursModeQuery } from "../api/hoursMode.ts";

/**
 * D-97 (demo 14/11): dải báo ở MỌI màn khi Trưởng BP đang giả lập giờ hành chính — ai nhìn màn cũng biết kết quả đang theo giờ
 * giả, không nhầm với giờ thật. Theo giờ thật, chưa tải được, hay backend chưa có route → không hiện gì.
 */
export function HoursModeBanner({ client = api }: { client?: Client }) {
  const q = useQuery(hoursModeQuery(client));
  const view = q.data;
  if (view === undefined || view.mode === "real") return null;
  return (
    <p role="status" data-testid="hours-mode-banner" className="border-b border-line bg-group px-12 py-2.5 text-secondary max-lg:px-4">
      <span className="font-semibold">Chế độ demo: {HOURS_MODE_LABEL[view.mode]}.</span> {HOURS_MODE_HINT[view.mode]}
      {view.eval_mode ? " (Đang chạy đánh giá: hệ thống bỏ qua chế độ này.)" : null}
    </p>
  );
}
