import { type KeyboardEvent, type ReactNode, type Ref, useId } from "react";

type ComposerProps = {
  /** Nhãn cho trình đọc màn hình (ẩn). */
  label: string;
  placeholder: string;
  value: string;
  onChange: (value: string) => void;
  /** Không truyền → không có nút gửi, Enter không gửi (vd ô ghi chú khi chờ xác nhận). */
  onSubmit?: () => void;
  maxLength: number;
  disabled?: boolean;
  busy?: boolean;
  /** Lỗi tại ô (422 / 413) — gắn `aria-invalid` + `aria-describedby`. */
  error?: string | null;
  /** Dòng nhỏ bên trái nút gửi (trang đầu: "Mật khẩu lỡ gõ sẽ được tự động ẩn"). */
  hint?: ReactNode;
  variant: "home" | "chat";
  autoFocus?: boolean;
  /** Ô nhập — để trang đặt focus (vd sau khi bấm nút gợi ý nhanh). */
  inputRef?: Ref<HTMLTextAreaElement>;
};

function SendIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 19V5M6 11l6-6 6 6" />
    </svg>
  );
}

// Ô nhập B4EmpHome (lớn, bo 24) / B4EmpChat (một dòng, dính đáy). Enter gửi, Shift+Enter xuống dòng; đang gõ dấu
// tiếng Việt (IME đang ghép chữ) thì Enter KHÔNG gửi.
export function Composer({ inputRef, ...props }: ComposerProps) {
  const id = useId();
  const errorId = `${id}-error`;
  const canSend = !!props.onSubmit && !props.disabled && !props.busy && props.value.trim().length > 0;

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    if (canSend) props.onSubmit?.();
  }

  const home = props.variant === "home";
  return (
    <div className="flex flex-col gap-1.5">
      <div
        className={
          home
            ? "flex flex-col gap-3 rounded-input border border-line bg-white py-5 pr-5 pb-3 pl-6 shadow-input"
            : "flex items-end gap-2 rounded-input border border-line bg-white py-2 pr-2 pl-5 shadow-input"
        }
      >
        <label htmlFor={id} className="sr-only">
          {props.label}
        </label>
        <textarea
          ref={inputRef}
          id={id}
          rows={home ? 2 : 1}
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder={props.placeholder}
          maxLength={props.maxLength}
          disabled={props.disabled}
          autoFocus={props.autoFocus}
          aria-invalid={props.error ? true : undefined}
          aria-describedby={props.error ? errorId : undefined}
          className={`resize-none bg-transparent placeholder:text-ink-2 focus-visible:outline-none disabled:text-ink-2 ${
            home ? "w-full" : "max-h-40 min-h-10 grow py-2"
          }`}
        />
        {props.onSubmit ? (
          <div className={home ? "flex items-center gap-2" : "contents"}>
            {home ? <span className="grow">{props.hint}</span> : null}
            <button
              type="button"
              aria-label="Gửi"
              onClick={() => canSend && props.onSubmit?.()}
              disabled={!canSend}
              className="flex size-10 shrink-0 items-center justify-center rounded-full bg-send text-white disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-fpt-blue"
            >
              <SendIcon />
            </button>
          </div>
        ) : null}
      </div>
      {props.error ? (
        <p id={errorId} role="alert" className="px-5 text-label font-normal text-danger">
          {props.error}
        </p>
      ) : null}
    </div>
  );
}
