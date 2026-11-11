import { type KeyboardEvent, type ReactNode, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** Giữ Tab / Shift+Tab trong hộp (kiểm thử 12/11: ở hộp "Từ chối", Tab đi ra trang phía sau — tới được nút "Đồng ý thực hiện"
 *  còn đang hiện dưới lớp phủ; người dùng bàn phím có thể ĐỒNG Ý trong khi tưởng đang ở hộp từ chối). */
function keepFocusInside(event: KeyboardEvent<HTMLDivElement>, box: HTMLDivElement | null): void {
  if (event.key !== "Tab" || box === null) return;
  const items = Array.from(box.querySelectorAll<HTMLElement>(FOCUSABLE));
  const first = items[0];
  const last = items[items.length - 1];
  if (first === undefined || last === undefined) {
    event.preventDefault();
    return;
  }
  const active = document.activeElement;
  const outside = !box.contains(active);
  if (event.shiftKey && (active === first || outside)) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && (active === last || outside)) {
    event.preventDefault();
    first.focus();
  }
}

// Sheet giữa màn bo 20 (Bản 4: sheet từ chối). Nền mờ đè cả trang; Esc = đóng (khi được phép); Tab không ra khỏi hộp.
export function Modal({ label, onClose, children }: { label: string; onClose?: () => void; children: ReactNode }) {
  const box = useRef<HTMLDivElement>(null);
  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-ink/25 px-4 motion-safe:animate-fade-in max-lg:py-4"
      onKeyDown={(e) => {
        if (e.key === "Escape" && onClose) onClose();
        keepFocusInside(e, box.current);
      }}
    >
      <div
        ref={box}
        role="dialog"
        aria-modal="true"
        aria-label={label}
        className="flex max-h-full w-120 max-w-full flex-col gap-4 overflow-y-auto rounded-sheet bg-white p-6 shadow-input motion-safe:animate-pop-in max-lg:p-4"
      >
        {children}
      </div>
    </div>
  );
}
