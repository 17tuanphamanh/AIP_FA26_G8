// Markdown đang chạy chữ (StreamingText): giấu dấu mở chưa có dấu đóng để không lộ ký hiệu thô giữa chừng.

/** Đang chạy chữ mà dấu `**` hoặc `` ` `` chưa có dấu đóng → tạm bỏ dấu mở cuối (không lộ ký hiệu thô; đóng xong thì hiện đúng). */
export function softClose(text: string): string {
  let out = text;
  if ((out.match(/\*\*/g)?.length ?? 0) % 2 === 1) {
    const at = out.lastIndexOf("**");
    out = out.slice(0, at) + out.slice(at + 2);
  }
  if ((out.match(/`/g)?.length ?? 0) % 2 === 1) {
    const at = out.lastIndexOf("`");
    out = out.slice(0, at) + out.slice(at + 1);
  }
  return out;
}
