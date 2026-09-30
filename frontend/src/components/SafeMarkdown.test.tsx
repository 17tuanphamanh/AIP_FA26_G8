// t21: Markdown của tin `answer` (KH 4.1 #5) — HTML thô hiện thành CHỮ, không thẻ nào sinh ra; ảnh / link lạ bị lọc.
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { SafeMarkdown } from "./SafeMarkdown.tsx";

afterEach(cleanup);

describe("t21: SafeMarkdown lọc HTML", () => {
  it.each([
    "<img src=x onerror=alert(1)>",
    "<script>alert(1)</script>",
    '<a href="javascript:alert(1)">bấm</a>',
  ])("HTML thô %s → hiện như chữ, không có thẻ img/script/a", (html) => {
    const { container } = render(<SafeMarkdown text={html} />);
    expect(container.querySelector("img, script, a, iframe")).toBeNull();
    expect(container.textContent).toContain(html);
  });

  it("ảnh Markdown ![](https://…) → không có thẻ img (không tải gì từ máy chủ ngoài)", () => {
    const { container } = render(<SafeMarkdown text="Xem ảnh ![sơ đồ](https://attacker.example/x.png) nhé" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("Xem ảnh");
  });

  it("link: chỉ http(s)/mailto giữ href, mở tab mới noopener; javascript: bị bỏ href", () => {
    const { container } = render(
      <SafeMarkdown text="[KB](https://kb.example/vpn) và [bẫy](javascript:alert(1)) và [dữ liệu](data:text/html,x)" />,
    );
    const links = [...container.querySelectorAll("a")];
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["https://kb.example/vpn"]);
    expect(links[0]?.getAttribute("target")).toBe("_blank");
    expect(links[0]?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(container.textContent).toContain("bẫy");
  });

  it("Markdown thường vẫn hiện đúng (danh sách, đậm)", () => {
    const { container } = render(<SafeMarkdown text={"Làm hai bước:\n\n1. Mở **ABC Connect**\n2. Kết nối lại"} />);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
    expect(container.querySelector("strong")?.textContent).toBe("ABC Connect");
  });
});
