import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { ApiError, errorMessage } from "../../api/errors.ts";
import {
  confirmBody,
  confirmTicket,
  getTicket,
  NOTE_MAX,
  replyTicket,
  sendMessage,
  TEXT_MAX,
  withBusyRetry,
} from "../../api/tickets.ts";
import type { Accepted, ParentReplyIn, TicketView } from "../../api/types.ts";
import { Composer } from "../../components/Composer.tsx";
import { Conversation } from "../../components/Conversation.tsx";
import { DigestMessage, type SendResult } from "../../components/DigestMessage.tsx";
import { normalizeConversation } from "../../components/messages.ts";
import { ProgressStrip } from "../../components/ProgressStrip.tsx";
import { ownEntry } from "../../lib/lookup.ts";
import { latestRound, PARENT_FINAL_NOTE, PARENT_PROCESSING, parentStatusLabel, progressItems } from "./multi.ts";
import { ProgressStepper } from "./ProgressStepper.tsx";
import { describeSendError, readNotices } from "./sendError.ts";
import { REDACTED_NOTE, sessionTickets, titleOf, useSessionTickets } from "./sessionTickets.ts";
import { FINAL_NOTE, POLL_PROCESSING_MS, pollDelay, statusLabel, statusTone, type Tone } from "./status.ts";
import { StreamingText } from "./StreamingText.tsx";
import { ThinkingBox } from "./ThinkingBox.tsx";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion.ts";
import { POLL_STREAMING_MS, reconcile, type StreamPhase, useTicketStream } from "./useTicketStream.ts";

const PILL: Record<Tone, { box: string; dot: string }> = {
  processing: { box: "bg-selected text-fpt-blue", dot: "bg-fpt-blue" },
  waiting: { box: "bg-orange-bg text-orange-ink", dot: "bg-fpt-orange" },
  done: { box: "bg-group text-ink", dot: "bg-done" },
  closed: { box: "bg-group text-ink-2", dot: "bg-ink-3" },
};

/** Route `/chat/:ticketId` — `key` theo id để trạng thái nội bộ (nháp, thông báo) không lẫn giữa hai ticket. */
export function ChatRoute() {
  const { ticketId = "" } = useParams();
  return <ChatPage key={ticketId} ticketId={ticketId} />;
}

const stopOn = (error: unknown) => error instanceof ApiError && (error.status === 403 || error.status === 404);
/** Thân ticket sai hình dạng (api/tickets.ts `parseTicketView`): đang polling → giữ bản hợp lệ cũ + câu lỗi dữ liệu (Q-fe-46). */
const badBody = (error: unknown): error is ApiError => error instanceof ApiError && error.code === "invalid_ticket_body";

/** Sau 202 backend xử lý ở NỀN: lượt GET ngay sau đó có thể vẫn là bước cũ (vẫn `confirm`/`clarify`). Giữ khoá thao tác
 *  tới khi ticket đổi thật (hoặc quá `SETTLE_MAX_MS`) — không để bấm lần hai rồi nhận 409 "đã sang bước khác". */
const SETTLE_MAX_MS = 30_000;
const progressOf = (v: TicketView) => `${v.status}|${v.waiting_for}|${v.final_state}|${v.conversation.length}`;

