import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router";
import { ApiError, PURGED_TEXT, errorMessage, isPurged } from "../../api/errors.ts";
import {
  confirmBody,
  confirmTicket,
  createTicket,
  getTicket,
  NOTE_MAX,
  replyTicket,
  REQUEST_TEXT_MAX,
  sendMessage,
  TEXT_MAX,
  withBusyRetry,
} from "../../api/tickets.ts";
import type { Accepted, ParentReplyIn, TicketView } from "../../api/types.ts";
import { Composer } from "../../components/Composer.tsx";
import logoUrl from "../../assets/logo.svg";
import { Conversation, USER_BUBBLE } from "../../components/Conversation.tsx";
import { DigestMessage, type SendResult } from "../../components/DigestMessage.tsx";
import { normalizeConversation } from "../../components/messages.ts";
import { ProgressStrip } from "../../components/ProgressStrip.tsx";
import { ApprovalClock } from "./ApprovalClock.tsx";
import { clockDeadline } from "./approvalClock.ts";
import { latestRound, PARENT_FINAL_NOTE, PARENT_PROCESSING, parentStatusLabel, progressItems } from "./multi.ts";
import { ProgressStepper } from "./ProgressStepper.tsx";
import { describeSendError, readNotices } from "./sendError.ts";
import { REDACTED_NOTE, sessionTickets, titleOf, useSessionTickets } from "./sessionTickets.ts";
import { POLL_PROCESSING_MS, finalNoteOf, handlingText, pollDelay, statusLabel, statusTone, type Tone } from "./status.ts";
import { StreamingText } from "./StreamingText.tsx";
import { usePacedMessages } from "./usePacedMessages.ts";
import { ThinkingBox } from "./ThinkingBox.tsx";
import { usePrefersReducedMotion } from "./usePrefersReducedMotion.ts";
import { displayText, POLL_STREAMING_MS, reconcile, type StreamPhase, useTicketStream } from "./useTicketStream.ts";

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

