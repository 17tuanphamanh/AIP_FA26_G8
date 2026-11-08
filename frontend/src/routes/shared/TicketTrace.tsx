import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { MatchedRules } from "./MatchedRules.tsx";
import { MaNhan, NhanMa } from "../../components/MaNhan.tsx";
import { luatIT } from "../../lib/nhan.ts";
import { approvalQuery } from "../../api/approvals.ts";
import { loadedItems, queueQuery } from "../../api/escalations.ts";
import { TRACE_TICKET_ID, traceQuery, tracePath, type TicketTrace as Trace, type TraceStep } from "../../api/trace.ts";
import {
  closeNoteLine,
  formatAt,
  formatProb,
  policyProbs,
  rollbackText,
  screenLayer,
  stepTitle,
  TRACE_BAD_ID_TEXT,
  TRACE_EMPTY_TEXT,
  TRACE_TITLE,
  traceErrorText,
} from "./traceText.ts";

// Nhật ký quyết định của một ticket — `GET /api/tickets/{id}/trace` THẬT (chỉ đọc; L1, L2, Trưởng BP IT). Mỗi bước một
// thẻ theo thời gian, nhãn tiếng Việt; chỉ hiện các trường backend đã lọc theo danh sách trắng (không câu người dùng, không
// prompt, không tham số). Lỗi: 403 / 404 / thân sai hình dạng có câu riêng — KHÔNG hiện dữ liệu cũ kèm lỗi. Chữ từ server
// hiện thô (React tự thoát), không Markdown, không ảnh/thư viện ngoài.

/** Route `/trace/:ticketId` — `key` theo id để không mang dữ liệu sang ticket khác. */
export function TicketTraceRoute() {
  const { ticketId = "" } = useParams();
  return <TicketTrace key={ticketId} ticketId={ticketId} />;
}

function Page({ ticketId, children }: { ticketId: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-6 px-12 py-8 max-lg:px-4 max-lg:py-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-title">{TRACE_TITLE}</h1>
        <p className="text-ink-2">
          Yêu cầu <span className="font-mono select-all">{ticketId}</span> · chỉ xem, theo thứ tự thời gian.
        </p>
      </div>
      {children}
    </section>
  );
}

function TicketTrace({ ticketId }: { ticketId: string }) {
  const valid = TRACE_TICKET_ID.test(ticketId);
  const query = useQuery({ ...traceQuery(ticketId), enabled: valid });
  if (!valid) {
    return (
      <Page ticketId={ticketId}>
        <p role="alert" className="text-danger">
          {TRACE_BAD_ID_TEXT}
        </p>
      </Page>
    );
  }
  return (
    <Page ticketId={ticketId}>
      {query.isError ? (
        <div role="alert" data-testid="trace-error" className="rounded-group bg-danger-bg px-5 py-4 text-danger-ink">
          {traceErrorText(query.error)}
        </div>
      ) : query.isPending ? (
        <p className="text-ink-2 motion-safe:animate-pulse">Đang tải nhật ký…</p>
      ) : (
        <Body trace={query.data} />
      )}
    </Page>
  );
}