// B4EmpChat + B4EmpStates (đã tinh chỉnh KH 4.6): một cột 720 px; polling theo KH mục 5; ô nhập theo `waiting_for`.
// Ticket cha nhiều ý (D-31, T20b — có `children_progress`): dải tiến độ dưới header (không phải tin nhắn), tin tổng hợp
// round lớn nhất có form khi `waiting_for = "reply"`, nhãn cha theo 12b Q-fe-34. Ticket thường: không nhánh nào đổi.
export function ChatPage({ ticketId }: { ticketId: string }) {
  const location = useLocation();
  const queryClient = useQueryClient();
  const queryKey = useMemo(() => ["ticket", ticketId], [ticketId]);
  const settlingRef = useRef(false);
  const streamPhaseRef = useRef<StreamPhase>("off"); // SSE đang sống → polling chỉ còn là lưới an toàn thưa
  const query = useQuery({
    queryKey,
    queryFn: () => getTicket(ticketId),
    // 2 s đang xử lý · 10 s chờ người · dừng khi có final_state; 403/404 → dừng (không hỏi mãi một ticket không đọc được).
    // Vừa gửi xong (202) mà ticket chưa đổi bước → đang xử lý thật → 2 s, không theo `waiting_for` cũ.
    refetchInterval: (q) => {
      if (stopOn(q.state.error)) return false;
      const delay = pollDelay(q.state.data);
      if (delay !== false && streamPhaseRef.current === "streaming") return POLL_STREAMING_MS;
      return delay !== false && settlingRef.current ? POLL_PROCESSING_MS : delay;
    },
    retry: false,
  });
  const view = query.data;
  const messages = useMemo(() => normalizeConversation(view?.conversation), [view]);
  // Câu yêu cầu + tiêu đề: chỉ từ bộ nhớ phiên (12b Q-fe-18) — không lấy tin người dùng trong `conversation` (đó là
  // câu TRẢ LỜI khi hỏi thêm). Tải lại trang / mở bằng URL → không có → "Yêu cầu của bạn", không bong bóng.
  const mine = useSessionTickets().find((t) => t.ticket_id === ticketId);
  const title = titleOf(mine);

  useEffect(() => {
    if (view) sessionTickets.setTone(ticketId, statusTone(view));
  }, [view, ticketId]);

  const [notices, setNotices] = useState<string[]>(() => readNotices(location.state));
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [waitNote, setWaitNote] = useState<string | null>(null);
  // Bước của ticket lúc gửi thành công (202) — còn trùng với bước hiện tại thì coi như đang xử lý.
  const [sentAt, setSentAt] = useState<string | null>(null);
  useEffect(() => {
    if (sentAt === null) return;
    const timer = setTimeout(() => setSentAt(null), SETTLE_MAX_MS);
    return () => clearTimeout(timer);
  }, [sentAt]);
  const settling = sentAt !== null && view !== undefined && progressOf(view) === sentAt;
  useEffect(() => {
    settlingRef.current = settling;
  }, [settling]);

  // SSE tiến trình (chỉ khi server bật; 404/lỗi/ngắt quá 3 lần → tự về polling hiện có, không mất tin: tin chính thức luôn từ GET).
  const streamActive = view !== undefined && !view.final_state && (!view.waiting_for || settling);
  const stream = useTicketStream({ ticketId, active: streamActive, onSync: () => void queryClient.invalidateQueries({ queryKey }) });
  useEffect(() => {
    streamPhaseRef.current = stream.phase;
  }, [stream.phase]);
  const reducedMotion = usePrefersReducedMotion();
  const { official, streaming } = useMemo(() => reconcile(messages, stream.view.messages), [messages, stream.view.messages]);

  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView?.({ block: "end" });
  }, [messages.length, view?.waiting_for, view?.final_state]);

  /** Gửi + hiện `notices` + gọi lại ngay; lỗi trả về cho nơi gọi tự hiện (ô nhập dưới, hay từng khối tin tổng hợp). */
  async function submit(send: () => Promise<Accepted>): Promise<SendResult> {
    setSending(true);
    setFieldError(null);
    setError(null);
    try {
      const accepted = await withBusyRetry(send, (seconds) => setWaitNote(`Hệ thống đang bận — tự thử lại sau ${seconds} giây…`));
      setNotices(accepted.notices);
      setDraft("");
      if (view) setSentAt(progressOf(view));
      await queryClient.invalidateQueries({ queryKey }); // sau 202: gọi lại ngay một lần rồi theo nhịp
      return { ok: true };
    } catch (e) {
      // 409 (sự kiện muộn — ticket đã sang bước khác): tải lại ticket (câu báo do nơi gọi hiện).
      if (e instanceof ApiError && e.status === 409) void queryClient.invalidateQueries({ queryKey });
      return { ok: false, error: e };
    } finally {
      setSending(false);
      setWaitNote(null);
    }
  }

  async function run(send: () => Promise<Accepted>) {
    const result = await submit(send);
    if (result.ok) return;
    const described = describeSendError(result.error);
    setFieldError(described.field);
    setError(described.message);
  }

  const sendReply = (body: ParentReplyIn) => submit(() => replyTicket(ticketId, body));

  if (query.isPending) {
    return <p className="px-12 py-10 text-ink-2">Đang tải yêu cầu…</p>;
  }
  if (!view) {
    const e = query.error;
    return (
      <section className="px-12 py-10">
        <h1 className="text-heading">
          {e instanceof ApiError && e.status === 404 ? "Không tìm thấy yêu cầu này." : "Chưa tải được yêu cầu."}
        </h1>
        <p className="mt-2 text-ink-2">{e instanceof ApiError && e.status === 404 ? "" : errorMessage(e instanceof ApiError ? e : null)}</p>
        <Link to="/chat" className="mt-4 inline-block font-semibold text-fpt-blue">
          Tạo yêu cầu mới
        </Link>
      </section>
    );
  }

  const tone = statusTone(view);
  // Đang chờ backend nhận câu trả lời / xác nhận vừa gửi → không mở lại ô nhập, nút của bước cũ.
  const waiting = view.final_state || settling ? null : view.waiting_for;
  const composer = composerFor(view, waiting, settling);
  // Nhiều ý (D-31): form CHỈ cho tin tổng hợp round lớn nhất và CHỈ khi cha đang chờ trả lời; tin cũ chỉ đọc.
  const progress = progressItems(view.children_progress);
  const activeRound = waiting === "reply" ? latestRound(messages) : null;
  const pillLabel = progress ? parentStatusLabel(view, progress) : statusLabel(view.final_state ?? view.status);

  return (
    <div className="flex h-full min-w-0 flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-line px-6">
        <div className="flex min-w-0 grow flex-col">
          <h1 className="truncate text-body font-semibold">{title}</h1>
        </div>
        <span className="hidden text-label font-normal text-ink-2 lg:inline">
          Mã yêu cầu <span className="font-mono select-all" data-testid="ticket-id">{view.ticket_id}</span>
        </span>
        <span role="status" className={`inline-flex h-7 shrink-0 items-center gap-2 rounded-full px-3 text-secondary ${PILL[tone].box}`}>
          <span className={`size-1.75 rounded-full ${PILL[tone].dot}`} aria-hidden="true" />
          {pillLabel}
        </span>
      </header>
      {progress ? <ProgressStrip items={progress} /> : null}

      <div className="flex min-h-0 grow flex-col items-center overflow-y-auto px-6 pt-8 pb-6">
        <div className="flex w-full max-w-(--chat-width) grow flex-col gap-6">
          {notices.length > 0 ? (
            <div role="status" className="rounded-group bg-group px-4 py-3 text-secondary text-ink-2" data-testid="notices">
              {notices.map((notice) => (
                <p key={notice}>{notice}</p>
              ))}
            </div>
          ) : null}
          {mine ? (
            <p
              data-role="request"
              className={`max-w-130 self-end rounded-sheet bg-button-2 px-4.5 py-3 whitespace-pre-line ${
                mine.request === null ? "text-ink-2 italic" : ""
              }`}
            >
              {mine.request ?? REDACTED_NOTE}
            </p>
          ) : null}
          <Conversation
            messages={official}
            renderDigest={(digest) => (
              <DigestMessage
                digest={digest}
                newRequestLink
                form={digest.round === activeRound ? { sending, onSend: sendReply } : undefined}
              />
            )}
          />
          {streaming.map((message) => (
            <StreamingText key={message.id} message={message} reducedMotion={reducedMotion} />
          ))}
          {streamActive && (stream.view.steps.length > 0 || stream.view.log.length > 0) ? (
            <div data-testid="stream-progress" className="flex flex-col gap-3">
              <ProgressStepper steps={stream.view.steps} />
              <ThinkingBox log={stream.view.log} current={stream.view.steps.findLast((s) => s.state === "active")?.label} />
            </div>
          ) : null}
          <ActionPanel
            view={view}
            waiting={waiting}
            settling={settling}
            sending={sending}
            parent={progress !== null}
            replyShown={activeRound !== null}
            onConfirm={(ok) => void run(() => confirmTicket(ticketId, confirmBody(ok, ok ? undefined : draft)))}
          />
          {query.isError ? (
            <p role="status" className="text-secondary text-ink-2">
              {badBody(query.error) ? errorMessage(query.error) : "Tạm mất kết nối tới máy chủ — đang thử lại…"}
            </p>
          ) : null}
          <div ref={end} />
        </div>
      </div>

      {view.final_state ? null : (
        <div className="flex shrink-0 justify-center px-6 pb-6">
          <div className="flex w-full max-w-(--chat-width) flex-col gap-2">
            {waitNote || error ? (
              <p role={error ? "alert" : "status"} className={`px-5 text-secondary ${error ? "text-danger" : "text-ink-2"}`}>
                {error ?? waitNote}
              </p>
            ) : null}
            <Composer
              variant="chat"
              label={composer.label}
              placeholder={composer.placeholder}
              value={composer.enabled ? draft : ""}
              onChange={setDraft}
              onSubmit={waiting === "clarify" ? () => void run(() => sendMessage(ticketId, draft.trim())) : undefined}
              maxLength={waiting === "confirm" ? NOTE_MAX : TEXT_MAX}
              disabled={!composer.enabled}
              busy={sending}
              error={fieldError}
            />
          </div>
        </div>
      )}
    </div>
  );
}