const stopOn = (error: unknown) => error instanceof ApiError && (error.status === 403 || error.status === 404 || isPurged(error));
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
  const navigate = useNavigate();
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
  // Đồng hồ chờ duyệt hết hạn → tải lại ticket NGAY một lần (ApprovalClock gọi đúng một lần mỗi hạn); kết luận theo ticket.
  // Ghi lại hạn đã quá → ô nhập đổi "Đang chuyển kỹ thuật viên" tới khi ticket tải lại đổi bước / đổi hạn (ĐP soát 23d0f6a #5).
  const [expiredDeadline, setExpiredDeadline] = useState<string | null>(null);
  const onClockExpire = useCallback(
    (expired: string) => {
      setExpiredDeadline(expired);
      void queryClient.refetchQueries({ queryKey, exact: true });
    },
    [queryClient, queryKey],
  );
  const messages = useMemo(() => normalizeConversation(view?.conversation), [view]);
  // Câu yêu cầu + tiêu đề (12b Q-fe-18): có bộ nhớ phiên (`mine`) → dùng nó, như cũ. Không có (tải lại trang / mở bằng
  // URL / mở từ danh sách) → `request_text` của ticket (câu ĐÃ CHE từ backend, Nợ API #8); null/thiếu → "Yêu cầu của
  // bạn", không bong bóng. Không lấy tin người dùng trong `conversation` (đó là câu TRẢ LỜI khi hỏi thêm).
  const mine = useSessionTickets().find((t) => t.ticket_id === ticketId);
  const savedRequest = mine ? null : view?.request_text?.trim() ? view.request_text : null;
  // Backend cắt ở REQUEST_TEXT_MAX điểm mã, không thêm dấu → đủ độ dài thì bong bóng thêm "…" (chỉ chỗ hiện; tiêu đề tự cắt riêng).
  const savedBubble = savedRequest !== null && Array.from(savedRequest).length >= REQUEST_TEXT_MAX ? `${savedRequest}…` : savedRequest;
  const title = titleOf(mine ?? (savedRequest === null ? undefined : { request: savedRequest }));

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
  const paced = usePacedMessages(stream.view.messages, reducedMotion); // nhịp chữ chạy phía màn; chỉ đổi sang tin chính thức khi đã hiện hết
  const { official, streaming } = useMemo(() => reconcile(messages, paced), [messages, paced]);
  // Tin vừa chạy chữ xong → bản chính thức hiện tại chỗ, không chạy hiệu ứng vào lần nữa (không nháy).
  const streamedTexts = useMemo(
    () => new Set(stream.view.messages.filter((m) => m.ended).map((m) => displayText(m.text))),
    [stream.view.messages],
  );
  const progressShown = streamActive && (stream.view.steps.length > 0 || stream.view.log.length > 0);
  const answering = streaming.some((m) => m.text.length > 0);

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

  /** Q13b (D-79): "Hỏi tiếp" từ ticket ĐÃ kết thúc → ticket MỚI kèm `follows_ticket_id` (backend kiểm chủ) → sang trang ticket mới. */
  async function sendFollowUp() {
    const value = draft.trim();
    if (!value || sending) return;
    setSending(true);
    setFieldError(null);
    setError(null);
    try {
      const accepted = await withBusyRetry(
        () => createTicket(value, ticketId),
        (seconds) => setWaitNote(`Hệ thống đang bận — tự thử lại sau ${seconds} giây…`),
      );
      sessionTickets.add(accepted.ticket_id, value, accepted.notices);
      setDraft("");
      navigate(`/chat/${encodeURIComponent(accepted.ticket_id)}`, { state: { notices: accepted.notices } });
    } catch (e) {
      const described = describeSendError(e);
      setFieldError(described.field);
      setError(described.message);
    } finally {
      setSending(false);
      setWaitNote(null);
    }
  }

  if (query.isPending) {
    return <p className="px-12 py-10 text-ink-2 motion-safe:animate-pulse max-lg:px-4 max-lg:py-6">Đang tải yêu cầu…</p>;
  }
  if (!view && isPurged(query.error)) {
    // M2 bn-a: ticket đã kết thúc, hội thoại đã dọn theo hạn giữ (410) — câu trung tính, không phải lỗi, không hỏi lại.
    return (
      <section className="px-12 py-10 max-lg:px-4 max-lg:py-6">
        <h1 className="text-heading">{PURGED_TEXT}</h1>
        <Link to="/chat" className="mt-4 inline-block font-semibold text-fpt-blue max-lg:inline-flex max-lg:min-h-11 max-lg:items-center">
          Tạo yêu cầu mới
        </Link>
      </section>
    );
  }
  if (!view) {
    const e = query.error;
    return (
      <section className="px-12 py-10 max-lg:px-4 max-lg:py-6">
        <h1 className="text-heading">
          {e instanceof ApiError && e.status === 404 ? "Không tìm thấy yêu cầu này." : "Chưa tải được yêu cầu."}
        </h1>
        <p className="mt-2 text-ink-2">{e instanceof ApiError && e.status === 404 ? "" : errorMessage(e instanceof ApiError ? e : null)}</p>
        <Link to="/chat" className="mt-4 inline-block font-semibold text-fpt-blue max-lg:inline-flex max-lg:min-h-11 max-lg:items-center">
          Tạo yêu cầu mới
        </Link>
      </section>
    );
  }

  const tone = statusTone(view);
  // Đang chờ backend nhận câu trả lời / xác nhận vừa gửi → không mở lại ô nhập, nút của bước cũ.
  const waiting = view.final_state || settling ? null : view.waiting_for;
  // Nhiều ý (D-31): form CHỈ cho tin tổng hợp round lớn nhất và CHỈ khi cha đang chờ trả lời; tin cũ chỉ đọc.
  const progress = progressItems(view.children_progress);
  const activeRound = waiting === "reply" ? latestRound(messages) : null;
  const pillLabel = progress ? parentStatusLabel(view, progress) : statusLabel(view.final_state ?? view.status);
  // N-TB P5 (sửa ĐP 27/10 00:05): "Chờ IT duyệt · còn mm:ss" CHỈ khi waiting_for = approval; độ lệch từ `server_now` đo lúc
  // nhận (`dataUpdatedAt`); ticket cha: `deadline` của cha như server trả.
  const deadline = clockDeadline(view, waiting);
  const clock = deadline ? (
    <ApprovalClock
      key={deadline}
      deadline={deadline}
      serverNow={view.server_now}
      receivedAt={query.dataUpdatedAt}
      onExpire={() => onClockExpire(deadline)}
    />
  ) : null;
  const composer = composerFor(view, waiting, settling, deadline !== null && deadline === expiredDeadline, progress !== null);
  const followUp = Boolean(view.final_state) && view.can_follow_up === true; // Q13b: ô "Hỏi tiếp" trên ticket đã kết thúc

  return (
    <div className="flex h-full min-w-0 flex-col">
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-line bg-white/90 px-6 backdrop-blur max-lg:h-14 max-lg:px-4">
        <div className="flex min-w-0 grow flex-col">
          <h1 className="truncate text-body font-semibold">{title}</h1>
          <span className="hidden truncate text-label font-normal text-ink-2 lg:inline">
            Mã yêu cầu <span className="font-mono select-all" data-testid="ticket-id">{view.ticket_id}</span>
          </span>
        </div>
        <span role="status" className={`inline-flex h-8 shrink-0 items-center gap-2 rounded-full px-3.5 text-secondary font-semibold ${PILL[tone].box}`}>
          <span className={`size-2 rounded-full ${PILL[tone].dot} ${tone === "processing" ? "motion-safe:animate-pulse" : ""}`} aria-hidden="true" />
          {pillLabel}
        </span>
      </header>
      {progress ? <ProgressStrip items={progress} /> : null}

      <div className="flex min-h-0 grow flex-col items-center overflow-y-auto px-6 pt-10 pb-8 max-lg:px-4 max-lg:pt-6 max-lg:pb-6">
        <div className="flex w-full max-w-(--chat-width) grow flex-col gap-8">
          {notices.length > 0 ? (
            <div role="status" className="rounded-group border border-line bg-group px-4 py-3 text-secondary text-ink-2 motion-safe:animate-drop-in" data-testid="notices">
              {notices.map((notice) => (
                <p key={notice}>{notice}</p>
              ))}
            </div>
          ) : null}
          {mine ? (
            <p
              data-role="request"
              className={`${USER_BUBBLE} motion-safe:animate-rise-in ${mine.request === null ? "text-ink-2 italic" : ""}`}
            >
              {mine.request ?? REDACTED_NOTE}
            </p>
          ) : savedRequest !== null ? (
            <p data-role="request" className={USER_BUBBLE}>
              {savedBubble}
            </p>
          ) : null}
          <Conversation
            messages={official}
            quiet={(m) => m.role === "assistant" && streamedTexts.has(m.text)}
            renderDigest={(digest) => (
              <DigestMessage
                digest={digest}
                newRequestLink
                form={digest.round === activeRound ? { sending, onSend: sendReply } : undefined}
              />
            )}
          />
          {/* Lượt trả lời đang chạy (TA 14/11): MỘT ảnh đại diện (vòng quay khi đang xử lý) — khung tiến trình ở trên, chữ chạy ở dưới.
              Chữ bắt đầu chạy → danh sách bước thu lại, chỉ còn dòng đầu khung. */}
          {progressShown || streaming.length > 0 ? (
            <div className="flex items-start gap-3" data-testid="assistant-turn">
              <TurnAvatar busy={progressShown} />
              <div className="flex min-w-0 grow flex-col gap-4">
                {progressShown ? (
                  <div
                    data-testid="stream-progress"
                    className="overflow-hidden rounded-group border border-line bg-white shadow-input motion-safe:animate-pop-in"
                  >
                    <ThinkingBox log={stream.view.log} current={stream.view.steps.findLast((s) => s.state === "active")?.label} />
                    <ProgressStepper steps={stream.view.steps} collapsed={answering} />
                  </div>
                ) : null}
                {streaming.map((message) => (
                  <StreamingText key={message.id} message={message} reducedMotion={reducedMotion} bare />
                ))}
              </div>
            </div>
          ) : null}
          <ActionPanel
            view={view}
            clock={clock}
            waiting={waiting}
            settling={settling}
            sending={sending}
            parent={progress !== null}
            replyShown={activeRound !== null}
            streamShown={progressShown || streaming.length > 0}
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

      {view.final_state && !followUp ? null : (
        <div className="relative flex shrink-0 justify-center bg-white px-6 pb-4 max-lg:px-3 max-lg:pb-[calc(0.75rem+env(safe-area-inset-bottom))]">
          <span aria-hidden="true" className="pointer-events-none absolute inset-x-0 -top-8 h-8 bg-linear-to-t from-white to-white/0" />
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
              onSubmit={
                waiting === "clarify" ? () => void run(() => sendMessage(ticketId, draft.trim())) : followUp ? () => void sendFollowUp() : undefined
              }
              maxLength={waiting === "confirm" ? NOTE_MAX : TEXT_MAX}
              disabled={!composer.enabled}
              busy={sending}
              error={fieldError}
            />
            <p className="text-center text-label font-normal text-ink-2">Trợ lý AI có thể nhầm — hãy đọc kỹ hướng dẫn trước khi làm theo.</p>
          </div>
        </div>
      )}
    </div>
  );
}

