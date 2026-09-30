import { Link } from "react-router";

export function NotFound() {
  return (
    <section className="px-12 py-10">
      <p className="text-label text-ink-2">Lỗi 404</p>
      <h1 className="mt-2 text-title">Không tìm thấy trang</h1>
      <p className="mt-2 max-w-(--chat-width) text-ink-2">Đường dẫn không đúng hoặc trang đã được chuyển.</p>
      <Link to="/" className="mt-6 inline-flex h-11 items-center rounded-full bg-fpt-blue px-5 font-semibold text-white">
        Về trang đầu
      </Link>
    </section>
  );
}
