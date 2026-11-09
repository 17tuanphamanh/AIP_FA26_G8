import { useEffect, useRef, useState } from "react";
import { primeTick, useMachineNow } from "../../components/clock.ts";
import { clockOffset, EXPIRED_TEXT, FIVE_MIN_TEXT, formatRemaining, isUrgent, phaseOf, WAIT_LABEL } from "./approvalClock.ts";

type Props = {
  /** Hạn (ISO có múi giờ) — đã lọc ở `clockDeadline`. */
  deadline: string;
  /** `server_now` của lần nhận ticket gần nhất. */
  serverNow: string | null | undefined;
  /** Giờ máy lúc nhận ticket đó (TanStack `dataUpdatedAt`). */
  receivedAt: number;
  /** Hết hạn → gọi ĐÚNG MỘT lần cho mỗi lần gắn (nơi dùng `key={deadline}`; màn tải lại ticket, không tự kết luận gì). */
  onExpire: () => void;
};

// "Chờ IT duyệt · còn mm:ss" (ĐP 26/10 N-TB P5). Nhịp 1 giây dùng chung (components/clock.ts). Không mã luật, không
// trường nào khác của phiếu duyệt. Trình đọc màn hình: vùng `aria-live="polite"` riêng CHỈ đổi chữ khi chạm mốc 5 phút và
// khi hết hạn (không đọc từng giây); chữ đếm giây nằm trong `role="timer"` (mặc định không đọc).
export function ApprovalClock({ deadline, serverNow, receivedAt, onExpire }: Props) {
  // Nhịp chung còn giữ mốc CŨ khi chưa ai nghe (nhịp dừng lúc rời màn) → làm mới TRƯỚC lần vẽ đầu; không thì lần vẽ đầu có
  // thể "hết hạn giả" → gọi `onExpire` + chốt sai pha / mốc 20%.
  useState(primeTick);
  const machine = useMachineNow();
  const now = machine + clockOffset(serverNow, receivedAt);
  const deadlineMs = Date.parse(deadline);
  // Mốc tính 20% = giờ máy chủ lúc component gắn = lần đầu thấy `server_now` cho hạn này (nơi dùng đặt `key={deadline}`:
  // hạn đổi → gắn lại → mốc mới, pha gắn mới, được gọi `onExpire` lại một lần cho hạn mới).
  const [firstSeen] = useState(now);
  const remaining = deadlineMs - now;
  const phase = phaseOf(remaining);
  // Pha lúc gắn: không đọc lại câu đang có sẵn khi vừa mở trang — chỉ đọc khi pha ĐỔI.
  const [mountPhase] = useState(phase);
  const announce = phase === mountPhase ? "" : phase === "expired" ? EXPIRED_TEXT : phase === "five" ? FIVE_MIN_TEXT : "";

  const fired = useRef(false);
  useEffect(() => {
    if (phase !== "expired" || fired.current) return;
    fired.current = true;
    onExpire();
  }, [phase, onExpire]);

  const urgent = phase !== "expired" && isUrgent(remaining, deadlineMs, firstSeen);
  return (
    <div data-testid="approval-clock" className="flex flex-col gap-1">
      {phase === "expired" ? (
        <span className="text-label text-orange-ink">{EXPIRED_TEXT}</span>
      ) : (
        <span className="text-label text-orange-ink">
          {WAIT_LABEL} · còn{" "}
          <span role="timer" data-urgent={urgent ? "true" : undefined} className={`font-mono ${urgent ? "text-danger" : ""}`}>
            {formatRemaining(remaining)}
          </span>
        </span>
      )}
      <span className="sr-only" aria-live="polite" data-testid="approval-clock-live">
        {announce}
      </span>
    </div>
  );
}
