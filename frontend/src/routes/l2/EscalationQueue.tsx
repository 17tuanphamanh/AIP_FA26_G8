import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { ApiError, errorMessage } from "../../api/errors.ts";
import { QUEUE_LIMIT, QUEUE_REFRESH_MS, queueQuery, queueRefetchInterval } from "../../api/escalations.ts";
import type { EscalationQueueItem } from "../../api/types.ts";
import {
  DENY_BADGE,
  EMPTY_VIEW,
  GROUP_PAGE_SIZE,
  NO_IDS,
  NO_MATCH_FULL_TEXT,
  NO_MATCH_TEXT,
  SEARCH_LIMIT_NOTE,
  SEARCH_MAX,
  type QueueView,
  clampPage,
  filterQueue,
  groupQueue,
  pageCount,
  pruneQueueView,
  reasonLine,
  searchWords,
  splitLabel,
  trackMissed,
  waitingText,
} from "./queue.ts";

// B4L2Queue — hàng đợi escalate THẬT (`GET /api/escalations/queue`, quyền escalation:handle: L1 + L2). Thứ tự của server
// giữ nguyên, chỉ gom nhóm liên tiếp theo `priority` (queue.ts). L1/L2 được thấy mã E (KH 4.2 #2). Không nút duyệt nào
// ở màn này [Chốt 2.2]. Khác Bản 4: nhóm không tô màu theo mức (màu theo hạng = bảng ưu tiên thứ hai ở frontend).
// Tìm nhanh + thẻ nhóm + thu gọn nhóm + phân trang trong nhóm: làm ở trình duyệt, trên các ca ĐÃ tải, KHÔNG sắp lại thứ tự
// server. Không dòng nào bị ẩn mà thiếu con số bên cạnh ("Khớp k / N ca", "· N ca", "Ca a–b / N", số trên thẻ).

export function EscalationQueue() {
  const query = useQuery({ ...queueQuery(), refetchInterval: (q) => queueRefetchInterval(q.state.error) });
  const items = query.data;
  const [search, setSearch] = useState("");
  const words = searchWords(search);
  const shown = items ? filterQueue(items, search) : [];
  const full = items !== undefined && items.length >= QUEUE_LIMIT;

  return (
    <section className="flex flex-col gap-6 px-12 py-10">
      <div className="flex items-end gap-4">
        <div className="flex min-w-0 grow flex-col gap-1">
          <h1 className="text-title">Hàng đợi escalate</h1>
          <p className="text-ink-2">
            {items ? (
              <>
                <span data-testid="queue-count">Đang hiện {items.length} ca</span> ·{" "}
              </>
            ) : null}
            theo mức ưu tiên, rồi thời gian chờ · tự tải lại mỗi {QUEUE_REFRESH_MS / 1000} giây.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void query.refetch()}
          disabled={query.isFetching}
          className="h-7.5 shrink-0 rounded-full bg-button-2 px-3.5 text-secondary font-semibold text-fpt-blue disabled:opacity-60"
        >
          {query.isFetching ? "Đang tải…" : "Tải lại"}
        </button>
      </div>

      {items && items.length > 0 ? (
        <div className="flex items-center gap-3 rounded-group border border-line px-5 py-3">
          <label htmlFor="queue-search" className="shrink-0 text-secondary">
            Tìm ca
          </label>
          <input
            id="queue-search"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            maxLength={SEARCH_MAX}
            placeholder="Mã ticket, mã E, tên nhóm, lý do…"
            autoComplete="off"
            spellCheck={false}
            data-testid="queue-search"
            className="h-9 min-w-0 grow rounded-lg border border-line px-3 text-secondary"
          />
          {words.length > 0 ? (
            <span role="status" data-testid="queue-search-count" className="shrink-0 text-secondary text-ink-2">
              Khớp {shown.length} / {items.length} ca{full ? SEARCH_LIMIT_NOTE : ""}
            </span>
          ) : null}
        </div>
      ) : null}

      {items === undefined ? (
        query.isPending ? (
          <p className="text-ink-2">Đang tải hàng đợi…</p>
        ) : (
          <p role="alert" className="text-danger">
            Chưa tải được hàng đợi: {errorMessage(query.error instanceof ApiError ? query.error : null)}
          </p>
        )
      ) : (
        <>
          {query.isError ? (
            <p role="status" className="text-secondary text-ink-2">
              Chưa tải lại được — đang hiện dữ liệu lần trước.
            </p>
          ) : null}
          {full ? (
            <p role="status" className="rounded-group bg-orange-bg px-4 py-3 text-secondary text-orange-ink" data-testid="queue-overflow">
              Hàng đợi đang quá {QUEUE_LIMIT} ca — chỉ hiện {QUEUE_LIMIT} ca đầu theo ưu tiên (ca cũ trước), ca mới hơn có thể
              chưa hiện.
            </p>
          ) : null}
          <QueueGroups all={items} items={shown} searchKey={words.join(" ")} full={full} now={query.dataUpdatedAt} />
        </>
      )}
    </section>
  );
}

