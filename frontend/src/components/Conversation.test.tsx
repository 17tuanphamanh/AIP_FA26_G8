// t22: hội thoại theo `kind` (12b Q-fe-2) — kind lạ hiện như tin thường, phần tử hỏng bị bỏ, không throw.
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Conversation } from "./Conversation.tsx";
import { normalizeConversation, stripSourcesBlock } from "./messages.ts";

afterEach(cleanup);

// t27 (12b Q-fe-19): khối "Nguồn:" backend nối vào cuối câu trả lời (domain/answer.py render_answer) trùng ô nguồn →
// cắt CHỈ khi khớp đúng từng ký tự; lệch một ký tự → giữ nguyên (lặp chấp nhận được, mất nguồn thì không).
describe("t27: cắt khối Nguồn: lặp", () => {
  const vpn = { chunk_id: "KB-VPN-001#v1#1", title: "Tổng quan dịch vụ VPN", heading_path: "Địa chỉ máy chủ và cổng kết nối" };
  const block = "Nguồn:\n- Tổng quan dịch vụ VPN › Địa chỉ máy chủ và cổng kết nối";

  it("khớp đúng → cắt (có bước đánh số; nguồn trùng chuỗi chỉ một dòng; câu chỉ có khối nguồn → rỗng)", () => {
    expect(stripSourcesBlock(`VPN dùng IKEv2.\n\n${block}`, [vpn])).toBe("VPN dùng IKEv2.");
    expect(stripSourcesBlock(`Làm như sau.\n\n1. Mở ABC Connect\n2. Kết nối lại\n\n${block}`, [vpn])).toBe(
      "Làm như sau.\n\n1. Mở ABC Connect\n2. Kết nối lại",
    );
    expect(stripSourcesBlock(`VPN dùng IKEv2.\n\n${block}`, [vpn, { ...vpn, chunk_id: "KB-VPN-001#v1#2" }])).toBe(
      "VPN dùng IKEv2.",
    );
    expect(stripSourcesBlock(block, [vpn])).toBe("");
  });

  it.each([
    ["dấu phân cách khác", `VPN dùng IKEv2.\n\nNguồn:\n- Tổng quan dịch vụ VPN > Địa chỉ máy chủ và cổng kết nối`],
    ["tiêu đề lệch một ký tự", `VPN dùng IKEv2.\n\nNguồn:\n- Tổng quan dịch vụ VPn › Địa chỉ máy chủ và cổng kết nối`],
    ["thừa khoảng trắng cuối", `VPN dùng IKEv2.\n\n${block} `],
    ["tiêu đề khối khác", `VPN dùng IKEv2.\n\nNguồn :\n- Tổng quan dịch vụ VPN › Địa chỉ máy chủ và cổng kết nối`],
    ["thiếu dòng trống trước khối", `VPN dùng IKEv2.\n${block}`],
  ])("lệch (%s) → giữ nguyên", (_label, text) => {
    expect(stripSourcesBlock(text, [vpn])).toBe(text);
  });

  it("trên màn: tin answer không còn dòng \"Nguồn:\", ô nguồn vẫn có", () => {
    const messages = normalizeConversation([{ role: "assistant", kind: "answer", text: `VPN dùng IKEv2.\n\n${block}`, sources: [vpn] }]);
    const { container } = render(<Conversation messages={messages} />);
    const answer = container.querySelector('[data-kind="answer"]');
    expect(answer?.textContent).not.toContain("Nguồn:");
    expect(answer?.querySelectorAll('[data-testid="source"]')).toHaveLength(1);
  });
});

describe("t22: Conversation", () => {
  it("kind lạ → hiện text như tin thường; dữ liệu hỏng bị bỏ; không throw", () => {
    const raw: unknown = [
      { role: "user", text: "VPN công ty dùng cổng nào?" },
      { role: "assistant", kind: "kieu_moi_cua_backend", text: "Tin kiểu mới" },
      null,
      42,
      "chuỗi trần",
      [],
      { role: "assistant" }, // thiếu text → bỏ
      { role: "assistant", kind: "question", text: 12 },
      { role: "assistant", kind: { lạ: true }, text: "kind không phải chuỗi" },
      {
        role: "assistant",
        kind: "answer",
        text: "Dùng **IKEv2**.",
        sources: [{ chunk_id: "KB-VPN-001#v1#1", title: "Tổng quan dịch vụ VPN", heading_path: "Cổng kết nối" }, { hỏng: 1 }, null],
      },
      { role: "assistant", kind: "escalation", text: "Mình chuyển cho kỹ thuật viên." },
    ];
    const messages = normalizeConversation(raw);
    expect(messages.map((m) => m.kind)).toEqual(["user", "kieu_moi_cua_backend", "question", "text", "answer", "escalation"]);
    expect(normalizeConversation("không phải mảng")).toEqual([]);

    const { container } = render(<Conversation messages={messages} />);
    expect(container.querySelector('[data-kind="kieu_moi_cua_backend"]')?.textContent).toContain("Tin kiểu mới");
    expect(screen.getByText("12")).toBeTruthy();
    expect(container.querySelector('[data-role="user"]')?.textContent).toBe("VPN công ty dùng cổng nào?");
    // Nguồn: title · heading_path; nguồn hỏng bị bỏ.
    const sources = container.querySelector('[data-testid="sources"]');
    expect(sources?.textContent).toContain("Tổng quan dịch vụ VPN · Cổng kết nối");
    expect(sources?.querySelectorAll('[data-testid="source"]')).toHaveLength(1);
    expect(container.querySelector('[data-kind="answer"] strong')?.textContent).toBe("IKEv2");
  });
});
