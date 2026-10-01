import type { PolicyVersionItem } from "../../api/types.ts";
import { vnDateTime } from "./range.ts";

// Lịch sử phiên bản (B4MgrPolicy, cột phải). Mới nhất ở trên (theo `version_id` giảm). Bản đang áp dụng đậm. Quay lui
// = TẠO phiên bản mới chép nội dung bản chọn (Q-fe-26, append-only) → bản tạo ra có "khôi phục từ bản X". Nút "Quay lui"
// chỉ cho người có `policy:edit`, không có ở bản đang áp dụng.

export function PolicyHistory({
  versions,
  dirty,
  canEdit,
  busy,
  onRestore,
}: {
  versions: readonly PolicyVersionItem[];
  dirty: boolean;
  canEdit: boolean;
  busy: boolean;
  onRestore: (version: PolicyVersionItem) => void;
}) {
  const sorted = [...versions].sort((a, b) => b.version_id - a.version_id);
  return (
    <ul aria-label="Lịch sử phiên bản" className="overflow-hidden rounded-group border border-line">
      {dirty ? (
        <li data-testid="version-draft" className="flex flex-col px-4 py-2.5">
          <span className="text-secondary font-semibold">Bản nháp</span>
          <span className="text-label font-normal text-ink-2">Đang sửa · chưa lưu</span>
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
          {canEdit && !v.is_current ? (
            <button
              type="button"
              disabled={busy}
              aria-label={`Quay lui bản ${v.version}`}
              onClick={() => onRestore(v)}
              className="shrink-0 rounded-md px-1 text-label text-fpt-blue disabled:opacity-60"
            >
              Quay lui
            </button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