type Found = { key: string; view: QueueView };

/**
 * `all` = danh sách CHƯA lọc (đúng tham chiếu của truy vấn), `items` = các ca khớp ô tìm, `searchKey` = các từ tìm nối lại
 * ("" = không tìm). Hai bộ trạng thái, cùng khoá theo `priority`, chỉ trong bộ nhớ (Q-fe-42 A):
 * - `saved`: khi KHÔNG tìm — nhóm thu gọn, trang, thẻ nhóm (thẻ dùng chung cả khi tìm).
 * - `found`: khi đang tìm — mỗi lần DANH SÁCH TỪ đổi thì về "mọi nhóm mở, trang 1"; xoá ô tìm → về `saved` nguyên vẹn.
 * - `missed`: ca MỚI (so với lần tải trước) rơi vào nhóm đang khuất theo `saved` (Q-fe-43) — báo một dòng ở CẢ hai chế độ.
 */
function QueueGroups({
  all,
  items,
  searchKey,
  full,
  now,
}: {
  all: EscalationQueueItem[];
  items: EscalationQueueItem[];
  searchKey: string;
  full: boolean;
  now: number;
}) {
  const searching = searchKey !== "";
  const [saved, setSaved] = useState<QueueView>(EMPTY_VIEW);
  const [found, setFound] = useState<Found>({ key: searchKey, view: EMPTY_VIEW });
  const [missed, setMissed] = useState<ReadonlySet<number>>(NO_IDS);
  // null = chưa có lần tải nào (lần dựng đầu là lần tải đầu → không ca nào là "mới").
  const [source, setSource] = useState<EscalationQueueItem[] | null>(null);
  // Dữ liệu mới (tự tải lại / nút "Tải lại") → dọn trạng thái NGAY lúc dựng, không qua effect. `saved` dọn theo danh sách
  // CHƯA lọc (theo danh sách đã lọc thì gõ tìm sẽ làm bung nhóm đang thu gọn); `found` dọn theo các ca khớp. Không có gì
  // đổi → pruneQueueView / trackMissed trả đúng object cũ → không setState.
  let latest = saved; // trạng thái đã lưu sau khi dọn theo dữ liệu mới
  if (source !== all) {
    setSource(all);
    latest = pruneQueueView(saved, all);
    if (latest !== saved) setSaved(latest);
    const nextFound = pruneQueueView(found.view, items);
    if (nextFound !== found.view) setFound({ key: found.key, view: nextFound });
  }
  if (found.key !== searchKey) setFound({ key: searchKey, view: EMPTY_VIEW });
  // Lần dựng không có dữ liệu mới: chỉ bỏ các ca đã báo mà nay hiện ra / rời hàng đợi.
  const nextMissed = trackMissed(missed, source === all ? all : source, all, latest);
  if (nextMissed !== missed) setMissed(nextMissed);

  if (all.length === 0) return <p className="rounded-group bg-group px-5 py-4 text-ink-2">Không có ca nào đang chờ</p>;

  // Tên nhóm lấy từ danh sách CHƯA lọc (nhãn không đổi theo chữ gõ); số đếm bên cạnh là số ca đang khớp.
  const allGroups = groupQueue(all);
  const names = new Map(allGroups.map((g) => [g.priority, g.name]));
  const missedGroups = allGroups
    .map((g) => ({ priority: g.priority, name: g.name, count: g.items.filter((i) => missed.has(i.escalation_id)).length }))
    .filter((g) => g.count > 0);
  const missedTotal = missedGroups.reduce((n, g) => n + g.count, 0);
  // "Hiện các nhóm này": về thẻ "Tất cả" + mở các nhóm đó trong trạng thái ĐÃ LƯU → lần dựng sau trackMissed bỏ hết.
  const reveal = () =>
    setSaved((v) => {
      const collapsed = new Set(v.collapsed);
      for (const g of missedGroups) collapsed.delete(g.priority);
      return { ...v, collapsed, active: null };
    });
  const missedLine =
    missedTotal > 0 ? (
      <div
        role="status"
        data-testid="queue-missed"
        className="flex flex-wrap items-center gap-3 rounded-group bg-orange-bg px-4 py-3 text-secondary text-orange-ink"
      >
        <span className="min-w-0 grow">
          Có {missedTotal} ca mới ở nhóm đang ẩn hoặc thu gọn: {missedGroups.map((g) => `${g.name} (${g.count})`).join(", ")}
        </span>
        <button type="button" onClick={reveal} className={PAGER_BUTTON}>
          Hiện các nhóm này
        </button>
      </div>
    ) : null;

  if (items.length === 0) {
    return (
      <div className="flex flex-col gap-4">
        {missedLine}
        <p className="rounded-group bg-group px-5 py-4 text-ink-2">{full ? NO_MATCH_FULL_TEXT : NO_MATCH_TEXT}</p>
      </div>
    );
  }

  const view = searching ? found.view : saved;
  const change = (next: (v: QueueView) => QueueView) => {
    if (searching) setFound((f) => ({ key: f.key, view: next(f.view) }));
    else setSaved(next);
  };
  const toggle = (priority: number) =>
    change((v) => {
      const collapsed = new Set(v.collapsed);
      if (collapsed.has(priority)) collapsed.delete(priority);
      else collapsed.add(priority);
      return { ...v, collapsed };
    });
  const goPage = (priority: number, page: number) => change((v) => ({ ...v, pages: { ...v.pages, [priority]: page } }));
  const select = (priority: number | null) => setSaved((v) => ({ ...v, active: priority }));

  // Khoá khối = priority + thứ tự xuất hiện của hạng đó (không theo vị trí: nhóm phía trước xuất hiện / biến mất không làm
  // khối sau bị dựng lại, mất tiêu điểm bàn phím).
  const seen = new Map<number, number>();
  const groups = groupQueue(items).map((group) => {
    const nth = seen.get(group.priority) ?? 0;
    seen.set(group.priority, nth + 1);
    return { ...group, name: names.get(group.priority) ?? group.name, key: nth === 0 ? `${group.priority}` : `${group.priority}-${nth}` };
  });
  // Thẻ đang chọn không có ca (đang tìm) → chỉ suy ra tạm "Tất cả", không đặt lại.
  const current = groups.some((g) => g.priority === saved.active) ? saved.active : null;
  const tabClass = (selected: boolean) =>
    `h-8 shrink-0 rounded-md px-4 text-secondary ${selected ? "bg-white font-semibold shadow-input" : ""}`;

  return (
    <div className="flex flex-col gap-4">
      {missedLine}
      <div role="tablist" aria-label="Nhóm ưu tiên" data-testid="queue-tabs" className="flex flex-wrap self-start rounded-lg bg-segmented p-0.5">
        <button
          type="button"
          role="tab"
          aria-selected={current === null}
          onClick={() => select(null)}
          data-testid="queue-tab-all"
          className={tabClass(current === null)}
        >
          Tất cả · {items.length}
        </button>
        {groups.map((group) => (
          <button
            key={group.key}
            type="button"
            role="tab"
            aria-selected={current === group.priority}
            onClick={() => select(group.priority)}
            data-testid="queue-tab"
            data-priority={group.priority}
            className={tabClass(current === group.priority)}
          >
            {group.name} · {group.items.length}
          </button>
        ))}
      </div>
      {groups.map((group) => {
        if (current !== null && group.priority !== current) return null;
        const total = group.items.length;
        const page = clampPage(view.pages[group.priority] ?? 1, total);
        const start = (page - 1) * GROUP_PAGE_SIZE;
        const open = !view.collapsed.has(group.priority);
        return (
          <section
            key={group.key}
            aria-labelledby={`queue-group-${group.key}`}
            data-testid="queue-group"
            data-priority={group.priority}
            className="flex flex-col gap-1.5"
          >
            <h2 id={`queue-group-${group.key}`} className="pl-1 text-label text-ink-2">
              <button
                type="button"
                onClick={() => toggle(group.priority)}
                aria-expanded={open}
                data-testid="queue-group-toggle"
                className="inline-flex items-center gap-2 rounded-md py-0.5 pr-2 focus-visible:outline-2 focus-visible:outline-fpt-blue"
              >
                <svg
                  width="12"
                  height="12"
                  viewBox="0 0 24 24"
                  fill="none"
                  className={`stroke-ink-3 transition-transform ${open ? "rotate-90" : ""}`}
                  strokeWidth="2.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M9 6l6 6-6 6" />
                </svg>
                <span data-testid="queue-group-name">{group.name}</span>
                <span className="font-normal" data-testid="queue-group-count">
                  · {total} ca
                </span>
              </button>
            </h2>
            {open ? (
              <>
                <ul className="overflow-hidden rounded-group border border-line">
                  {group.items.slice(start, start + GROUP_PAGE_SIZE).map((item) => (
                    <QueueRow key={item.escalation_id} item={item} now={now} />
                  ))}
                </ul>
                {total > GROUP_PAGE_SIZE ? (
                  <Pager name={group.name} page={page} total={total} onGo={(next) => goPage(group.priority, next)} />
                ) : null}
              </>
            ) : null}
          </section>
        );
      })}
    </div>
  );
}