const SENT_NOTE = "Đã gửi — đang xử lý";
export const FOLLOW_UP_LABEL = "Hỏi tiếp về yêu cầu này";

/** `approvalExpired`: đồng hồ duyệt đang ở pha quá hạn (chưa tải lại được trạng thái mới) → câu "đang chuyển". `parent`: ticket cha
 *  chưa đóng mà không chờ gì của người dùng (chờ các ý — D-77) → câu của cha, không nhãn trạng thái ticket thường (Q6 c2). */
function composerFor(view: TicketView, waiting: TicketView["waiting_for"], settling: boolean, approvalExpired = false, parent = false) {
  if (settling) return { enabled: false, label: "Tin nhắn", placeholder: `${SENT_NOTE}…` };
  // Q13b (D-79): ticket đã kết thúc mà backend cho hỏi tiếp → ô nhập mở, gửi = tạo ticket MỚI (mang gợi ý loại việc, không mang chữ cũ).
  if (view.final_state && view.can_follow_up === true) {
    return { enabled: true, label: FOLLOW_UP_LABEL, placeholder: "Hỏi tiếp, ví dụ: vẫn chưa được, hoặc hỏi thêm về việc này…" };
  }
  if (waiting === "clarify") return { enabled: true, label: "Trả lời", placeholder: "Trả lời câu hỏi ở trên…" };
  // Q13a (D-78): ghi chú gửi kèm "Chưa ổn" sau câu trả lời KB mở vòng hỏi tiếp (tối đa 2 vòng) — gợi ý người dùng mô tả đã thử gì.
  if (waiting === "confirm") return { enabled: true, label: "Ghi chú nếu chưa ổn", placeholder: "Chưa ổn? Ghi bạn đã thử gì, lỗi còn thế nào rồi bấm Chưa ổn…" };
  if (waiting === "approval") return { enabled: false, label: "Tin nhắn", placeholder: approvalExpired ? "Đang chuyển kỹ thuật viên" : "Đang chờ IT duyệt" };
  if (waiting === "reply") return { enabled: false, label: "Tin nhắn", placeholder: "Phản hồi trong khung ở trên" };
  return { enabled: false, label: "Tin nhắn", placeholder: `${parent && !view.final_state ? PARENT_PROCESSING : statusLabel(view.status)}…` };
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
  /** Đồng hồ chờ duyệt (null = không có hạn → chỉ nhãn tĩnh). */
  clock: ReactNode;
  /** Khung tiến trình / chữ chạy đang hiện → không vẽ thêm dòng "đang xử lý" (một chỉ báo là đủ). */
  streamShown: boolean;
  onConfirm: (ok: boolean) => void;
};

