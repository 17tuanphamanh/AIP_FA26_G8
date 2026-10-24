import { type QueryClient, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { approvalQuery, decideApproval, inboxQuery } from "../../api/approvals.ts";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { serverNow } from "../../api/serverClock.ts";
import type { ApprovalListItem, ApprovalViewP4, DecisionIn, ReasonCode } from "../../api/types.ts";
import { hasPerm, ROLE_LABEL } from "../../auth/permissions.ts";
import { useMe } from "../../auth/useAuth.ts";
import { ActionView, FlatTable } from "../../components/ActionView.tsx";
import { useServerNow } from "../../components/clock.ts";
import { Modal } from "../../components/Modal.tsx";
import { RejectSheet } from "../../components/RejectSheet.tsx";
import { ownEntry } from "../../lib/lookup.ts";
import {
  actionLabel,
  AFFECTED_OTHER_TEXT,
  AFFECTED_SELF_TEXT,
  approveBody,
  BACKUP_TEXT,
  DECISION_SENT,
  deadlineText,
  decisionRole,
  isReflex,
  isUrgent,
  managerText,
  MISSING_VALUE,
  NOTICES_TEXT,
  PLAN_CHANGED_TEXT,
  readonlyText,
  reflexText,
  rejectBody,
  remainingClock,
  RISK_MISSING_TEXT,
  riskSummary,
  STATUS_LABEL,
  VIEW_NOT_FOUND_TEXT,
  viewedSeconds,
  VIEWER_TEXT,
} from "./inbox.ts";

// B4L1Detail — `GET /api/approvals/{id}` (route THẬT 4c P6; dev:mock chỉ giả id phiếu minh hoạ). Hiện ĐÚNG object `action`
// đã băm (Bảng/JSON) + mã băm đủ; căn cứ quy trình; risk/facts khoá–giá trị chung. Trạng thái KH 4.6: 409 `plan_changed`
// (chỉ một câu, không object, không nút — G4-13), 404, dự phòng; N4c: người xem giám sát (`viewer`, hoặc `role_as` lạ) →
// một dòng thông tin, KHÔNG có đường quyết định nào. Trường null (phòng ban, rủi ro, căn cứ) → "—" / câu thay, không khoá
// quyết định: căn cứ để duyệt là object đã băm + mã băm. Quyết định: `POST …/decision` THẬT (MSW chỉ chặn id phiếu minh
// hoạ, Q-fe-5). Phiếu không còn `pending` → chỉ đọc. F6: chống duyệt theo phản xạ (P10 §3.2) — "Đồng ý" khi mới xem < 5 giây
// → hỏi lại; thanh quyết định nằm NGOÀI vùng cuộn, nền đặc (12b Q-fe-32 — như Bản 4: không bao giờ đè nội dung).

const BACK = (
  <Link to="/approvals" className="text-secondary text-fpt-blue">
    ‹ Chờ tôi duyệt
  </Link>
);

const isPlanChanged = (e: unknown) => e instanceof ApiError && e.status === 409 && e.code === "plan_changed";

/** Route `/approvals/:approvalId` — `key` theo id để nháp từ chối không mang sang phiếu khác. */
export function ApprovalDetailRoute() {
  const { approvalId = "" } = useParams();
  return <ApprovalDetail key={approvalId} id={approvalId} />;
}

function Blocked({ text }: { text: string }) {
  return (
    <section className="flex flex-col gap-2 px-12 py-10" data-testid="approval-blocked">
      {BACK}
      <h1 className="text-heading">{text}</h1>
    </section>
  );
}

function ApprovalDetail({ id }: { id: string }) {
  const query = useQuery(approvalQuery(id));
  // Hash lệch → KHÔNG hiện bản nào, kể cả bản đã tải trước đó (fail-closed, G4-13).
  if (isPlanChanged(query.error)) return <Blocked text={PLAN_CHANGED_TEXT} />;
  if (query.data) return <Detail view={query.data} />;
  if (query.isPending) return <p className="px-12 py-10 text-ink-2">Đang tải phiếu…</p>;
  if (query.error instanceof ApiError && query.error.status === 404) return <Blocked text={VIEW_NOT_FOUND_TEXT} />;
  return (
    <section className="flex flex-col gap-2 px-12 py-10">
      {BACK}
      <h1 className="text-heading">Chưa tải được phiếu</h1>
      <p role="alert" className="text-ink-2">
        {errorMessage(query.error instanceof ApiError ? query.error : null)}
      </p>
    </section>
  );
}

/** created_at: xem phiếu không trả (4c P6) → lấy từ hộp thư đã tải; chưa có (mở thẳng trang) → gọi lại hộp thư. */
function cachedCreatedAt(client: QueryClient, approvalId: string): string | null {
  for (const [, items] of client.getQueriesData<ApprovalListItem[]>({ queryKey: ["approvals", "list"] })) {
    const hit = items?.find((i) => i.approval_id === approvalId);
    if (hit) return hit.created_at;
  }
  return null;
}

function useCreatedAt(view: ApprovalViewP4): string | null {
  const client = useQueryClient();
  const cached = cachedCreatedAt(client, view.approval_id);
  const list = useQuery({ ...inboxQuery(view.status), enabled: cached === null });
  return cached ?? list.data?.find((i) => i.approval_id === view.approval_id)?.created_at ?? null;
}

function Deadline({ view, createdAt }: { view: ApprovalViewP4; createdAt: string | null }) {
  const now = useServerNow();
  if (view.status !== "pending") {
    return (
      <span data-testid="approval-status" className="shrink-0 rounded-full bg-group px-3.5 py-1.5 text-secondary font-semibold">
        {ownEntry(STATUS_LABEL, view.status, "")}
      </span>
    );
  }
  const urgent = isUrgent(createdAt, view.deadline, now);
  return (
    <span
      data-testid="approval-deadline"
      data-urgent={urgent}
      className={`shrink-0 rounded-full px-3.5 py-1.5 text-secondary font-semibold tabular-nums ${
        urgent ? "bg-danger-bg text-danger" : "bg-group text-ink"
      }`}
    >
      {remainingClock(view.deadline, now, createdAt)}
    </span>
  );
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="pl-1 text-label text-ink-2">{title}</h2>
      {children}
    </section>
  );
}

