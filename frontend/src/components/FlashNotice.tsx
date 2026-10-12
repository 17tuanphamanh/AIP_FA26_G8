import { useLocation } from "react-router";
import { flashText } from "./flash.ts";

/** Dải thông báo đầu vùng nội dung cho mã flash trong history state (components/flash.ts). */
export function FlashNotice() {
  const text = flashText(useLocation().state);
  if (text === null) return null;
  return (
    <p role="status" data-testid="flash" className="mx-12 mt-6 rounded-group bg-orange-bg px-5 py-3.5 text-orange-ink">
      {text}
    </p>
  );
}
