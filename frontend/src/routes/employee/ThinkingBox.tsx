import { useState } from "react";
import type { LogItem } from "../../api/events.ts";

// "Hệ thống đang xử lý": khung thu gọn được, MẶC ĐỊNH ĐÓNG. Bên trong: lý do đã chuẩn hoá (`thought`), công cụ đã dùng
// (`tool_call`: tên thân thiện + kết quả, không tham số) và việc của từng ý khi yêu cầu nhiều ý. Chỉ hiện những gì server cho
// phép phát ra (danh sách trắng ở backend/app/api/events.py) — không suy luận thô, không mã luật.

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
  return (
    <section data-testid="thinking-box" data-open={open} className="flex flex-col gap-2 rounded-sheet bg-group px-4 py-3 text-secondary">
      <button
        type="button"
        aria-expanded={open}
        aria-controls="thinking-box-body"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 text-left font-semibold"
      >
        <span aria-hidden="true">{open ? "▾" : "▸"}</span>
        <span>{THINKING_TITLE}</span>
        {current && !open ? <span className="truncate font-normal text-ink-2">· {current}</span> : null}
      </button>
      {open ? (
        <ul id="thinking-box-body" className="flex flex-col gap-1 pl-5">
          {log.length === 0 ? <li className="text-ink-2">Chưa có chi tiết.</li> : log.map((item, i) => <Line key={i} item={item} />)}
        </ul>
      ) : null}
    </section>
  );
}