const PAGER_BUTTON = "h-7.5 rounded-full bg-button-2 px-3.5 text-secondary font-semibold text-fpt-blue disabled:opacity-60";

function Pager({ name, page, total, onGo }: { name: string; page: number; total: number; onGo: (page: number) => void }) {
  const pages = pageCount(total);
  const from = (page - 1) * GROUP_PAGE_SIZE + 1;
  const to = Math.min(page * GROUP_PAGE_SIZE, total);
  return (
    <nav aria-label={`Phân trang trong nhóm ${name}`} data-testid="queue-pager" className="flex items-center gap-2 pt-0.5">
      <span className="mr-auto pl-1 text-secondary text-ink-2">
        Ca {from}–{to} / {total} · trang {page}/{pages}
      </span>
      <button type="button" className={PAGER_BUTTON} disabled={page <= 1} onClick={() => onGo(1)}>
        Đầu
      </button>
      <button type="button" className={PAGER_BUTTON} disabled={page <= 1} onClick={() => onGo(page - 1)}>
        Trước
      </button>
      <button type="button" className={PAGER_BUTTON} disabled={page >= pages} onClick={() => onGo(page + 1)}>
        Sau
      </button>
      <button type="button" className={PAGER_BUTTON} disabled={page >= pages} onClick={() => onGo(pages)}>
        Cuối
      </button>
    </nav>
  );
}

