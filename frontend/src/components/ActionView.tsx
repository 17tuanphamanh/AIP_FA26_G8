import { useState } from "react";
import {
  actionValueLabel,
  EMPTY_TEXT,
  flatKeyLabel,
  IDENTITY_KEYS,
  needsRawFormat,
  NULL_TEXT,
  RAW_FORMAT_NOTE,
  ASCII_IDENTITY_KEYS,
  hasNonAscii,
  safeJsonText,
  targetParts,
  visibleJson,
} from "../routes/l1/actionLabels.ts";
import { ACTION_KEY_LABEL, flattenEntries, isShortValue } from "../routes/l1/inbox.ts";

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
}: {
  value: unknown;
  testId: string;
  keyLabel?: (key: string) => string | null;
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
              {entry.value}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

// ---- Bảng hành động của phiếu duyệt (B2, ĐP 01/11 14:50 + 15:00 + 15:35; Project claude/bang-nhan-b2-01-11.md mục 0, 0c) ----
// TẮT (mặc định): chỉ chữ người đọc được — khoá có nhãn chỉ hiện nhãn; giá trị có nhãn chỉ hiện nhãn; chuỗi không nhãn hiện nội
// dung không ngoặc kép. BẬT: khoá gốc + JSON.stringify từng dòng. Mọi phần tử gốc LUÔN trong DOM (`hidden` khi tắt) — test so
// từng ký tự. Đủ mọi khoá, đúng thứ tự `flattenEntries`, không gộp/ẩn/sắp lại dòng.

/** Nhãn khoá CHÍNH XÁC (1-1). Khoá chỉ khớp nhãn nhóm ("Dữ kiện" cho facts.<lạ>) không tính — (a): hiện khoá gốc kể cả khi tắt. */
function exactKeyLabel(key: string): string | null {
  const full = flatKeyLabel(key);
  if (full !== null) return full;
  return /^[a-z_]+$/.test(key) && Object.hasOwn(ACTION_KEY_LABEL, key) ? ACTION_KEY_LABEL[key]! : null;
}

/** Nhãn nhóm cho khoá lạ trong nhóm đã biết (params.<lạ>, facts.<lạ>) — hiện kèm khoá gốc, không thay. */
function groupLabel(key: string): string | null {
  const head = key.split(/[.[]/)[0] ?? "";
  return key !== head && Object.hasOwn(ACTION_KEY_LABEL, head) ? ACTION_KEY_LABEL[head]! : null;
}

function ActionKey({ entryKey, showRaw }: { entryKey: string; showRaw: boolean }) {
  const exact = exactKeyLabel(entryKey);
  if (exact !== null) {
    return (
      <>
        <span className="font-sans">{exact}</span>
        <span data-testid="raw-key" hidden={!showRaw}>
          {" · "}
          <span className="text-label font-normal">{safeJsonText(entryKey)}</span>
        </span>
      </>
    );
  }
  const group = groupLabel(entryKey);
  return group !== null ? (
    <>
      <span className="font-sans">{group}</span> · <span className="text-label font-normal">{safeJsonText(entryKey)}</span>
    </>
  ) : (
    <>{entryKey ? safeJsonText(entryKey) : "(gốc)"}</>
  );
}

/** Chữ hiện khi TẮT cho giá trị KHÔNG nhãn. `rawFormat` = (c): hiện nguyên JSON.stringify + chú thích. */
function plainDisplay(raw: string, key: string): { text: string; rawFormat: boolean } {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return { text: raw, rawFormat: false }; // "undefined" hay dạng lạ → nguyên văn
  }
  if (value === null) return { text: NULL_TEXT, rawFormat: false }; // (b)
  if (typeof value === "string") {
    if (value === "") return { text: EMPTY_TEXT, rawFormat: false }; // (b)
    // (c). `target`: phần sau ":" là danh tính → xét riêng phần đó (vd "device: LAP" có khoảng trắng đầu ở phần sau).
    const suffix = key === "target" && value.includes(":") ? value.slice(value.indexOf(":") + 1) : "";
    // (h) danh tính ASCII: requested_for, device_id, phần sau ":" của target có ký tự ngoài ASCII → dạng gốc, escape \uXXXX.
    const ascii = ASCII_IDENTITY_KEYS.has(key) && hasNonAscii(key === "target" ? suffix || value : value);
    const unsafe = ascii || needsRawFormat(value) || (suffix !== "" && needsRawFormat(suffix));
    return unsafe ? { text: visibleJson(value, ascii), rawFormat: true } : { text: value, rawFormat: false };
  }
  return { text: raw, rawFormat: false }; // (e) số, bool, {} / [] → nguyên giá trị
}

function ActionValue({ entryKey, raw, showRaw }: { entryKey: string; raw: string; showRaw: boolean }) {
  const label = actionValueLabel(entryKey, raw);
  const target = entryKey === "target" ? targetParts(raw) : null;
  const identity = IDENTITY_KEYS.has(entryKey);
  const rawEl = (
    <span data-testid="raw-value" hidden={!showRaw} className={label !== null ? "text-label font-normal text-ink-2" : undefined}>
      {safeJsonText(raw, ASCII_IDENTITY_KEYS.has(entryKey))}
    </span>
  );
  if (label !== null) {
    return (
      <span className="inline-flex flex-col items-end">
        <span data-testid="value-label" className="font-sans text-ink">
          {target ? (
            <>
              {target.prefix} <span className="font-mono">{target.rest}</span>
            </>
          ) : (
            label
          )}
        </span>
        {rawEl}
      </span>
    );
  }
  const shown = plainDisplay(raw, entryKey);
  return (
    <>
      <span data-testid="display-value" hidden={showRaw} className={identity || entryKey === "target" || shown.rawFormat ? "font-mono" : "font-sans"}>
        {shown.text}
        {shown.rawFormat ? (
          <span data-testid="raw-format-note" className="ml-2 font-sans text-label font-normal text-ink-2">
            {RAW_FORMAT_NOTE}
          </span>
        ) : null}
      </span>
      {rawEl}
    </>
  );
}

function ActionTable({ action, showRaw }: { action: Record<string, unknown>; showRaw: boolean }) {
  return (
    <dl className="font-mono text-secondary">
      {flattenEntries(action).map((entry) => {
        const short = isShortValue(entry.value);
        return (
          <div
            key={entry.key}
            data-testid="action-row"
            data-key={entry.key}
            className={`flex justify-between border-t border-line px-5 py-2.5 first:border-t-0 ${short ? "flex-wrap gap-x-4 gap-y-1" : "gap-4"}`}
          >
            <dt className="shrink-0 text-ink-2">
              <ActionKey entryKey={entry.key} showRaw={showRaw} />
            </dt>
            <dd className={`min-w-0 text-right wrap-anywhere break-normal${short ? " ml-auto max-w-full" : ""}`}>
              <ActionValue entryKey={entry.key} raw={entry.value} showRaw={showRaw} />
            </dd>
          </div>
        );
      })}
    </dl>
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
        <h3 className="sr-only">{title}</h3>
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
        <span className="grow" />
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
          <ActionTable action={action} showRaw={showRaw} />
        ) : (
          <pre data-testid="action-json" className="overflow-x-auto px-5 py-4 font-mono text-label font-normal">
            {/* Mục 0d: cùng hàm hiển thị an toàn — ký tự vô hình hiện \uXXXX; object sạch → === JSON.stringify(action, null, 2). */}
            {safeJsonText(JSON.stringify(action, null, 2))}
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
