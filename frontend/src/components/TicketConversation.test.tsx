// M2 bn-a: hội thoại CHỈ ĐỌC của IT (chi tiết escalate F3, màn ghi đè F4) khi job hạn giữ đã dọn checkpoint → backend 410
// `conversation_purged` → câu chính sách lưu trữ (trung tính, không alert), kể cả khi màn truyền `failText` riêng.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PURGED_TEXT } from "../api/errors.ts";
import { TicketConversation } from "./TicketConversation.tsx";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function mount(status: number, detail: string, failText?: string) {
  vi.stubGlobal("fetch", vi.fn(async () => json(status, { detail })));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <TicketConversation ticketId="tkt-cu" failText={failText} />
    </QueryClientProvider>,
  );
}

describe("M2: TicketConversation — 410 conversation_purged", () => {
  it.each([undefined, "Chưa tải được chi tiết yêu cầu."])("failText=%j → câu chính sách lưu trữ, không alert", async (failText) => {
    mount(410, "conversation_purged", failText);
    expect((await screen.findByTestId("conversation-purged")).textContent).toBe(PURGED_TEXT);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByTestId("ticket-unavailable")).toBeNull();
  });

  it("lỗi khác (503) vẫn như cũ — không nhầm thành 'đã dọn'", async () => {
    mount(503, "checkpoint_unavailable");
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.queryByTestId("conversation-purged")).toBeNull();
  });
});