/** Ảnh đại diện trợ lý của lượt đang chạy: `busy` → vòng quay mảnh quanh logo (tắt khi giảm chuyển động). */
function TurnAvatar({ busy }: { busy: boolean }) {
  return (
    <span className="relative mt-0.5 size-7 shrink-0">
      {busy ? <span aria-hidden="true" className="chat-turn-ring" /> : null}
      <img src={logoUrl} alt="" width={28} height={28} className="relative size-7 rounded-lg" />
    </span>
  );
}

function ActionPanel({ view, waiting, settling, sending, parent, replyShown, clock, streamShown, onConfirm }: ActionPanelProps) {
  if (view.final_state) {
    return (
      <div className="flex flex-col items-start gap-3 rounded-group border border-line bg-group p-5 motion-safe:animate-rise-in" data-testid="final-note">
        <p>{parent ? PARENT_FINAL_NOTE : finalNoteOf(view)}</p>
        {parent && view.handling?.length ? (
          <ul data-testid="handling-lines" className="flex list-disc flex-col gap-1 pl-5 text-secondary">
            {view.handling.map((h) => (
              <li key={`${h.ticket_id}|${h.updated_at}`}>{handlingText(h)}</li>
            ))}
          </ul>
        ) : null}
        <Link
          to="/chat"
          className="inline-flex h-10 items-center gap-2 rounded-full border border-line bg-white px-4 text-secondary font-semibold text-fpt-blue hover:bg-selected max-lg:min-h-11"
        >
          <span aria-hidden="true">+</span>
          Tạo yêu cầu mới
        </Link>
      </div>
    );
  }
  if (waiting === "confirm") {
    return (
      <div className="ml-10 flex flex-wrap items-center gap-3 rounded-group border border-line bg-white py-4 pr-4 pl-5 motion-safe:animate-rise-in">
        <span className="grow font-semibold">Vấn đề của bạn đã được giải quyết chưa?</span>
        <button
          type="button"
          disabled={sending}
          onClick={() => onConfirm(false)}
          className="h-11 rounded-full border border-line bg-white px-5 font-semibold hover:bg-group disabled:opacity-60"
        >
          Chưa ổn
        </button>
        <button
          type="button"
          disabled={sending}
          onClick={() => onConfirm(true)}
          className="h-11 rounded-full bg-fpt-blue px-5.5 font-semibold text-white hover:bg-fpt-blue/90 disabled:opacity-60"
        >
          Đã ổn
        </button>
      </div>
    );
  }
  if (waiting === "approval") {
    // Có hạn → đồng hồ (N-TB P5); không có hạn / hạn hỏng → nhãn tĩnh như cũ.
    return (
      <div className="ml-10 flex items-start rounded-group border-l-3 border-l-fpt-orange bg-orange-bg py-4 pr-5 pl-4.5 motion-safe:animate-rise-in">
        <div className="flex min-w-0 flex-col gap-1.5">
          {clock ?? <span className="text-label text-orange-ink">Chờ IT duyệt</span>}
          <p>Yêu cầu cần IT duyệt trước khi thực hiện.</p>
          <span className="text-label font-normal text-ink-2">Bạn có thể rời trang — kết quả sẽ hiện trong cuộc trò chuyện này.</span>
        </div>
      </div>
    );
  }
  if (waiting === "reply") {
    // Form nằm trong tin tổng hợp. Không có tin nào đọc được (dữ liệu hỏng) → báo, không mở ô nhập nào.
    return replyShown ? null : (
      <p role="status" className="rounded-group border border-line bg-group p-5">
        Chưa hiện được nội dung cần phản hồi. Vui lòng tải lại trang.
      </p>
    );
  }
  if (waiting === "clarify") return null; // câu hỏi đã nằm trong hội thoại; ô trả lời ở dưới
  if (streamShown) return null; // khung tiến trình đã nói hệ thống đang làm gì
  return (
    <div className="flex items-start gap-3 motion-safe:animate-fade-in">
      <TurnAvatar busy />
      <p
        className="flex flex-wrap items-center gap-x-2.5 gap-y-1 rounded-group border border-line bg-white px-4 py-2.5 text-secondary shadow-input"
        data-testid="processing"
      >
        <span className="inline-flex items-center gap-1" aria-hidden="true">
          <span className="size-1.5 rounded-full bg-fpt-blue motion-safe:animate-bounce" />
          <span className="size-1.5 rounded-full bg-fpt-blue/70 motion-safe:animate-bounce motion-safe:[animation-delay:150ms]" />
          <span className="size-1.5 rounded-full bg-fpt-blue/40 motion-safe:animate-bounce motion-safe:[animation-delay:300ms]" />
        </span>
        <span className="shimmer-text font-semibold">{settling ? SENT_NOTE : parent ? PARENT_PROCESSING : statusLabel(view.status)}…</span>{" "}
        <span className="text-ink-2">Bạn không cần làm gì.</span>
      </p>
    </div>
  );
}
