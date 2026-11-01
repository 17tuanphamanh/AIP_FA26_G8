import { useState } from "react";
import { actionValueLabel } from "../routes/l1/actionLabels.ts";
import { actionKeyLabel, flattenEntries, isShortValue } from "../routes/l1/inbox.ts";

// B4L1Detail "Hệ thống sẽ thực hiện chính xác": ĐÚNG object `action` đã băm nhận từ server (KH 4.2 #5 [Chốt 5.2.1]).
// Tab Bảng liệt kê đủ mọi khoá (đệ quy, tên khoá giữ nguyên); tab JSON = JSON.stringify của CHÍNH object đó. Không tóm
// tắt, không đổi tên, không lọc khoá. Mã băm hiện đủ, font mono, có nút sao chép.

/**
 * Bảng khoá–giá trị chung (dùng cho `action`, `risk`, `facts`): chữ thô, không Markdown/HTML. `keyLabel`: nhãn tiếng Việt cạnh
 * khoá đã biết ("Nhãn · khoá" — khoá giữ nguyên, chữ nhỏ); khoá lạ → chỉ khoá.
 */
export function FlatTable({
  value,
  testId,
  keyLabel,
  valueLabel,
  showRaw = true,
}: {
  value: unknown;
  testId: string;
  keyLabel?: (key: string) => string | null;
  /** B2: nhãn dễ đọc cho giá trị (bảng nhãn 1-1). Không truyền → ô giá trị như cũ. */
  valueLabel?: (key: string, raw: string) => string | null;
  /** B2 (b): dòng CÓ nhãn — giá trị gốc hiện hay ẩn (vẫn trong DOM). Dòng không nhãn luôn hiện gốc. */
  showRaw?: boolean;
}) {
  return (
    <dl className="font-mono text-secondary">
      {flattenEntries(value).map((entry) => {
        // Giá trị ngắn: dòng `flex-wrap` — không vừa cạnh khoá thì CẢ giá trị xuống dòng dưới, căn phải (không để một dấu câu
        // rơi riêng một dòng); chỉ khi một mình vẫn không vừa cả dòng mới ngắt — không `nowrap`, nên không bao giờ bị khung
        // `overflow-hidden` cắt mất đuôi. Giá trị dài: cạnh khoá, ngắt ở ranh giới hợp lý; chuỗi liền quá dài mới ngắt giữa.
        const short = isShortValue(entry.value);
        return (
          <div
            key={entry.key}
            data-testid={testId}
            data-key={entry.key}
            className={`flex justify-between border-t border-line px-5 py-2.5 first:border-t-0 ${short ? "flex-wrap gap-x-4 gap-y-1" : "gap-4"}`}
          >
            <dt className="shrink-0 text-ink-2">
              {keyLabel && entry.key && keyLabel(entry.key) ? (
                <>
                  <span className="font-sans">{keyLabel(entry.key)}</span> · <span className="text-label font-normal">{entry.key}</span>
                </>
              ) : (
                entry.key || "(gốc)"
              )}
            </dt>
            <dd className={`min-w-0 text-right wrap-anywhere break-normal${short ? " ml-auto max-w-full" : ""}`}>
              {valueLabel ? <LabeledValue raw={entry.value} label={valueLabel(entry.key, entry.value)} showRaw={showRaw} /> : entry.value}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

/** B2 (b, ĐP 01/11 14:50). Có nhãn: nhãn là chữ chính; giá trị gốc (phần tử riêng — test so từng ký tự) LUÔN có trong DOM,
 *  hiện ngay dưới khi bật "Hiện giá trị gốc", ẩn (`hidden`) khi tắt. Không nhãn (mã người dùng, mã máy, đường dẫn, tên phần
 *  mềm, khoá/giá trị lạ): luôn hiện gốc. */
function LabeledValue({ raw, label, showRaw }: { raw: string; label: string | null; showRaw: boolean }) {
  if (label === null) return <span data-testid="raw-value">{raw}</span>;
  return (
    <span className="inline-flex flex-col items-end">
      <span data-testid="value-label" className="font-sans text-ink">
        {label}
      </span>
      <span data-testid="raw-value" hidden={!showRaw} className="text-label font-normal text-ink-2">
        {raw}
      </span>
    </span>
  );
}

/** Chú thích đầu bảng (ĐP 01/11 14:50 điều kiện 4) — đúng chữ ĐP. */
export const RAW_NOTE = "Bảng hiển thị bằng nhãn dễ đọc. Bấm 'Hiện giá trị gốc' hoặc mở tab JSON để xem đúng dữ liệu hệ thống sẽ chạy.";
export const SHOW_RAW_TEXT = "Hiện giá trị gốc";

type Mode = "table" | "json";

export function ActionView({ action, hash, title }: { action: Record<string, unknown>; hash: string; title: string }) {
  const [mode, setMode] = useState<Mode>("table");
  const [copied, setCopied] = useState<"ok" | "fail" | null>(null);
  // Điều kiện 6: mặc định TẮT; state nằm trong component — màn phiếu dựng lại theo id (ApprovalDetailRoute key) → không nhớ sang phiếu khác.
  const [showRaw, setShowRaw] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied("ok");
    } catch {
      setCopied("fail"); // không có quyền clipboard → người dùng tự chọn (mã có `select-all`)
    }
  }

  const tab = (value: Mode, label: string) => (
    <button
      type="button"
      role="tab"
      id={`action-tab-${value}`}
      aria-selected={mode === value}
      aria-controls="action-panel"
      onClick={() => setMode(value)}
      className={`h-7 rounded-md px-3 text-label ${mode === value ? "bg-white text-ink shadow-input" : "font-normal text-ink"}`}
    >
      {label}
    </button>
  );

  return (
    <div className="overflow-hidden rounded-group border border-line">
      <div className="flex flex-col gap-1.5 border-b border-line px-5 py-4">
        <p className="text-heading">{title}</p>
        {/* Điều kiện 4: mã băm rút gọn + sao chép ngay đầu bảng; câu chú thích. Mã đủ vẫn ở chân bảng. */}
        <div className="flex items-center gap-2 text-label font-normal text-ink-2">
          <span>Mã băm</span>
          <code data-testid="action-hash-short" title={hash} className="font-mono text-ink">
            {hash.slice(0, 12)}…
          </code>
          <button type="button" onClick={() => void copy()} className="rounded-full bg-button-2 px-2.5 py-0.5 text-label text-fpt-blue">
            Sao chép
          </button>
        </div>
        <p data-testid="raw-note" className="text-label font-normal text-ink-2">
          {RAW_NOTE}
        </p>
      </div>
      <div className="flex items-center gap-3 border-b border-line bg-group px-5 py-2.5">
        <span className="grow text-secondary text-ink-2">Toàn bộ nội dung sẽ thực hiện (đã khoá bằng mã băm)</span>
        {mode === "table" ? (
          <button
            type="button"
            aria-pressed={showRaw}
            onClick={() => setShowRaw((v) => !v)}
            data-testid="show-raw"
            className={`h-7 shrink-0 rounded-md border px-3 text-label ${
              showRaw ? "border-fpt-blue bg-selected text-fpt-blue" : "border-line bg-white font-normal text-ink"
            }`}
          >
            {SHOW_RAW_TEXT}
          </button>
        ) : null}
        <div role="tablist" aria-label="Cách hiển thị hành động" className="flex rounded-lg bg-segmented p-0.5">
          {tab("table", "Bảng")}
          {tab("json", "JSON")}
        </div>
      </div>
      <div id="action-panel" role="tabpanel" aria-labelledby={`action-tab-${mode}`}>
        {mode === "table" ? (
          <FlatTable value={action} testId="action-row" keyLabel={actionKeyLabel} valueLabel={actionValueLabel} showRaw={showRaw} />
        ) : (
          <pre data-testid="action-json" className="overflow-x-auto px-5 py-4 font-mono text-label font-normal">
            {JSON.stringify(action, null, 2)}
          </pre>
        )}
      </div>
      <div className="flex flex-col gap-1.5 border-t border-line px-5 py-3">
        <div className="flex items-center gap-3">
          <span className="shrink-0 text-label text-ink-2">Mã băm</span>
          <code data-testid="action-hash" className="min-w-0 grow font-mono text-label font-normal break-all select-all">
            {hash}
          </code>
          <button
            type="button"
            onClick={() => void copy()}
            className="h-7.5 shrink-0 rounded-full bg-button-2 px-3.5 text-label text-fpt-blue"
          >
            Sao chép
          </button>
        </div>
        {copied ? (
          <span role="status" className="text-label font-normal text-ink-2">
            {copied === "ok" ? "Đã sao chép mã băm." : "Không sao chép được — chọn mã rồi sao chép thủ công."}
          </span>
        ) : null}
        <span className="text-label font-normal text-ink-2">
          Nội dung đổi sau khi duyệt thì hệ thống dừng và chuyển L2.
        </span>
      </div>
    </div>
  );
}
