// Chuỗi chiều cao của khung (sửa lỗi sau commit 0eb24d8): vỏ nội dung `ref={content}` nằm giữa `main` và màn; thiếu `h-full` thì
// `h-full` / `min-h-full` của chat, phiếu duyệt, trang chủ chat tính ra "auto" và ô nhập / thanh quyết định không còn dính
// đáy. happy-dom không có bố cục → kiểm chữ trong mã nguồn; bố cục thật do e2e/khung-dinh-day.e2e.ts.
import { describe, expect, it } from "vitest";
import app from "./App.tsx?raw";

describe("khung ứng dụng", () => {
  const wrapper = /<div ref=\{content\} className="([^"]*)"/.exec(app)?.[1];

  it("vỏ nội dung có h-full và tự cuộn (overflow-y-auto)", () => {
    expect(wrapper, "không thấy vỏ nội dung `ref={content}` trong App.tsx").toBeDefined();
    const tokens = (wrapper ?? "").split(/\s+/);
    expect(tokens).toContain("h-full");
    expect(tokens).toContain("overflow-y-auto");
  });
});
