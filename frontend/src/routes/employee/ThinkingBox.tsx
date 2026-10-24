import { useEffect, useState } from "react";
import type { LogItem } from "../../api/events.ts";

// "Hệ thống đang xử lý": khung thu gọn được, MẶC ĐỊNH ĐÓNG. Bên trong: lý do đã chuẩn hoá (`thought`), công cụ đã dùng
// (`tool_call`: tên thân thiện + kết quả, không tham số) và việc của từng ý khi yêu cầu nhiều ý. Chỉ hiện những gì server cho
// phép phát ra (danh sách trắng ở backend/app/api/events.py) — không suy luận thô, không mã luật.
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

function Line({ item }: { item: LogItem }) {
  const prefix = item.childId ? `${childLabel(item.childId)}: ` : "";
  return (
    <li data-kind={item.kind} className={item.kind === "thought" ? "text-ink-2 italic" : ""}>
      {prefix}
      {item.kind === "tool_call" ? `${item.label} — ${item.ok ? "thành công" : "gặp lỗi"}` : item.label}
    </li>
  );
}

export function ThinkingBox({ log, current }: { log: readonly LogItem[]; current?: string }) {
  const [open, setOpen] = useState(false);
  const [closing, setClosing] = useState(false);
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
    <section data-testid="thinking-box" data-open={open} className="flex flex-col rounded-sheet bg-group px-4 py-3 text-secondary">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="thinking-box-body"
        onClick={toggle}
        className="flex items-center gap-2 text-left font-semibold"
      >
        <span aria-hidden="true" className={`inline-block transition-transform duration-200 motion-reduce:transition-none ${open ? "rotate-90" : ""}`}>
          ▸
        </span>
        <span>{THINKING_TITLE}</span>
        {current && !open ? <span className="min-w-0 truncate font-normal text-ink-2">· {current}</span> : null}
      </button>
      <div
        className="grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none"
        style={{ gridTemplateRows: open ? "1fr" : "0fr" }}
        onTransitionEnd={() => setClosing(false)}
      >
        <div className="min-h-0 overflow-hidden">
          {mounted ? (
            <ul id="thinking-box-body" className="mt-2 flex max-h-48 flex-col gap-1 overflow-y-auto pl-5">
              {log.length === 0 ? <li className="text-ink-2">Chưa có chi tiết.</li> : log.map((item, i) => <Line key={i} item={item} />)}
            </ul>
          ) : null}
        </div>
      </div>
    </section>
  );
}