const SENT_NOTE = "Đã gửi — đang xử lý";

function composerFor(view: TicketView, waiting: TicketView["waiting_for"], settling: boolean) {
  if (settling) return { enabled: false, label: "Tin nhắn", placeholder: `${SENT_NOTE}…` };
  if (waiting === "clarify") return { enabled: true, label: "Trả lời", placeholder: "Trả lời câu hỏi ở trên…" };
  if (waiting === "confirm") return { enabled: true, label: "Ghi chú nếu chưa ổn", placeholder: "Nhắn thêm nếu chưa ổn…" };
  if (waiting === "approval") return { enabled: false, label: "Tin nhắn", placeholder: "Đang chờ IT duyệt" };
  if (waiting === "reply") return { enabled: false, label: "Tin nhắn", placeholder: "Phản hồi trong khung ở trên" };
  return { enabled: false, label: "Tin nhắn", placeholder: `${statusLabel(view.status)}…` };
}

type ActionPanelProps = {
  view: TicketView;
  waiting: TicketView["waiting_for"];
  settling: boolean;
  sending: boolean;
  /** Ticket cha nhiều ý (có `children_progress`) — câu theo 12b Q-fe-34. */
  parent: boolean;
  /** Tin tổng hợp đang có form trả lời (waiting_for = reply) — khi đó form nằm trong hội thoại. */
  replyShown: boolean;
  onConfirm: (ok: boolean) => void;
};

