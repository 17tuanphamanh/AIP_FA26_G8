import { MaNhan } from "../../components/MaNhan.tsx";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { ticketReadOnlyQuery } from "../../api/tickets.ts";
import { hasPerm } from "../../auth/permissions.ts";
import { useMe } from "../../auth/useAuth.ts";
import { OverrideDialog } from "../../components/OverrideDialog.tsx";
import { TicketConversation } from "../../components/TicketConversation.tsx";
import { deadlineText, TICKET_ID_PATTERN, TICKET_UNAVAILABLE } from "./inbox.ts";

// Xem ticket CHỈ ĐỌC để ghi đè (KH 4.6: tab "Hệ thống đã tự xử lý" ẩn tới Phase 7 → mở bằng mã ticket, hoặc từ phiếu đã
// quyết). Hội thoại: `GET /api/tickets/{id}` THẬT (component chỉ đọc của F3, không mock). Q-fe-24 [Chốt]: nút "Ghi đè…"
// hiện theo quyền `decision:override`, KHÔNG phụ thuộc GET ticket thành công — server quyết (404 / 409 `ticket_open`…).
// GET lỗi (vd ticket minh hoạ của dev:mock không có ở backend → 404) → câu trung tính, không mã lỗi. Ghi đè: route THẬT 4d.

export function TicketOverrideRoute() {
  const { ticketId = "" } = useParams();
  return <TicketOverride key={ticketId} ticketId={ticketId} />;
}

function TicketOverride({ ticketId }: { ticketId: string }) {
  const me = useMe();
  const [open, setOpen] = useState(false);
  const valid = TICKET_ID_PATTERN.test(ticketId);
  const query = useQuery({ ...ticketReadOnlyQuery(ticketId), enabled: valid });
  const view = query.data;
  // R3: hạn của LẦN CHỜ HIỆN TẠI; null / thiếu / không phải thời điểm → không hiện gì (không đoán, không "—").
  const waitDeadline = view?.final_state ? null : deadlineText(view?.deadline);

  return (
    <section className="flex flex-col gap-6 px-12 pt-20 pb-8">
      <div className="flex flex-col gap-1">
        <Link to="/approvals" className="text-secondary text-fpt-blue">
          ‹ Chờ tôi duyệt
        </Link>
        <h1 className="text-title">
          Ticket <span className="font-mono">{ticketId}</span>
        </h1>
        <p className="text-ink-2">Xem chỉ đọc. Ghi đè không đổi ticket — chỉ ghi vào nhật ký để đánh giá lại hệ thống.</p>
        {view ? (
          <p data-testid="ticket-state" className="text-secondary text-ink-2">
            Trạng thái <MaNhan loai="trang_thai" ma={view.status} />
            {view.exit_code ? (
              <>
                {" "}
                · Kết thúc <MaNhan loai="ma_ket_thuc" ma={view.exit_code} />
              </>
            ) : null}
            {view.final_state ? " · Đã kết thúc" : " · Chưa kết thúc"}
            {waitDeadline ? (
              <>
                {" "}
                · Hạn của lần chờ hiện tại <span data-testid="ticket-deadline">{waitDeadline}</span>
              </>
            ) : null}
          </p>
        ) : null}
      </div>

      {valid ? (
        <TicketConversation ticketId={ticketId} failText={TICKET_UNAVAILABLE} />
      ) : (
        <p role="alert" className="text-danger">
          Mã ticket không hợp lệ.
        </p>
      )}

      {valid && hasPerm(me, "decision:override") ? (
        <div>
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="h-11 rounded-full bg-button-2 px-5 font-semibold text-fpt-blue"
          >
            Ghi đè…
          </button>
        </div>
      ) : null}
      {open ? <OverrideDialog ticketId={ticketId} onClose={() => setOpen(false)} /> : null}
    </section>
  );
}
