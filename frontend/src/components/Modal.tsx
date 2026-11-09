import type { ReactNode } from "react";

// Sheet giữa màn bo 20 (Bản 4: sheet từ chối). Nền mờ đè cả trang; Esc = đóng (khi được phép).
export function Modal({ label, onClose, children }: { label: string; onClose?: () => void; children: ReactNode }) {
  return (
    <div
      className="fixed inset-0 z-20 flex items-center justify-center bg-ink/25 px-4 motion-safe:animate-fade-in max-lg:py-4"
      onKeyDown={(e) => {
        if (e.key === "Escape" && onClose) onClose();
      }}
    >
      <div
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
