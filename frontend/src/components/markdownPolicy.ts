// Luật lọc Markdown cho nội dung do LLM/agent viết (KH 4.1 #5) — dùng ở SafeMarkdown.tsx.
// react-markdown 10 không dựng HTML thô (thẻ HTML trong chuỗi hiện thành CHỮ); KHÔNG BAO GIỜ thêm plugin parse HTML
// thô — `check:style` luật 4 chặn trong package.json và src.
// Lớp lọc riêng:
//   - chỉ các thẻ trong ALLOWED_ELEMENTS; thẻ khác bị gỡ, giữ chữ bên trong. Ảnh bị bỏ hẳn: ảnh Markdown
//     `![](https://…)` sẽ tải từ máy chủ ngoài (lộ IP/thời điểm đọc; CSP chặn ở bản build nhưng dev thì không).
//   - link chỉ `https:`, `http:`, `mailto:`; scheme khác → bỏ href.
export const ALLOWED_ELEMENTS = [
  "p", "br", "strong", "em", "del", "ul", "ol", "li", "code", "pre", "blockquote", "a", "h3", "h4", "hr",
];

export function safeUrl(url: string): string {
  return /^(https?:|mailto:)/i.test(url.trim()) ? url : "";
}
