import type { PolicyVersionItem } from "../../api/types.ts";
import { vnDateTime } from "./range.ts";

// Lịch sử phiên bản (B4MgrPolicy, cột phải) — CHỈ XEM. Mới nhất ở trên (theo `version_id` giảm). Bản đang áp dụng đậm.
// Route thật (N-POL1) trả đúng 1 mục: bản nạp từ file (`version_id` 0, `updated_by` null → "Hệ thống", `restored_from`
// null). `restored_from` có giá trị → "khôi phục từ bản X"; null hoặc không có khoá → không hiện gì. Nút "Quay lui" đã gỡ
// (chưa có route restore — N-POL2).

export function PolicyHistory({ versions, dirty }: { versions: readonly PolicyVersionItem[]; dirty: boolean }) {
  const sorted = [...versions].sort((a, b) => b.version_id - a.version_id);
  return (
    <ul aria-label="Lịch sử phiên bản" className="overflow-hidden rounded-group border border-line">
      {dirty ? (
        <li data-testid="version-draft" className="flex flex-col px-4 py-2.5">
          <span className="text-secondary font-semibold">Bản đang sửa</span>
          <span className="text-label font-normal text-ink-2">Chỉ để kiểm tra · chưa lưu</span>
        </li>
      ) : null}
      {sorted.length === 0 ? (
        <li data-testid="version-empty" className="px-4 py-2.5 text-secondary text-ink-2">
          Chưa có phiên bản nào.
        </li>
      ) : null}
      {sorted.map((v) => (
        <li
          key={v.version_id}
          data-testid="version-row"
          data-version={v.version}
          data-current={v.is_current}
          className={`flex items-center gap-2 px-4 py-2.5 ${dirty || sorted[0] !== v ? "border-t border-line" : ""}`}
        >
          <span className="flex min-w-0 grow flex-col">
            <span className={`text-secondary ${v.is_current ? "font-semibold" : ""}`}>
              Bản {v.version}
              {v.is_current ? " · đang áp dụng" : ""}
            </span>
            <span className="text-label font-normal text-ink-2">
              {v.updated_by ?? "Hệ thống"} · {vnDateTime(v.updated_at)}
              {v.restored_from ? ` · khôi phục từ bản ${v.restored_from}` : ""}
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}
