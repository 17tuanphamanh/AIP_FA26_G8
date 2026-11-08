import { Link } from "react-router";

export function Forbidden() {
  return (
    <section className="px-12 py-10 max-lg:px-4 max-lg:py-6">
      <p className="text-label text-ink-2">Lỗi 403</p>
      <h1 className="mt-2 text-title">Bạn không có quyền xem trang này</h1>
      <p className="mt-2 max-w-(--chat-width) text-ink-2">
        Trang này dành cho vai trò khác. Nếu bạn cần quyền truy cập, hãy liên hệ bộ phận IT.
      </p>
      <Link to="/" className="mt-6 inline-flex h-11 items-center rounded-full bg-fpt-blue px-5 font-semibold text-white">
        Về trang đầu
      </Link>
    </section>
  );
}