function Body({ trace }: { trace: Trace }) {
  return (
    <>
      {trace.parent_ticket_id ? (
        <p data-testid="trace-parent" className="text-ink-2">
          Ý con của yêu cầu{" "}
          <Link to={tracePath(trace.parent_ticket_id)} className="font-mono text-fpt-blue max-lg:inline-flex max-lg:min-h-11 max-lg:items-center">
            {trace.parent_ticket_id}
          </Link>
        </p>
      ) : null}
      {trace.is_parent ? (
        <section aria-labelledby="trace-children-heading" data-testid="trace-children" className="flex flex-col gap-2">
          <h2 id="trace-children-heading" className="text-heading">
            Các ý con ({trace.children.length})
          </h2>
          <ul className="flex flex-col gap-1">
            {trace.children.map((c) => (
              <li key={c.ticket_id} data-testid="trace-child">
                <Link to={tracePath(c.ticket_id)} className="font-mono text-fpt-blue max-lg:inline-flex max-lg:min-h-11 max-lg:items-center">
                  {c.ticket_id}
                </Link>
                <span className="text-ink-2">
                  {" "}
                  · {c.intent === null ? "chưa phân loại" : <MaNhan loai="loai_yeu_cau" ma={c.intent} />}
                  {c.exit_code ? (
                    <>
                      {" · "}
                      <MaNhan loai="ma_ket_thuc" ma={c.exit_code} />
                    </>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {trace.steps.length === 0 ? (
        <p className="text-ink-2">{TRACE_EMPTY_TEXT}</p>
      ) : (
        <ol aria-label="Các bước" className="flex flex-col gap-3">
          {trace.steps.map((s, i) => (
            <StepCard key={i} step={s} />
          ))}
        </ol>
      )}
    </>
  );
}

function Line({ children, testId }: { children: ReactNode; testId?: string }) {
  return (
    <p data-testid={testId} className="text-secondary text-ink-2">
      {children}
    </p>
  );
}

function StepCard({ step: s }: { step: TraceStep }) {
  const layer = s.screen ? screenLayer(s.screen) : null;
  const probs = s.policy ? policyProbs(s.policy) : null;
  const rollback = s.execution ? rollbackText(s.execution) : null;
  const closeNote = s.outcome ? closeNoteLine(s.outcome) : null;
  return (
    <li data-testid="trace-step" data-step={s.step} className="flex flex-col gap-1 rounded-group border border-line px-5 py-4">
      <div className="flex items-baseline gap-3 max-lg:flex-wrap">
        <h3 data-testid="trace-step-title" className="min-w-0 grow font-semibold">
          {stepTitle(s)}
        </h3>
        <span className="shrink-0 text-secondary text-ink-2 tabular-nums">{formatAt(s.at)}</span>
      </div>
      <Line testId="trace-step-codes">
        <MaNhan loai="buoc" ma={s.step} /> · <MaNhan loai="su_kien" ma={s.event} />
      </Line>
      {s.classify?.intent ? (
        <Line>
          Loại yêu cầu <MaNhan loai="loai_yeu_cau" ma={s.classify.intent} />
        </Line>
      ) : null}
      {s.policy?.rule_id ? (
        <Line testId="trace-rule">
          Luật <NhanMa {...luatIT(s.policy.rule_id, s.policy.rule_description)} />
        </Line>
      ) : null}
      {s.outcome?.exit_code ? (
        <Line testId="trace-exit">
          Mã kết thúc <MaNhan loai="ma_ket_thuc" ma={s.outcome.exit_code} />
        </Line>
      ) : null}
      {layer ? <Line>{layer}</Line> : null}
      {s.classify?.model_version ? (
        <Line>
          Phiên bản model <span className="font-mono">{s.classify.model_version}</span>
        </Line>
      ) : null}
      {s.classify?.model_probs && Object.keys(s.classify.model_probs).length > 0 ? (
        <Line testId="trace-model-probs">
          Model:{" "}
          {Object.entries(s.classify.model_probs)
            .map(([label, p]) => `${label} ${formatProb(p)}`)
            .join(" · ")}
        </Line>
      ) : null}
      {s.diagnose && s.diagnose.fact_keys.length > 0 ? (
        <Line testId="trace-facts">
          Dữ kiện: <span className="font-mono">{s.diagnose.fact_keys.join(", ")}</span>
        </Line>
      ) : null}
      {s.sources && s.sources.length > 0 ? (
        <ul data-testid="trace-sources" className="flex flex-col text-secondary text-ink-2">
          {s.sources.map((src) => (
            <li key={src.doc_id}>
              Nguồn KB <span className="font-mono">{src.doc_id}</span>
              {src.title ? ` — ${src.title}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
      {probs ? <Line>{probs}</Line> : null}
      {s.approval?.at ? <Line>Lúc {formatAt(s.approval.at)}</Line> : null}
      {s.execution && s.execution.calls.length > 0 ? (
        <ul data-testid="trace-calls" className="flex flex-col text-secondary text-ink-2">
          {s.execution.calls.map((c, i) => (
            <li key={i}>
              <span className="font-mono">{c.name}</span>: {c.result === "ok" ? "thành công" : "thất bại"}
            </li>
          ))}
        </ul>
      ) : null}
      {rollback ? <Line>{rollback}</Line> : null}
      {s.policy ? (
        <div className="pt-2">
          <MatchedRules rules={s.policy.matched_rules} headingLevel={3} />
        </div>
      ) : null}
      {closeNote ? (
        // Ghi chú đóng ca của L2 (chữ tự do, đã che ở backend): hiện thô như chữ, xuống dòng khi quá dài.
        <p data-testid="trace-close-note" className="text-secondary text-ink-2 min-w-0 break-words whitespace-pre-line">
          {closeNote}
        </p>
      ) : null}
    </li>
  );
}

// ---- Nút "Nhật ký quyết định" gắn ở router (App.tsx) cạnh màn phiếu duyệt L1, chi tiết escalate L2, xem ticket — đọc mã
// ticket từ CHÍNH truy vấn mà màn đó đã dùng (cùng khoá cache), không gọi thêm route nào. Chưa biết mã ticket → không hiện.

function TraceButton({ ticketId }: { ticketId: string | undefined }) {
  if (!ticketId || !TRACE_TICKET_ID.test(ticketId)) return null;
  return (
    // Cao 0 + sticky: nút nổi ở góc phải trên, KHÔNG chiếm một hàng — màn chi tiết (h-full) không bị đẩy xuống, thanh quyết
    // định của phiếu duyệt luôn nằm trong khung nhìn.
    <div className="sticky top-0 z-10 flex h-0 justify-end overflow-visible px-12 max-lg:px-4">
      <Link
        to={tracePath(ticketId)}
        data-testid="trace-link"
        className="mt-6 inline-flex h-9 items-center rounded-full border border-line bg-white px-4 text-secondary font-semibold text-fpt-blue hover:bg-group max-lg:mt-3 max-lg:h-11 max-lg:px-3"
      >
        {TRACE_TITLE}
      </Link>
    </div>
  );
}

/** Màn phiếu duyệt `/approvals/:approvalId`. */
export function ApprovalTraceLink() {
  const { approvalId = "" } = useParams();
  const query = useQuery(approvalQuery(approvalId));
  return <TraceButton ticketId={query.data?.ticket_id} />;
}

/** Chi tiết escalate `/escalations/:escalationId[?status=closed]` — ca tìm trong các trang đã tải như màn chi tiết. */
export function EscalationTraceLink() {
  const { escalationId = "" } = useParams();
  const [params] = useSearchParams();
  const query = useInfiniteQuery(queueQuery(params.get("status") === "closed" ? "closed" : "open"));
  const id = /^\d{1,15}$/.test(escalationId) ? Number(escalationId) : null;
  return <TraceButton ticketId={loadedItems(query.data)?.find((i) => i.escalation_id === id)?.ticket_id} />;
}

/** Xem ticket `/approvals/ticket/:ticketId` (nơi Trưởng BP IT / L1 xem ticket để ghi đè). */
export function TicketTraceLink() {
  const { ticketId = "" } = useParams();
  return <TraceButton ticketId={ticketId} />;
}