function Detail({ view }: { view: ApprovalViewP4 }) {
  const me = useMe();
  const queryClient = useQueryClient();
  const createdAt = useCreatedAt(view);
  const startedAt = useRef<string | null>(null); // giờ (máy chủ) bắt đầu xem — chỉ để backend ghi log
  const viewStart = useRef<number | null>(null); // mốc performance.now() khi chi tiết hiện xong — chống duyệt theo phản xạ
  const inFlight = useRef(false); // chặn bấm 2 lần trong cùng một nhịp (state chưa kịp cập nhật)
  const [sending, setSending] = useState(false);
  const [sheet, setSheet] = useState(false);
  const [sheetError, setSheetError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<{ redacted: boolean } | null>(null);
  const [reflex, setReflex] = useState<number | null>(null); // số giây đã xem khi hộp "xem lại" đang mở
  const pending = view.status === "pending";
  const role = decisionRole(view.role_as);
  // Chỉ người được giao / dự phòng, phiếu còn chờ, mới có đường quyết định (thanh, hộp hỏi lại, sheet, hàm gửi).
  const canDecide = pending && role !== "viewer";

  // `Detail` chỉ render khi GET phiếu 200 → effect đầu tiên = lúc khối chi tiết hiện xong.
  useEffect(() => {
    startedAt.current ??= new Date(serverNow()).toISOString();
    viewStart.current ??= performance.now();
  }, []);

  const reload = () => void queryClient.invalidateQueries({ queryKey: ["approvals"] });

  async function send(body: DecisionIn, fromSheet: boolean) {
    if (inFlight.current || sent || !canDecide) return;
    inFlight.current = true;
    setSending(true);
    setError(null);
    setSheetError(null);
    try {
      const res = await decideApproval(view.approval_id, body);
      setSent({ redacted: Array.isArray(res.notices) && res.notices.length > 0 });
      setSheet(false);
      reload();
    } catch (e) {
      const message = errorMessage(e instanceof ApiError ? e : null);
      if (e instanceof ApiError && e.status === 409) {
        // Phiếu đã chuyển bước (quyết rồi / quá hạn): báo câu của server + tải lại phiếu và hộp thư.
        setSheet(false);
        setError(message);
        reload();
      } else if (fromSheet) {
        setSheetError(message); // giữ sheet + lựa chọn + ghi chú để sửa rồi gửi lại
      } else {
        setError(message);
      }
    } finally {
      inFlight.current = false;
      setSending(false);
    }
  }

  // CHỈ hỏi lại khi ĐỒNG Ý: đồng ý vội là chiều gây hại (hệ thống thực hiện hành động). Từ chối là hướng an toàn — không
  // chặn thêm bước nào, để người duyệt không ngại từ chối khi còn nghi ngờ (không đẩy tăng ca bỏ sót).
  function approve() {
    if (inFlight.current || sent || !canDecide) return;
    const seconds = viewedSeconds(viewStart.current, performance.now());
    if (isReflex(seconds)) {
      setReflex(seconds);
      return;
    }
    void send(approveBody(startedAt.current), false);
  }

  const actionType = view.action.type;
  const title = typeof actionType === "string" ? actionLabel(actionType) : "Hành động";
  const requesterRole = ownEntry(ROLE_LABEL, view.requester.role, view.requester.role || MISSING_VALUE);
  const department = view.requester.department || MISSING_VALUE;
  const deadlineAt = deadlineText(view.deadline);
  const { affected } = view;
  const risk = view.risk_view ? riskSummary(view.risk_view) : null;
  // Thiếu cả `procedure` (lệch spec) → không vỡ màn: hiện "(không có)".
  const procedureTitle = view.procedure?.title?.trim();
  const procedureDoc = view.procedure?.doc_id ?? "(không có)";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div data-testid="approval-scroll" className="min-h-0 grow overflow-y-auto">
        <section className="flex flex-col gap-6 px-12 pt-8 pb-6">
          <div className="flex flex-col gap-1">
            {BACK}
            <div className="flex items-center gap-4">
              <h1 className="min-w-0 grow text-title">
                Phiếu <span className="font-mono">{view.approval_id}</span>
              </h1>
              <Deadline view={view} createdAt={createdAt} />
            </div>
            <p className="text-label font-normal text-ink-2">
              Mã ticket <span className="font-mono select-all">{view.ticket_id}</span>
              {deadlineAt ? (
                <>
                  {" "}
                  · Hạn duyệt <span data-testid="approval-deadline-at">{deadlineAt}</span>
                </>
              ) : null}
            </p>
          </div>

          {role === "backup" ? (
            <div role="note" data-testid="backup-banner" className="rounded-group bg-orange-bg px-5 py-3.5 text-orange-ink">
              <b className="font-semibold">{BACKUP_TEXT}</b> — người duyệt chính chưa quyết sau lần nhắc thứ hai.
            </div>
          ) : null}
          {role === "viewer" ? (
            <p role="note" data-testid="viewer-note" className="rounded-group bg-group px-5 py-3.5">
              {VIEWER_TEXT}
            </p>
          ) : null}
          {!pending ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-group bg-group px-5 py-3.5">
              <p role="status" data-testid="approval-readonly" className="grow">
                {readonlyText(view.status)}
              </p>
              {/* Q-fe-24: lối vào ghi đè theo quyền + `ticket_id` của phiếu (ticket đã rời bước duyệt); server quyết. */}
              {hasPerm(me, "decision:override") ? (
                <Link
                  to={`/approvals/ticket/${encodeURIComponent(view.ticket_id)}`}
                  data-testid="override-link"
                  className="shrink-0 text-secondary font-semibold text-fpt-blue"
                >
                  Xem ticket · Ghi đè…
                </Link>
              ) : null}
            </div>
          ) : null}

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_360px]">
            <Block title="Hệ thống sẽ thực hiện chính xác">
              <ActionView action={view.action} hash={view.action_plan_hash} title={title} />
            </Block>
            <aside className="flex flex-col gap-6">
              <Block title="Yêu cầu của người gửi">
                <p data-testid="request-summary" className="rounded-group border border-line px-5 py-3 whitespace-pre-line">
                  {view.request_summary}
                </p>
              </Block>
              <Block title="Người gửi">
                <dl className="overflow-hidden rounded-group border border-line text-secondary">
                  <div className="flex justify-between gap-4 px-5 py-3">
                    <dt>Vai trò</dt>
                    <dd className="text-ink-2">{requesterRole}</dd>
                  </div>
                  <div className="flex justify-between gap-4 border-t border-line px-5 py-3">
                    <dt>Phòng ban</dt>
                    <dd className="text-ink-2">{department}</dd>
                  </div>
                </dl>
              </Block>
              <Block title="Người bị ảnh hưởng">
                <div data-testid="affected" className="flex flex-col gap-2">
                  {!affected.is_requester ? (
                    <p role="note" data-testid="affected-other" className="rounded-group bg-orange-bg px-5 py-3 text-orange-ink">
                      <b className="font-semibold">{AFFECTED_OTHER_TEXT}</b> — hành động áp dụng lên tài khoản này, không phải người gửi.
                    </p>
                  ) : null}
                  <dl className="overflow-hidden rounded-group border border-line text-secondary">
                    <div className="flex justify-between gap-4 px-5 py-3">
                      <dt>Tài khoản</dt>
                      <dd data-testid="affected-user" className="font-mono text-ink-2">
                        {affected.user_id}
                      </dd>
                    </div>
                    <div className="flex justify-between gap-4 border-t border-line px-5 py-3">
                      <dt>Quan hệ với người gửi</dt>
                      <dd data-testid="affected-relation" className="text-ink-2">
                        {affected.is_requester ? AFFECTED_SELF_TEXT : AFFECTED_OTHER_TEXT}
                      </dd>
                    </div>
                    <div className="flex justify-between gap-4 border-t border-line px-5 py-3">
                      <dt>Phòng ban</dt>
                      <dd data-testid="affected-department" className="text-ink-2">
                        {affected.department || MISSING_VALUE}
                      </dd>
                    </div>
                    <div className="flex justify-between gap-4 border-t border-line px-5 py-3">
                      <dt>Quản lý</dt>
                      <dd data-testid="affected-manager" data-known={affected.manager.status === "known"} className="text-right text-ink-2">
                        {managerText(affected.manager)}
                      </dd>
                    </div>
                  </dl>
                </div>
              </Block>
              <Block title="Căn cứ quy trình">
                <p data-testid="procedure" className="flex flex-col rounded-group border border-line px-5 py-3">
                  <span>{procedureTitle || procedureDoc}</span>
                  {procedureTitle ? <span className="font-mono text-label font-normal text-ink-2">{procedureDoc}</span> : null}
                </p>
              </Block>
              <Block title="Đánh giá rủi ro">
                {view.risk ? (
                  <div className="flex flex-col gap-2">
                    {risk ? (
                      <dl data-testid="risk-summary" className="overflow-hidden rounded-group border border-line text-secondary">
                        <div className="flex justify-between gap-4 px-5 py-3">
                          <dt>Mức rủi ro</dt>
                          <dd data-testid="risk-level" data-level={view.risk_view?.risk_level} className="font-semibold">
                            {risk.level}
                          </dd>
                        </div>
                        <div className="flex justify-between gap-4 border-t border-line px-5 py-3">
                          <dt>Hướng xử lý</dt>
                          <dd data-testid="risk-route" className="text-ink-2">
                            {risk.route}
                          </dd>
                        </div>
                        <div className="flex justify-between gap-4 border-t border-line px-5 py-3">
                          <dt>Lý do</dt>
                          <dd data-testid="risk-reason" className="text-right text-ink-2">
                            {risk.reason}
                          </dd>
                        </div>
                        <div className="flex justify-between gap-4 border-t border-line px-5 py-3">
                          <dt>Luật khớp</dt>
                          <dd data-testid="risk-rule" className="font-mono text-ink-2">
                            {risk.ruleId ?? MISSING_VALUE}
                          </dd>
                        </div>
                        <div className="flex justify-between gap-4 border-t border-line px-5 py-3">
                          <dt>Nguồn đánh giá</dt>
                          <dd data-testid="risk-source" className="text-right text-ink-2">
                            {risk.source}
                          </dd>
                        </div>
                      </dl>
                    ) : null}
                    {risk?.note ? (
                      <p role="note" data-testid="risk-uncalibrated" className="rounded-group bg-orange-bg px-5 py-3 text-orange-ink">
                        {risk.note}
                      </p>
                    ) : null}
                    <div className="overflow-hidden rounded-group border border-line">
                      <FlatTable value={view.risk} testId="risk-row" />
                    </div>
                  </div>
                ) : (
                  <p data-testid="risk-missing" className="rounded-group border border-line px-5 py-3 text-ink-2">
                    {RISK_MISSING_TEXT}
                  </p>
                )}
              </Block>
              <Block title="Dữ kiện đã kiểm">
                <div className="overflow-hidden rounded-group border border-line">
                  <FlatTable value={view.facts} testId="fact-row" />
                </div>
              </Block>
            </aside>
          </div>

          {error ? (
            <p role="alert" className="text-danger">
              {error}
            </p>
          ) : null}
          {sent ? (
            <p role="status" data-testid="decision-sent" className="rounded-group bg-group px-5 py-3.5">
              <b className="font-semibold">{DECISION_SENT}</b>
              {sent.redacted ? ` · ${NOTICES_TEXT}` : ""}
            </p>
          ) : null}
        </section>
      </div>

      {canDecide && !sent ? (
        <div data-testid="decision-bar" className="flex h-19 shrink-0 items-center gap-3 border-t border-line bg-white px-12">
          <button
            type="button"
            onClick={() => {
              setSheetError(null);
              setSheet(true);
            }}
            disabled={sending}
            className="h-11 rounded-full bg-danger-bg px-5.5 font-semibold text-danger disabled:opacity-60"
          >
            Từ chối
          </button>
          <span className="grow text-label font-normal text-ink-2">Quyết định được ghi vào nhật ký kiểm toán.</span>
          <button
            type="button"
            onClick={approve}
            disabled={sending}
            className="h-11 rounded-full bg-fpt-blue px-6 font-semibold text-white disabled:opacity-60"
          >
            {sending && !sheet ? "Đang gửi…" : "Đồng ý thực hiện"}
          </button>
        </div>
      ) : null}

      {canDecide && reflex !== null && !sent ? (
        <Modal label="Xác nhận đồng ý" onClose={() => setReflex(null)}>
          <h2 className="text-center text-heading">Xem kỹ trước khi đồng ý</h2>
          <p data-testid="reflex-text">{reflexText(reflex)}</p>
          <div className="grid grid-cols-2 gap-3">
            {/* Nút mặc định (focus) là "Xem lại": Enter / Esc vội không thành đồng ý. */}
            <button type="button" autoFocus onClick={() => setReflex(null)} className="h-11 rounded-full bg-fpt-blue font-semibold text-white">
              Xem lại
            </button>
            <button
              type="button"
              onClick={() => {
                setReflex(null);
                void send(approveBody(startedAt.current), false);
              }}
              className="h-11 rounded-full bg-button-2 font-semibold text-fpt-blue"
            >
              Vẫn đồng ý
            </button>
          </div>
        </Modal>
      ) : null}

      {canDecide && sheet && !sent ? (
        <RejectSheet
          sending={sending}
          serverError={sheetError}
          onCancel={() => setSheet(false)}
          onSubmit={(reason: ReasonCode, note: string) => void send(rejectBody(reason, note, startedAt.current), true)}
        />
      ) : null}
    </div>
  );
}
