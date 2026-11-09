// Ô nhập trang chủ chat chỉ tự focus ở khổ ≥ 1024 px. Trên điện thoại, focus lúc mở trang bật bàn phím ảo ngay và che lời chào
// + nút gợi ý; nút gợi ý (người dùng vừa chạm) vẫn focus ô nhập như cũ. Không gọi mạng: ChatHome chưa gửi gì khi mới mở.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DESKTOP_QUERY } from "../../lib/viewport.ts";
import { ChatHome } from "./ChatHome.tsx";
import { SUGGESTIONS } from "./suggestions.ts";

afterEach(cleanup);

/** matchMedia giả: truy vấn khổ rộng trả `wide`, mọi truy vấn khác false. */
function viewport(wide: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: query === DESKTOP_QUERY ? wide : false,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
}

const mount = () =>
  render(
    <MemoryRouter>
      <ChatHome />
    </MemoryRouter>,
  );
const box = () => screen.getByLabelText("Mô tả vấn đề") as HTMLTextAreaElement;

describe("trang chủ chat: tự focus ô nhập", () => {
  it("khổ ≥ 1024 px: ô nhập có tiêu điểm ngay khi mở trang", () => {
    viewport(true);
    mount();
    expect(document.activeElement).toBe(box());
  });

  it("khổ < 1024 px: KHÔNG tự focus (không bật bàn phím ảo)", () => {
    viewport(false);
    mount();
    expect(document.activeElement).not.toBe(box());
    expect(document.activeElement === document.body || document.activeElement === null).toBe(true);
  });

  it("khổ < 1024 px: chạm nút gợi ý vẫn điền câu mẫu và focus ô nhập", () => {
    viewport(false);
    mount();
    const sample = SUGGESTIONS[0]!;
    fireEvent.click(screen.getByRole("button", { name: sample.label }));
    expect(box().value).toBe(sample.text);
    expect(document.activeElement).toBe(box());
  });

  it("không có matchMedia: giữ hành vi cũ (tự focus)", () => {
    vi.stubGlobal("matchMedia", undefined);
    mount();
    expect(document.activeElement).toBe(box());
  });
});
