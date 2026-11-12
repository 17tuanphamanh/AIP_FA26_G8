-- Độ trễ end-to-end và chi phí LLM theo yêu cầu cho MỘT khung giờ (CLI-7 S3, 13/11) — CHỈ ĐỌC (giao dịch READ ONLY, ROLLBACK).
--
-- Chạy trên máy demo (không cần mật khẩu: psql trong container postgres qua unix socket, user/DB lấy từ biến của container):
--
--   docker compose -p servicedesk exec -T -e FRM='2026-11-12 22:00+07' -e TO='2026-11-12 22:30+07' postgres \
--     sh -c 'psql -X -q -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -v frm="$FRM" -v to="$TO" -f -' \
--     < scripts/report/do_tre_chi_phi.sql
--
-- Định nghĩa (ghi kèm số khi đưa vào báo cáo):
-- - "Yêu cầu" = ticket GỐC (`parent_ticket_id IS NULL`) tạo trong [frm, to) — câu nhiều ý tính MỘT yêu cầu; chi phí của ticket con
--   (lời gọi LLM của từng ý) cộng về ticket gốc.
-- - Độ trễ end-to-end = `turns.ended_at - turns.started_at` của lượt `submit` của ticket gốc (từ lúc nhận câu tới lúc graph dừng: trả
--   lời, hỏi lại, chờ duyệt hoặc chuyển L2). Lượt `resume` (sau duyệt / trả lời hỏi lại) báo riêng. Lượt chưa kết thúc bỏ qua.
-- - Chi phí = Σ `llm_calls.cost_usd` (NULL = 0) qua `spans → turns → tickets`; lời gọi trúng cache tính đúng giá ghi trong bảng.
-- - Tách theo `tickets.source` (real | sim | eval).

BEGIN READ ONLY;

\echo '== 1. Số yêu cầu (ticket gốc) trong khung giờ, theo nguồn'
SELECT t.source, count(*) AS so_yeu_cau, count(*) FILTER (WHERE t.is_parent) AS so_cau_nhieu_y
FROM tickets t
WHERE t.parent_ticket_id IS NULL AND t.created_at >= :'frm'::timestamptz AND t.created_at < :'to'::timestamptz
GROUP BY t.source ORDER BY t.source;

\echo '== 2. Độ trễ end-to-end (giây) của lượt đầu (submit) — ticket gốc'
SELECT t.source,
       count(*) AS so_luot,
       round(CAST(percentile_cont(0.5) WITHIN GROUP (ORDER BY CAST(extract(epoch FROM u.ended_at - u.started_at) AS double precision)) AS numeric), 2) AS p50_s,
       round(CAST(percentile_cont(0.95) WITHIN GROUP (ORDER BY CAST(extract(epoch FROM u.ended_at - u.started_at) AS double precision)) AS numeric), 2) AS p95_s,
       round(CAST(max(extract(epoch FROM u.ended_at - u.started_at)) AS numeric), 2) AS max_s
FROM turns u JOIN tickets t ON t.ticket_id = u.ticket_id
WHERE t.parent_ticket_id IS NULL AND u.event_type = 'submit' AND u.ended_at IS NOT NULL
  AND t.created_at >= :'frm'::timestamptz AND t.created_at < :'to'::timestamptz
GROUP BY t.source ORDER BY t.source;

\echo '== 3. Độ trễ (giây) theo loại lượt — mọi ticket (gốc + con)'
SELECT t.source, u.event_type,
       count(*) AS so_luot,
       round(CAST(percentile_cont(0.5) WITHIN GROUP (ORDER BY CAST(extract(epoch FROM u.ended_at - u.started_at) AS double precision)) AS numeric), 2) AS p50_s,
       round(CAST(percentile_cont(0.95) WITHIN GROUP (ORDER BY CAST(extract(epoch FROM u.ended_at - u.started_at) AS double precision)) AS numeric), 2) AS p95_s
FROM turns u JOIN tickets t ON t.ticket_id = u.ticket_id
WHERE u.ended_at IS NOT NULL
  AND COALESCE((SELECT r.created_at FROM tickets r WHERE r.ticket_id = t.parent_ticket_id), t.created_at) >= :'frm'::timestamptz
  AND COALESCE((SELECT r.created_at FROM tickets r WHERE r.ticket_id = t.parent_ticket_id), t.created_at) < :'to'::timestamptz
GROUP BY t.source, u.event_type ORDER BY t.source, u.event_type;

\echo '== 4. Chi phí LLM (USD) theo yêu cầu'
WITH goc AS (
  SELECT t.ticket_id, t.source FROM tickets t
  WHERE t.parent_ticket_id IS NULL AND t.created_at >= :'frm'::timestamptz AND t.created_at < :'to'::timestamptz
), moi_yc AS (
  SELECT g.ticket_id, g.source,
         COALESCE(sum(COALESCE(c.cost_usd, 0)), 0) AS usd,
         count(c.call_id) AS so_loi_goi,
         count(c.call_id) FILTER (WHERE c.cache_hit) AS so_trung_cache
  FROM goc g
  LEFT JOIN tickets t ON t.ticket_id = g.ticket_id OR t.parent_ticket_id = g.ticket_id
  LEFT JOIN turns u ON u.ticket_id = t.ticket_id
  LEFT JOIN spans s ON s.turn_id = u.turn_id
  LEFT JOIN llm_calls c ON c.span_id = s.span_id
  GROUP BY g.ticket_id, g.source
)
SELECT source,
       count(*) AS so_yeu_cau,
       round(CAST(sum(usd) AS numeric), 6) AS tong_usd,
       round(CAST(avg(usd) AS numeric), 6) AS usd_moi_yeu_cau,
       round(CAST(percentile_cont(0.5) WITHIN GROUP (ORDER BY usd) AS numeric), 6) AS p50_usd,
       round(CAST(percentile_cont(0.95) WITHIN GROUP (ORDER BY usd) AS numeric), 6) AS p95_usd,
       sum(so_loi_goi) AS so_loi_goi_llm,
       sum(so_trung_cache) AS so_trung_cache
FROM moi_yc GROUP BY source ORDER BY source;

ROLLBACK;
