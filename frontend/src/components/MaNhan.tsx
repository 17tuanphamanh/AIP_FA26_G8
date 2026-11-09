import { type Loai, nhanIT } from "../lib/nhan.ts";

// "Nhãn · mã" cho nhân sự IT (bảng từ ngữ ĐP 26/10 23:10): nhãn chữ thường trước, mã kỹ thuật sau — chữ nhỏ, màu nhạt (token
// sẵn có `text-ink-2`), font mono. Mã lạ → "Khác · <mã>". Gợi ý (tooltip) qua `title` + bản sr-only cho trình đọc màn hình.
// KHÔNG dùng ở màn nhân viên (dùng `nhanNhanVien` — chỉ chữ).
export function Ma({ ma }: { ma: string }) {
  return (
    <span data-testid="ma" className="font-mono text-label font-normal text-ink-2">
      {ma}
    </span>
  );
}

export function NhanMa({ nhan, ma, goiY }: { nhan: string; ma: string; goiY?: string }) {
  return (
    <span data-testid="nhan-ma" title={goiY}>
      {nhan}
      {goiY ? <span className="sr-only"> ({goiY})</span> : null} · <Ma ma={ma} />
    </span>
  );
}

export function MaNhan({ loai, ma }: { loai: Loai; ma: string }) {
  const n = nhanIT(loai, ma);
  return <NhanMa nhan={n.nhan} ma={n.ma} goiY={n.goiY} />;
}
