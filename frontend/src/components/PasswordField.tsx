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
// - Nút `type="button"`: KHÔNG gửi form; aria-label đổi theo trạng thái + aria-pressed; cao 44 (h-11) như nút viên thuốc.
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
        className="h-11 min-w-11 shrink-0 rounded-full px-3 text-secondary font-semibold text-fpt-blue focus-visible:outline-2 focus-visible:outline-fpt-blue"
      >
        {shown ? "Ẩn" : "Hiện"}
      </button>
    </div>
  );
}
