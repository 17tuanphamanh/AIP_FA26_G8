// L2 (soát 01/11, ĐP 02/11): ô chat cắt im lặng ở maxLength khi dán → bộ đếm "n/max" gần giới hạn + câu báo khi chạm.
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { Composer } from "./Composer.tsx";

afterEach(cleanup);

function Harness({ initial = "", max = 4000 }: { initial?: string; max?: number }) {
  const [value, setValue] = useState(initial);
  return <Composer variant="chat" label="Ô chat" placeholder="" value={value} onChange={setValue} onSubmit={() => {}} maxLength={max} />;
}

describe("Composer — bộ đếm ký tự (L2)", () => {
  it("dưới 3500/4000 → không có bộ đếm", () => {
    render(<Harness initial={"a".repeat(3499)} />);
    expect(screen.queryByTestId("composer-counter")).toBeNull();
  });

  it("từ 3500 → 'n/4000', chưa có câu giới hạn; không aria-describedby", () => {
    render(<Harness initial={"a".repeat(3500)} />);
    expect(screen.getByTestId("composer-counter").textContent).toBe("3500/4000");
    expect(screen.getByLabelText("Ô chat").getAttribute("aria-describedby")).toBeNull();
  });

  it("chạm 4000 (dán dài bị cắt) → '4000/4000 · Đã tới giới hạn…', gắn aria-describedby vào ô", () => {
    render(<Harness />);
    const box = screen.getByLabelText("Ô chat");
    fireEvent.change(box, { target: { value: "b".repeat(4000) } });
    const counter = screen.getByTestId("composer-counter");
    expect(counter.textContent).toBe("4000/4000 · Đã tới giới hạn — phần dán thêm bị bỏ.");
    expect(box.getAttribute("aria-describedby")).toBe(counter.id);
    expect(box.getAttribute("maxlength")).toBe("4000");
  });

  it("ô ghi chú 1000 → ngưỡng 875", () => {
    render(<Harness initial={"c".repeat(875)} max={1000} />);
    expect(screen.getByTestId("composer-counter").textContent).toBe("875/1000");
  });
});

describe("Composer — chỉ ký tự vô hình không gửi được (kiểm thử 12/11)", () => {
  function Sender({ initial }: { initial: string }) {
    const [value, setValue] = useState(initial);
    const [sent, setSent] = useState(0);
    return (
      <>
        <Composer variant="chat" label="Ô chat" placeholder="" value={value} onChange={setValue} onSubmit={() => setSent((n) => n + 1)} maxLength={4000} />
        <output data-testid="sent">{sent}</output>
      </>
    );
  }

  it.each([["   "], ["​​"], ["­ ⁠﻿"], ["\n​\t"]])("%j → nút Gửi khoá, Enter không gửi", (text) => {
    render(<Sender initial={text} />);
    const send = screen.getByRole("button", { name: "Gửi" });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(screen.getByLabelText("Ô chat"), { key: "Enter" });
    fireEvent.click(send);
    expect(screen.getByTestId("sent").textContent).toBe("0");
  });

  it("còn một chữ nhìn thấy (kể cả kèm zero-width) → gửi được", () => {
    render(<Sender initial={"​VPN​"} />);
    const send = screen.getByRole("button", { name: "Gửi" });
    expect((send as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(send);
    expect(screen.getByTestId("sent").textContent).toBe("1");
  });
});

describe("Bong bóng chat ngắt chuỗi dài (kiểm thử 12/11)", () => {
  it("USER_BUBBLE có wrap-anywhere ở mọi khổ (không chỉ dưới 1024 px)", async () => {
    const { USER_BUBBLE } = await import("./Conversation.tsx");
    expect(USER_BUBBLE.split(" ")).toContain("wrap-anywhere");
  });
});