function QueueRow({ item, now }: { item: EscalationQueueItem; now: number }) {
  const reason = reasonLine(item);
  const extra = splitLabel(item.label).extra;
  const meta = [waitingText(item.created_at, now), item.assigned_to ? `${item.assigned_to} đang xử lý` : ""]
    .filter(Boolean)
    .join(" · ");
  return (
    <li className="border-t border-line first:border-t-0">
      <Link
        to={`/escalations/${item.escalation_id}`}
        data-testid="queue-row"
        data-escalation-id={item.escalation_id}
        data-ticket-id={item.ticket_id}
        data-exit-code={item.exit_code}
        className="grid min-h-13 grid-cols-[44px_minmax(0,1fr)_auto_14px] items-center gap-4 px-5 py-2 hover:bg-group focus-visible:outline-2 focus-visible:outline-fpt-blue"
      >
        <span className="font-mono text-label font-normal text-ink-2">{item.exit_code}</span>
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate" title={reason}>
            {reason}
          </span>
          {item.is_deny_case ? (
            <span className="shrink-0 rounded-full bg-danger-bg px-2 text-label text-danger-ink" data-testid="deny-badge">
              {DENY_BADGE}
            </span>
          ) : null}
          {extra ? (
            <span className="shrink-0 rounded-full bg-orange-bg px-2 text-label text-orange-ink">{extra}</span>
          ) : null}
        </span>
        <span className="text-secondary text-ink-2">{meta}</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" className="stroke-ink-3" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M9 6l6 6-6 6" />
        </svg>
      </Link>
    </li>
  );
}
