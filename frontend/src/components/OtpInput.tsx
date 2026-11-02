import { type ClipboardEvent, type KeyboardEvent, useEffect, useRef } from "react";

export const OTP_LENGTH = 6;

type OtpInputProps = {
  digits: string[];
  onChange: (digits: string[]) => void;
  disabled?: boolean;
  /** Đổi giá trị → đưa con trỏ về ô đầu (sau khi hết `disabled`) — dùng khi sai mã, 6 ô đã xoá trắng. */
  focusKey?: number;
};

// Mã TOTP 6 số, mỗi số một ô (B4Login bước OTP). Gõ → sang ô sau; Backspace ở ô trống → về ô trước;
// dán cả mã → rải vào các ô. Ô đầu có autocomplete="one-time-code" để trình duyệt/điện thoại tự điền.
export function OtpInput({ digits, onChange, disabled, focusKey = 0 }: OtpInputProps) {
  const refs = useRef<(HTMLInputElement | null)[]>([]);
  const focused = useRef(focusKey); // lần dựng đầu: autoFocus lo
  useEffect(() => {
    if (disabled || focused.current === focusKey) return;
    focused.current = focusKey;
    refs.current[0]?.focus();
  }, [focusKey, disabled]);

  function fill(start: number, raw: string) {
    const incoming = raw.replace(/\D/g, "").slice(0, OTP_LENGTH - start).split("");
    if (incoming.length === 0) return;
    const next = [...digits];
    incoming.forEach((d, i) => (next[start + i] = d));
    onChange(next);
    refs.current[Math.min(start + incoming.length, OTP_LENGTH - 1)]?.focus();
  }

  function onKeyDown(index: number, event: KeyboardEvent<HTMLInputElement>) {
    if (event.key !== "Backspace") return;
    event.preventDefault();
    const next = [...digits];
    if (next[index]) {
      next[index] = "";
    } else if (index > 0) {
      next[index - 1] = "";
      refs.current[index - 1]?.focus();
    }
    onChange(next);
  }

  function onPaste(index: number, event: ClipboardEvent<HTMLInputElement>) {
    event.preventDefault();
    fill(index, event.clipboardData.getData("text"));
  }

  return (
    <div className="flex gap-2" role="group" aria-label="Mã xác thực 6 số">
      {Array.from({ length: OTP_LENGTH }, (_, i) => (
        <input
          key={i}
          ref={(el) => {
            refs.current[i] = el;
          }}
          aria-label={`Chữ số ${i + 1}`}
          value={digits[i] ?? ""}
          onFocus={(e) => e.target.select()}
          onChange={(e) => {
            const raw = e.target.value.replace(/\D/g, "");
            // gõ đè lên ô đã có số → lấy số vừa gõ; tự điền / dán nhiều số → rải ra các ô sau
            fill(i, raw.length === 2 && digits[i] ? raw.slice(-1) : raw);
          }}
          onKeyDown={(e) => onKeyDown(i, e)}
          onPaste={(e) => onPaste(i, e)}
          inputMode="numeric"
          autoComplete={i === 0 ? "one-time-code" : "off"}
          autoFocus={i === 0}
          disabled={disabled}
          className="h-16 w-14 rounded-xl border border-line bg-white text-center text-heading focus-visible:outline-2 focus-visible:outline-fpt-blue"
        />
      ))}
    </div>
  );
}
