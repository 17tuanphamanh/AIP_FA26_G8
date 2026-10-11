import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { ApiError } from "../api/errors.ts";
import { homePath } from "../auth/permissions.ts";
import { useMe } from "../auth/useAuth.ts";
import { sessionTickets } from "../routes/employee/sessionTickets.ts";
import { type FlashKey, flashState } from "./flash.ts";
import { ReauthDialog, type ReauthOutcome } from "./ReauthDialog.tsx";

const isReauth = (e: unknown) => e instanceof ApiError && e.status === 403 && e.code === "reauth_required";

type Options<T, R> = {
  /** Gửi thao tác (qua client dùng chung — CÙNG client với đăng nhập lại). */
  send: (body: T) => Promise<R>;
  onSuccess: (result: R) => void;
  /** Lỗi khác 403 `reauth_required`, HOẶC gửi lại sau khi đăng nhập vẫn bị đòi đăng nhập (không lặp). */
  onFailure: (error: unknown) => void;
  /** Đăng nhập lại thất bại / bị huỷ → thao tác KHÔNG được gửi lại. */
  onCancelled: () => void;
  /** Câu báo khi đăng nhập lại bằng NGƯỜI KHÁC (thao tác bị huỷ). */
  otherUserFlash: FlashKey;
};

/**
 * Thao tác cần đăng nhập ≤ 10 phút (P6 §4, P10 §3.2–3.3; 12b Q-fe-4, Q-fe-25; tách từ OverrideDialog — Q-fe-30):
 * 403 `reauth_required` → hộp đăng nhập lại (CÙNG luồng F1, gồm OTP) →
 * - `sub` token mới = người cũ → gửi lại ĐÚNG một lần body đang chờ;
 * - đăng nhập lại thất bại / huỷ → không gửi lại;
 * - người KHÁC → không gửi lại, xoá toàn bộ dữ liệu đã tải của người cũ, về trang đầu của người mới kèm câu báo huỷ.
 * `run` chặn bấm 2 lần trong cùng một nhịp (ref — state chưa kịp cập nhật). `dialog` ≠ null → màn gọi phải hiện nó.
 */
export function useReauthRetry<T, R>({ send, onSuccess, onFailure, onCancelled, otherUserFlash }: Options<T, R>) {
  const me = useMe();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [sending, setSending] = useState(false);
  const [reauth, setReauth] = useState(false);
  const inFlight = useRef(false);
  const waiting = useRef<{ body: T } | null>(null); // body chờ gửi lại sau khi đăng nhập lại

  async function attempt(body: T, retry: boolean) {
    if (inFlight.current) return;
    inFlight.current = true;
    setSending(true);
    try {
      onSuccess(await send(body));
    } catch (e) {
      if (isReauth(e) && !retry) {
        waiting.current = { body };
        setReauth(true);
      } else {
        onFailure(e); // gửi lại vẫn 403 reauth → báo, KHÔNG lặp
      }
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }

  function onReauth(outcome: ReauthOutcome) {
    const pending = waiting.current;
    waiting.current = null; // bỏ body chờ trong MỌI trường hợp — chỉ nhánh cùng người mới dùng
    setReauth(false);
    if (outcome.kind === "ok" && pending) {
      void attempt(pending.body, true);
    } else if (outcome.kind === "other_user") {
      // Phiên giờ là người khác (cookie đã bị ghi đè): không để lại dữ liệu nào của người cũ trên màn.
      queryClient.clear();
      sessionTickets.clear();
      void navigate(homePath(outcome.me), { replace: true, state: flashState(otherUserFlash) });
    } else {
      onCancelled();
    }
  }

  const dialog: ReactNode = reauth ? <ReauthDialog userId={me.user_id} onDone={onReauth} /> : null;
  return {
    /** Gửi lần đầu. Đang gửi (kể cả cùng nhịp bấm) → bỏ qua. */
    run: (body: T) => void attempt(body, false),
    sending,
    busy: () => inFlight.current,
    dialog,
  };
}
