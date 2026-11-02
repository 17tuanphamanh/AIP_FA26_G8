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
