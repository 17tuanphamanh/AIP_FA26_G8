import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { llmStatusQuery } from "../../api/llmStatus.ts";
import { ApiError, routeMissing } from "../../api/errors.ts";
import type { LlmBackend, LlmKbStatus, LlmSpendStatus, LlmStatus as Status } from "../../api/types.ts";
import { Forbidden } from "../Forbidden.tsx";
import { formatNumber, formatRate, formatUsd } from "./metrics.ts";
import { LoadError, MissingPanel } from "./panels.tsx";
import { vnDateTime } from "./range.ts";

// Trạng thái LLM (I1) — trang QUẢN TRỊ CHỈ ĐỌC cho Trưởng BP IT: `GET /api/admin/llm-status`. Không nút sửa, không ô nhập;
// đổi cấu hình LLM làm ở file cấu hình + khởi động lại. Trạng thái = chấm màu + chữ xám (token), chữ ≥ 16 px (chỉ dùng
// cỡ body trở lên của token — không dùng hai cỡ nhỏ 15 px và 13 px). Mọi chữ từ server hiện thô (React tự thoát).

export const LLM_STATUS_MISSING_TITLE = "Máy chủ chưa có trang Trạng thái LLM";
export const LLM_STATUS_MISSING_TEXT = "Máy chủ chưa có route /api/admin/llm-status. Khi bản backend mới được triển khai, trang này tự hiện số liệu thật.";
export const COST_UPPER_BOUND_TEXT =
  "Chi phí tính theo bảng giá giờ cao điểm trong cấu hình — là cận trên, có thể cao hơn hoá đơn nhà cung cấp.";
export const AVG_DEFINITION_TEXT = "Trung bình mỗi yêu cầu = tổng chi ÷ số yêu cầu có ít nhất một lời gọi LLM, tính trên toàn bộ lịch sử.";
const NOT_SET = "chưa cấu hình";

type Dot = "bg-done" | "bg-fpt-orange" | "bg-danger" | "bg-ink-3";

const BACKEND: Record<LlmBackend, { dot: Dot; text: string }> = {
  scripted: { dot: "bg-ink-3", text: "Giả lập — không gọi nhà cung cấp thật" },
  real: { dot: "bg-done", text: "Thật — gọi nhà cung cấp AI" },
};
const SPEND: Record<LlmSpendStatus, { dot: Dot; text: (warnPercent: number) => string }> = {
  ok: { dot: "bg-done", text: () => "Trong ngưỡng" },
  warn: { dot: "bg-fpt-orange", text: (w) => `Từ ngưỡng cảnh báo (${formatRate(w / 100)} trần) trở lên` },
  over: { dot: "bg-danger", text: () => "Đã chạm trần — mô hình trả phí bị chặn" },
};
const KB: Record<LlmKbStatus, { dot: Dot; text: string }> = {
  ready: { dot: "bg-done", text: "Đã nạp" },
  missing: { dot: "bg-fpt-orange", text: "Chưa có bản KB nào đang dùng" },
  unknown: { dot: "bg-ink-3", text: "Không kiểm tra được lúc này" },
};

/** Chấm màu + chữ xám (trạng thái không chỉ bằng màu). */
function State({ dot, text, testId }: { dot: Dot; text: string; testId: string }) {
  return (
    <p data-testid={testId} className="flex items-center gap-2 text-ink-2">
      <span className={`size-2.5 shrink-0 rounded-full ${dot}`} aria-hidden="true" />
      <span>{text}</span>
    </p>
  );
}

function Card({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={`${id}-heading`} data-testid={id} className="flex flex-col gap-3 rounded-group border border-line px-5 py-4">
      <h2 id={`${id}-heading`} className="text-heading">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, value, testId }: { label: string; value: ReactNode; testId?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="text-ink-2">{label}</dt>
      <dd data-testid={testId} className="text-right tabular-nums">
        {value}
      </dd>
    </div>
  );
}

const textOr = (value: string | null) => value ?? NOT_SET;