function ActionPanel({ view, waiting, settling, sending, parent, replyShown, onConfirm }: ActionPanelProps) {
  if (view.final_state) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-sheet bg-group p-5" data-testid="final-note">
        <p>{parent ? PARENT_FINAL_NOTE : ownEntry(FINAL_NOTE, view.final_state, statusLabel(view.final_state))}</p>
        <Link to="/chat" className="font-semibold text-fpt-blue">
          Tạo yêu cầu mới
        </Link>
      </div>
    );
  }
  if (waiting === "confirm") {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded-sheet bg-group py-4 pr-4 pl-5">
        <span className="grow font-semibold">Vấn đề của bạn đã được giải quyết chưa?</span>
        <button
          type="button"
          disabled={sending}
          onClick={() => onConfirm(false)}
          className="h-11 rounded-full bg-white px-5 font-semibold disabled:opacity-60"
        >
          Chưa ổn
        </button>
        <button
          type="button"
          disabled={sending}
          onClick={() => onConfirm(true)}
          className="h-11 rounded-full bg-fpt-blue px-5.5 font-semibold text-white disabled:opacity-60"
        >
          Đã ổn
        </button>
      </div>
    );
  }
  if (waiting === "approval") {
    // TicketView chưa có `deadline` → chưa có đồng hồ đếm ngược (KH 1.3 #2).
    return (
      <div className="flex flex-col gap-2 rounded-sheet bg-orange-bg p-5">
        <span className="text-label text-orange-ink">Chờ IT duyệt</span>
        <p>Yêu cầu cần IT duyệt trước khi thực hiện.</p>
        <span className="text-label font-normal text-ink-2">Bạn có thể rời trang — kết quả sẽ hiện trong cuộc trò chuyện này.</span>
      </div>
    );
  }
  if (waiting === "reply") {
    // Form nằm trong tin tổng hợp. Không có tin nào đọc được (dữ liệu hỏng) → báo, không mở ô nhập nào.
    return replyShown ? null : (
      <p role="status" className="rounded-sheet bg-group p-5">
        Chưa hiện được nội dung cần phản hồi. Vui lòng tải lại trang.
      </p>
    );
  }
  if (waiting === "clarify") return null; // câu hỏi đã nằm trong hội thoại; ô trả lời ở dưới
  return (
    <p className="inline-flex items-center gap-2 text-secondary text-ink-2" data-testid="processing">
      <span className="size-1.75 animate-pulse rounded-full bg-fpt-blue" aria-hidden="true" />
      {settling ? SENT_NOTE : parent ? PARENT_PROCESSING : statusLabel(view.status)}… Bạn không cần làm gì.
    </p>
  );
}
