import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ackAlert } from "../../api/alerts.ts";
import { ApiError, errorMessage, routeMissing } from "../../api/errors.ts";
import type { AlertList } from "../../api/types.ts";
import { ACK_CONFLICT_TEXT, ACK_DONE_TEXT, ACK_GONE_TEXT, ACK_UNREADABLE_TEXT, ALERTS_MISSING_TITLE } from "./metrics.ts";

export type AckNotice = { tone: "ok" | "error"; text: string };

/**
 * "Đã xem" (P9 §7 — thao tác duy nhất với cảnh báo; F5 P6): KHÔNG optimistic — cảnh báo chỉ rời danh sách "Đang mở"
 * SAU khi server trả 200 ĐỌC ĐƯỢC (cảnh báo đã ack, đúng id). 200 mà thân không đọc được → không sửa cache, không báo
 * thành công, tải lại. 409 (đã có người xác nhận — không đọc `acked_by` của thân lỗi) / 404 (không còn) → câu riêng + tải
 * lại danh sách. Chặn bấm 2 lần theo id (ref — state chưa kịp cập nhật trong cùng một nhịp).
 */
export function useAlertAck() {
  const queryClient = useQueryClient();
  const inFlight = useRef(new Set<number>());
  const [pending, setPending] = useState<ReadonlySet<number>>(new Set());
  const [notice, setNotice] = useState<AckNotice | null>(null);

  const mark = (id: number, on: boolean) =>
    setPending((old) => {
      const next = new Set(old);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  const reload = () => void queryClient.invalidateQueries({ queryKey: ["alerts"] });

  async function ack(id: number) {
    if (inFlight.current.has(id)) return;
    inFlight.current.add(id);
    mark(id, true);
    setNotice(null);
    try {
      const acked = await ackAlert(id);
      if (acked === null) {
        setNotice({ tone: "error", text: ACK_UNREADABLE_TEXT });
        reload();
        return;
      }
      // Server đã ghi nhận → mới gỡ khỏi "Đang mở" và cập nhật "Tất cả" bằng bản server trả (giữ `truncated`). CHỈ sửa bộ
      // lọc đang có dữ liệu tốt: `setQueryData` lên query đang LỖI sẽ biến nó thành success với danh sách cũ trước lỗi (KH
      // mục 5 — không hiện số cũ) → bộ lọc đó để `reload()` đánh dấu cũ, mở ra là tải lại.
      const edit = (filter: "open" | "all", next: (items: AlertList["items"]) => AlertList["items"]) => {
        if (queryClient.getQueryState(["alerts", filter])?.status !== "success") return;
        queryClient.setQueryData<AlertList>(["alerts", filter], (old) => old && { ...old, items: next(old.items) });
      };
      edit("open", (items) => items.filter((a) => a.alert_id !== id));
      edit("all", (items) => items.map((a) => (a.alert_id === id ? acked : a)));
      setNotice({ tone: "ok", text: ACK_DONE_TEXT });
      reload();
    } catch (e) {
      if (routeMissing(e)) setNotice({ tone: "error", text: `${ALERTS_MISSING_TITLE} — máy chủ chưa có chức năng này.` });
      else if (e instanceof ApiError && e.status === 409) setNotice({ tone: "error", text: ACK_CONFLICT_TEXT });
      else if (e instanceof ApiError && e.status === 404) setNotice({ tone: "error", text: ACK_GONE_TEXT });
      else setNotice({ tone: "error", text: errorMessage(e instanceof ApiError ? e : null) });
      if (e instanceof ApiError && (e.status === 409 || e.status === 404) && !routeMissing(e)) reload();
    } finally {
      inFlight.current.delete(id);
      mark(id, false);
    }
  }

  return { ack: (id: number) => void ack(id), pending, notice };
}
