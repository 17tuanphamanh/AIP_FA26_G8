// Chỗ giữ cho màn dựng ở chặng sau: route + quyền đã có (F1), nội dung chưa có. Nói thật là chưa có —
// không hiện dữ liệu bịa (KH 4.3 #4).
export function Pending({ title, stage }: { title: string; stage: string }) {
  return (
    <section className="px-12 py-10">
      <h1 className="text-title">{title}</h1>
      <p className="mt-2 text-ink-2">Màn này dựng ở chặng {stage}.</p>
    </section>
  );
}
