import { useEffect, useState } from "react";
import type { LogItem } from "../../api/events.ts";

// "Hệ thống đang xử lý": đầu khung tiến trình (nút thu gọn được, MẶC ĐỊNH ĐÓNG). Bên trong: lý do đã chuẩn hoá (`thought`), công cụ
// đã dùng (`tool_call`: tên thân thiện + kết quả, không tham số) và việc của từng ý khi yêu cầu nhiều ý. Chỉ hiện những gì server cho
// phép phát ra (danh sách trắng ở backend/app/api/events.py) — không suy luận thô, không mã luật.
// TA 14/11 ("thô kệch"): biểu tượng lấp lánh, bước hiện tại loang sáng, số giây đã xử lý, mũi tên xoay; chi tiết có biểu tượng theo
// loại (ý nghĩ · công cụ thành công / lỗi) trên một đường kẻ dọc.
// Mượt: thân hộp mở/đóng bằng chuyển động chiều cao (grid-template-rows 0fr ↔ 1fr, tắt khi giảm chuyển động); khi đóng, danh sách
// còn gắn tới hết chuyển động rồi mới gỡ. Danh sách giới hạn chiều cao + cuộn nên thêm bước không đẩy bố cục bên dưới.

/** Thời lượng chuyển động mở/đóng (ms) — khớp `duration-200`; quá hạn mà không có transitionend thì vẫn gỡ danh sách. */
export const THINKING_ANIM_MS = 200;

export const THINKING_TITLE = "Hệ thống đang xử lý";

/** "tkt-1-2" → "Ý 2"; id lạ → "Ý". */
const childLabel = (childId: string) => {
  const last = childId.split("-").pop() ?? "";
  return /^\d{1,2}$/.test(last) ? `Ý ${last}` : "Ý";
};

function LineIcon({ item }: { item: LogItem }) {
  if (item.kind === "tool_call") {
    return item.ok ? (
      <span className="inline-flex size-4 items-center justify-center rounded-full bg-done/15 text-done">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 12.5l4.5 4.5L19 7.5" />
        </svg>
      </span>
    ) : (
      <span className="inline-flex size-4 items-center justify-center rounded-full bg-orange-bg text-[10px] font-bold text-orange-ink">!</span>
    );
  }
  return <span className="mx-[5px] mt-[3px] inline-block size-1.5 rounded-full bg-ink-3" />;
}

function Line({ item }: { item: LogItem }) {
  const prefix = item.childId ? `${childLabel(item.childId)}: ` : "";
  return (
    <li data-kind={item.kind} className={`flex items-start gap-2.5 motion-safe:animate-rise-in ${item.kind === "thought" ? "text-ink-2 italic" : "text-ink"}`}>
      <span aria-hidden="true" className="mt-[3px] shrink-0 not-italic">
        <LineIcon item={item} />
      </span>
      {prefix}
      {item.kind === "tool_call" ? `${item.label} — ${item.ok ? "thành công" : "gặp lỗi"}` : item.label}
    </li>
  );
}

/** Số giây kể từ khi khung hiện ra (chỉ để người dùng thấy hệ thống vẫn đang chạy). */
function useElapsedSeconds(): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, []);
  return seconds;
}

export function ThinkingBox({ log, current }: { log: readonly LogItem[]; current?: string }) {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
  const seconds = useElapsedSeconds();
  useEffect(() => {
    if (!closing) return;
    const timer = setTimeout(() => setClosing(false), THINKING_ANIM_MS + 50);
    return () => clearTimeout(timer);
  }, [closing]);
  const toggle = () => {
    setClosing(open);
    setOpen(!open);
  };
  const mounted = open || closing;
  return (
    <section data-testid="thinking-box" data-open={open} className="flex flex-col text-secondary">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="thinking-box-body"
        onClick={toggle}
        className="group flex w-full items-center gap-2.5 rounded-group px-4 py-3 text-left hover:bg-group/70 focus-visible:outline-2 focus-visible:outline-fpt-blue max-lg:min-h-11"
      >
        <span aria-hidden="true" className="inline-flex size-5 shrink-0 items-center justify-center text-fpt-blue">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" className="motion-safe:animate-pulse">
            <path d="M12 2.5l1.9 5.6 5.6 1.9-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.9z" />
            <path d="M19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2-2.2-.8 2.2-.8z" opacity="0.6" />
          </svg>
        </span>
        <span className="shrink-0 font-semibold">{THINKING_TITLE}</span>
        {current && !open ? <span className="shimmer-text min-w-0 truncate font-normal">· {current}</span> : null}
        <span className="grow" />
        {seconds > 0 ? (
          <span aria-hidden="true" className="shrink-0 text-label font-normal text-ink-3 tabular-nums">
            {seconds} giây
          </span>
        ) : null}
        <svg
          aria-hidden="true"
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={`shrink-0 text-ink-2 transition-transform duration-200 ease-soft motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
        onTransitionEnd={() => setClosing(false)}
      >
        <div className="min-h-0 overflow-hidden">
          {mounted ? (
            <ul id="thinking-box-body" className="mx-4 mb-3 flex max-h-56 flex-col gap-2 overflow-y-auto border-l border-line py-1 pl-3.5">
              {log.length === 0 ? <li className="text-ink-2">Chưa có chi tiết.</li> : log.map((item, i) => <Line key={i} item={item} />)}
            </ul>
          ) : null}
        </div>
      </div>
    </section>
  );
}