function Body({ data }: { data: Status }) {
  const backend = data.backend === null ? { dot: "bg-ink-3" as Dot, text: "Chưa xác định" } : BACKEND[data.backend];
  const spend = SPEND[data.spend.status];
  const kb = KB[data.kb.status];
  const avg = data.usage.avg_cost_per_ticket_usd;
  return (
    <>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <Card id="llm-backend" title="Máy chủ và mô hình AI">
          <State dot={backend.dot} text={backend.text} testId="llm-backend-state" />
          <dl className="flex flex-col gap-1">
            <Row label="Mô hình nhanh" value={<span className="font-mono">{textOr(data.models.fast)}</span>} testId="llm-model-fast" />
            <Row label="Mô hình mạnh" value={<span className="font-mono">{textOr(data.models.strong)}</span>} testId="llm-model-strong" />
          </dl>
          <State
            dot={data.api_key_configured ? "bg-done" : "bg-fpt-orange"}
            text={data.api_key_configured ? "Khoá API: đã cấu hình" : "Khoá API: chưa cấu hình"}
            testId="llm-key-state"
          />
        </Card>

        <Card id="llm-spend" title="Chi tiêu so với trần">
          <p data-testid="llm-spend-total" className="text-title tabular-nums">
            {formatUsd(data.spend.total_usd)} <span className="text-heading text-ink-2">/ {formatUsd(data.spend.cap_usd)} USD</span>
          </p>
          <p data-testid="llm-spend-percent" className="tabular-nums">
            Đã dùng {formatRate(data.spend.percent / 100)} trần
          </p>
          <State dot={spend.dot} text={spend.text(data.spend.warn_percent)} testId="llm-spend-state" />
          <p data-testid="llm-spend-note" className="text-ink-2">
            {COST_UPPER_BOUND_TEXT}
          </p>
        </Card>

        <Card id="llm-usage" title="Mức sử dụng">
          <dl className="flex flex-col gap-1">
            <Row label="Lời gọi trong 24 giờ qua" value={formatNumber(data.usage.calls_24h, "count")} testId="llm-calls-24h" />
            <Row label="Tổng số lời gọi" value={formatNumber(data.usage.calls_total, "count")} testId="llm-calls-total" />
            <Row label="Số yêu cầu có lời gọi" value={formatNumber(data.usage.tickets_with_calls, "count")} testId="llm-tickets" />
            <Row
              label="Chi phí trung bình mỗi yêu cầu"
              value={avg === null ? "— (chưa có yêu cầu)" : `${formatUsd(avg)} USD`}
              testId="llm-avg-cost"
            />
          </dl>
          <p data-testid="llm-avg-definition" className="text-ink-2">
            {AVG_DEFINITION_TEXT}
          </p>
        </Card>

        <Card id="llm-kb" title="Cơ sở tri thức (KB)">
          <State dot={kb.dot} text={kb.text} testId="llm-kb-state" />
          <dl className="flex flex-col gap-1">
            <Row label="Bí danh đang dùng" value={<span className="font-mono">{data.kb.alias}</span>} />
            <Row label="Phiên bản đang nạp" value={<span className="font-mono">{textOr(data.kb.collection)}</span>} testId="llm-kb-version" />
          </dl>
        </Card>
      </div>
      <p data-testid="llm-as-of" className="text-ink-2">
        Số liệu tại {vnDateTime(data.as_of)} (giờ Việt Nam).
      </p>
    </>
  );
}

export function LlmStatus() {
  const query = useQuery(llmStatusQuery());
  if (query.error instanceof ApiError && query.error.status === 403) return <Forbidden />;
  const missing = routeMissing(query.error);

  return (
    <section className="flex flex-col gap-6 px-12 py-10 max-lg:px-4 max-lg:py-6">
      <div className="flex flex-col gap-1">
        <h1 className="text-title">Trạng thái LLM</h1>
        <p className="text-ink-2">Chỉ để xem — trang này không có thao tác sửa cấu hình nào.</p>
      </div>
      {missing ? (
        <MissingPanel testId="llm-status-missing" title={LLM_STATUS_MISSING_TITLE} text={LLM_STATUS_MISSING_TEXT} />
      ) : query.isError ? (
        <LoadError error={query.error} what="trạng thái LLM" />
      ) : query.isPending ? (
        <p className="text-ink-2 motion-safe:animate-pulse">Đang tải trạng thái LLM…</p>
      ) : (
        <Body data={query.data} />
      )}
    </section>
  );
}
