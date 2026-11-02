import { useLayoutEffect, useRef } from "react";

type PasswordFieldProps = {
  id: string;
  name?: string;
  value: string;
  onChange: (value: string) => void;
  /** true = đang hiện chữ (type="text"). State nằm ở `useLoginSteps` — hook tự ẩn lại khi gửi / lỗi / xong / đóng. */
  shown: boolean;
  onToggle: () => void;
  /** Lớp riêng của ô nhập (nền, viền, outline) — giữ đúng như ô cũ của từng nơi dùng. */
  inputClassName: string;
};

// Ô mật khẩu + nút hiện/ẩn (gói fe-login-sua). Dùng ở màn đăng nhập (F1) và hộp xác nhận lại đăng nhập (F4).
// - Nút `type="button"`: KHÔNG gửi form; biểu tượng con mắt (đang ẩn → mắt mở = bấm để hiện; đang hiện → mắt gạch);
//   tên đọc cho trình đọc màn hình ở aria-label ("Hiện mật khẩu" / "Ẩn mật khẩu") + aria-pressed; vùng bấm 44×44.
// - Đổi type password ↔ text trên CÙNG một phần tử: giá trị giữ nguyên; vị trí con trỏ / vùng chọn khôi phục sau khi đổi.
// - autocomplete giữ `current-password` ở cả hai trạng thái.
export function PasswordField({ id, name, value, onChange, shown, onToggle, inputClassName }: PasswordFieldProps) {
  const input = useRef<HTMLInputElement>(null);
  const selection = useRef<[number, number] | null>(null);

  useLayoutEffect(() => {
    const saved = selection.current;
    selection.current = null;
    if (saved && input.current) {
      try {
        input.current.setSelectionRange(saved[0], saved[1]);
      } catch {
        // Trình duyệt không cho đặt vùng chọn → bỏ qua, giá trị vẫn giữ nguyên.
      }
    }
  }, [shown]);

  function toggle() {
    const el = input.current;
    if (el && el.selectionStart !== null && el.selectionEnd !== null) selection.current = [el.selectionStart, el.selectionEnd];
    onToggle();
  }

  return (
    <div className="flex items-center bg-white pr-1">
      <input
        ref={input}
        id={id}
        name={name}
        type={shown ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Mật khẩu"
        autoComplete="current-password"
        autoCapitalize="none"
        spellCheck={false}
        className={`min-w-0 flex-1 ${inputClassName}`}
      />
      <button
        type="button"
        onClick={toggle}
        aria-label={shown ? "Ẩn mật khẩu" : "Hiện mật khẩu"}
        aria-pressed={shown}
        aria-controls={id}
        className="flex size-11 shrink-0 items-center justify-center rounded-full text-ink-2 hover:bg-group hover:text-ink focus-visible:outline-2 focus-visible:outline-fpt-blue"
      >
        <EyeIcon off={shown} />
      </button>
    </div>
  );
}

/** Con mắt (bấm để hiện) / con mắt gạch chéo (bấm để ẩn). Thuần trang trí — tên nút nằm ở aria-label. */
function EyeIcon({ off }: { off: boolean }) {
  return (
    <svg viewBox="0 0 24 24" className="size-5 fill-none stroke-current" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
      <path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" />
      <circle cx="12" cy="12" r="3" />
      {off ? <path d="M4 4l16 16" /> : null}
    </svg>
  );
}
