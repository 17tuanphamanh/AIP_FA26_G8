// Kiểm thử 12/11 (máy demo): ở hộp "Từ chối" của L1, Tab đi ra trang phía sau — tới được nút "Đồng ý thực hiện" vẫn hiện dưới lớp phủ.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Modal } from "./Modal.tsx";

afterEach(cleanup);

function Page() {
  return (
    <>
      <button type="button">Đồng ý thực hiện</button>
      <Modal label="Từ chối" onClose={() => {}}>
        <textarea aria-label="Lý do" />
        <button type="button">Huỷ</button>
        <button type="button">Gửi từ chối</button>
      </Modal>
    </>
  );
}

describe("Modal — Tab không ra khỏi hộp", () => {
  it("Tab ở nút cuối → về ô đầu; Shift+Tab ở ô đầu → về nút cuối; không bao giờ tới nút phía sau", () => {
    render(<Page />);
    const first = screen.getByLabelText("Lý do");
    const last = screen.getByRole("button", { name: "Gửi từ chối" });
    last.focus();
    fireEvent.keyDown(last, { key: "Tab" });
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(first, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
    expect(document.activeElement).not.toBe(screen.getByRole("button", { name: "Đồng ý thực hiện" }));
  });

  it("Tab ở giữa hộp để trình duyệt tự chuyển (không chặn)", () => {
    render(<Page />);
    const middle = screen.getByRole("button", { name: "Huỷ" });
    middle.focus();
    const ev = fireEvent.keyDown(middle, { key: "Tab" });
    expect(ev).toBe(true); // không preventDefault
  });
});
