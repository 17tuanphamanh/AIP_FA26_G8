// Chính sách dạng JSON (F5 P7; chốt DỪNG 1). Vai trò tách bạch:
// - Hợp lệ hay không do `JSON.parse` quyết định — NGUỒN DUY NHẤT (giống server đọc lại đúng nội dung đó).
// - Bộ phân tích tự viết dưới đây CHỈ để định vị: dòng/cột của lỗi cú pháp (thông báo của JSON.parse khác nhau giữa
//   trình duyệt, Safari không có vị trí), dòng của `loc` trong lỗi 422 của server (`locLine`), và khoá trùng trong cùng
//   object. Nó KHÔNG BAO GIỜ khoá nút Lưu khi JSON.parse đã đọc được (lệch nhau → chỉ bỏ đánh dấu dòng).
// - Kiểm NGHĨA (ngưỡng, loại luật, id trùng…) là việc của server (422) — không viết lại validator ở đây (hai nguồn luật).
// Dòng/cột tính từ 1; xuống dòng = "\n" (textarea luôn chuẩn hoá về "\n").
import { ApiError, errorMessage, type Issue, routeMissing } from "../../api/errors.ts";
import { ownEntry } from "../../lib/lookup.ts";

export type JsonNode =
  | { kind: "object"; line: number; members: { key: string; line: number; value: JsonNode }[] }
  | { kind: "array"; line: number; items: JsonNode[] }
  | { kind: "scalar"; line: number };

/** Khoá xuất hiện nhiều lần trong CÙNG một object: `lines` tăng dần, dòng cuối là giá trị được dùng (như JSON.parse). */
export type DuplicateKey = { key: string; lines: number[] };

export type Located =
  | { ok: true; root: JsonNode; duplicates: DuplicateKey[] }
  | { ok: false; line: number | null; column: number | null; message: string };

class SyntaxFail extends Error {
  readonly at: number;
  constructor(at: number, message: string) {
    super(message);
    this.at = at;
  }
}

const NUMBER = /-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/y;
const ESCAPES: Record<string, string> = { '"': '"', "\\": "\\", "/": "/", b: "\b", f: "\f", n: "\n", r: "\r", t: "\t" };
const show = (c: string | undefined) => (c === undefined ? "hết tệp" : c === "\n" ? "xuống dòng" : `«${c}»`);

/** Phân tích JSON chặt (RFC 8259) kèm vị trí. Lỗi → dòng/cột + câu tiếng Việt. */
export function locate(text: string): Located {
  const lineStarts = [0];
  for (let k = 0; k < text.length; k++) if (text[k] === "\n") lineStarts.push(k + 1);
  const position = (at: number) => {
    let lo = 0;
    let hi = lineStarts.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (lineStarts[mid]! <= at) lo = mid;
      else hi = mid - 1;
    }
    return { line: lo + 1, column: at - lineStarts[lo]! + 1 };
  };
  const lineOf = (at: number) => position(at).line;

  const n = text.length;
  let i = 0;
  const duplicates: DuplicateKey[] = [];
  const fail = (at: number, message: string): never => {
    throw new SyntaxFail(at, message);
  };
  const ws = () => {
    while (i < n && (text[i] === " " || text[i] === "\t" || text[i] === "\n" || text[i] === "\r")) i++;
  };

  function string(): string {
    const start = i;
    i++; // "
    let out = "";
    for (;;) {
      if (i >= n) fail(start, "Chuỗi chưa đóng — thiếu dấu ngoặc kép");
      const c = text[i]!;
      if (c === '"') {
        i++;
        return out;
      }
      if (c === "\\") {
        const e = text[i + 1];
        const escaped = e === undefined ? undefined : ownEntry<string | undefined>(ESCAPES, e, undefined);
        if (escaped !== undefined) {
          out += escaped;
          i += 2;
        } else if (e === "u" && /^[0-9a-fA-F]{4}$/.test(text.slice(i + 2, i + 6))) {
          out += String.fromCharCode(parseInt(text.slice(i + 2, i + 6), 16));
          i += 6;
        } else {
          fail(i, "Ký tự thoát không hợp lệ trong chuỗi");
        }
        continue;
      }
      if (c.charCodeAt(0) < 0x20) fail(c === "\n" ? start : i, c === "\n" ? "Chuỗi chưa đóng trước khi xuống dòng" : "Chuỗi chứa ký tự điều khiển");
      out += c;
      i++;
    }
  }

  function value(): JsonNode {
    ws();
    if (i >= n) fail(i, "Nội dung kết thúc giữa chừng — thiếu giá trị");
    const line = lineOf(i);
    const c = text[i]!;
    if (c === "{") return object(line);
    if (c === "[") return array(line);
    if (c === '"') {
      string();
      return { kind: "scalar", line };
    }
    if (c === "-" || (c >= "0" && c <= "9")) {
      NUMBER.lastIndex = i;
      const m = NUMBER.exec(text);
      if (!m) fail(i, "Số không hợp lệ");
      i += m![0].length;
      return { kind: "scalar", line };
    }
    for (const literal of ["true", "false", "null"]) {
      if (text.startsWith(literal, i)) {
        i += literal.length;
        return { kind: "scalar", line };
      }
    }
    return fail(i, `Cần một giá trị (chuỗi, số, đối tượng, mảng, true, false, null) — gặp ${show(c)}`);
  }

  function object(line: number): JsonNode {
    i++; // {
    const members: { key: string; line: number; value: JsonNode }[] = [];
    const seen = new Map<string, number[]>();
    ws();
    if (text[i] === "}") {
      i++;
      return { kind: "object", line, members };
    }
    for (;;) {
      ws();
      if (i >= n) fail(i, "Nội dung kết thúc khi đối tượng chưa đóng — thiếu }");
      if (text[i] !== '"') fail(i, text[i] === "}" ? "Dấu phẩy thừa trước }" : `Cần tên khoá trong ngoặc kép — gặp ${show(text[i])}`);
      const keyLine = lineOf(i);
      const key = string();
      ws();
      if (text[i] !== ":") fail(i, `Thiếu dấu hai chấm sau khoá "${key}"`);
      i++;
      members.push({ key, line: keyLine, value: value() });
      seen.set(key, [...(seen.get(key) ?? []), keyLine]);
      ws();
      if (text[i] === ",") {
        i++;
        continue;
      }
      if (text[i] === "}") {
        i++;
        break;
      }
      fail(i, i >= n ? "Nội dung kết thúc khi đối tượng chưa đóng — thiếu }" : `Thiếu dấu phẩy hoặc } — gặp ${show(text[i])}`);
    }
    for (const [key, lines] of seen) if (lines.length > 1) duplicates.push({ key, lines });
    return { kind: "object", line, members };
  }

  function array(line: number): JsonNode {
    i++; // [
    const items: JsonNode[] = [];
    ws();
    if (text[i] === "]") {
      i++;
      return { kind: "array", line, items };
    }
    for (;;) {
      items.push(value());
      ws();
      if (text[i] === ",") {
        i++;
        ws();
        if (text[i] === "]") fail(i, "Dấu phẩy thừa trước ]");
        continue;
      }
      if (text[i] === "]") {
        i++;
        break;
      }
      fail(i, i >= n ? "Nội dung kết thúc khi mảng chưa đóng — thiếu ]" : `Thiếu dấu phẩy hoặc ] — gặp ${show(text[i])}`);
    }
    return { kind: "array", line, items };
  }

  try {
    ws();
    if (i >= n) fail(0, "Nội dung trống");
    const root = value();
    ws();
    if (i < n) fail(i, `Thừa nội dung sau khi JSON đã kết thúc — gặp ${show(text[i])}`);
    duplicates.sort((a, b) => a.lines[0]! - b.lines[0]!);
    return { ok: true, root, duplicates };
  } catch (error) {
    if (error instanceof SyntaxFail) return { ok: false, ...position(error.at), message: error.message };
    return { ok: false, line: null, column: null, message: "Không định vị được lỗi" }; // vd lồng quá sâu (tràn ngăn xếp)
  }
}

/** Dòng mà `loc` (đường dẫn kiểu Pydantic, tính từ gốc nội dung) trỏ tới: khoá → dòng của khoá; phần tử mảng → dòng bắt
 *  đầu phần tử. Khoá trùng → lần cuối (giá trị server dùng). Không tìm thấy / `loc` rỗng → null ("Toàn tệp"). */
export function lineAt(root: JsonNode, loc: readonly (string | number)[]): number | null {
  if (loc.length === 0) return null;
  let node = root;
  let line: number | null = null;
  for (const part of loc) {
    if (node.kind === "object" && typeof part === "string") {
      const member = node.members.findLast((m) => m.key === part);
      if (!member) return null;
      line = member.line;
      node = member.value;
    } else if (node.kind === "array" && (typeof part === "number" || /^\d+$/.test(part))) {
      const item = node.items[Number(part)];
      if (!item) return null;
      line = item.line;
      node = item;
    } else {
      return null;
    }
  }
  return line;
}

/** Hàm thuần theo lệnh P7: văn bản + `loc` → số dòng (null = "Toàn tệp", kể cả khi văn bản không định vị được). */
export function locLine(text: string, loc: readonly (string | number)[]): number | null {
  const located = locate(text);
  return located.ok ? lineAt(located.root, loc) : null;
}

export type PolicyCheck =
  | { valid: true; value: unknown; root: JsonNode | null; duplicates: DuplicateKey[] }
  | { valid: false; line: number | null; column: number | null; message: string };

/**
 * JSON.parse quyết hợp lệ. Lỗi → vị trí từ bộ tự viết (không ra vị trí → "Toàn tệp"). Hợp lệ mà bộ tự viết báo lỗi →
 * VẪN hợp lệ (không khoá Lưu), chỉ không có cây để đánh dấu dòng (`root` null). `locator` truyền vào để test nhánh này.
 */
export function checkPolicyText(text: string, locator: (text: string) => Located = locate): PolicyCheck {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    const at = locator(text);
    if (!at.ok) return { valid: false, line: at.line, column: at.column, message: at.message };
    return { valid: false, line: null, column: null, message: "JSON không hợp lệ" };
  }
  const at = locator(text);
  return at.ok ? { valid: true, value, root: at.root, duplicates: at.duplicates } : { valid: true, value, root: null, duplicates: [] };
}

/** "Dòng 5, cột 3 · Thiếu dấu phẩy…" hoặc "Toàn tệp · …". */
export function syntaxText(check: Extract<PolicyCheck, { valid: false }>): string {
  return check.line === null ? `Toàn tệp · ${check.message}` : `Dòng ${check.line}, cột ${check.column} · ${check.message}`;
}

const joinLines = (lines: readonly number[]) =>
  lines.length <= 1 ? String(lines[0] ?? "") : `${lines.slice(0, -1).join(", ")} và ${lines[lines.length - 1]}`;

/** Cảnh báo vàng (không chặn Lưu): khoá lặp trong cùng object — giá trị sau cùng được dùng, giống server. */
export function duplicateText(dup: DuplicateKey): string {
  return `Khoá "${dup.key}" lặp ở dòng ${joinLines(dup.lines)} — hệ thống dùng giá trị sau cùng (dòng ${dup.lines[dup.lines.length - 1]})`;
}

/** Nội dung server trả → văn bản hiện trong ô sửa. */
export const formatPolicy = (content: unknown): string => JSON.stringify(content, null, 2);

// Câu trên màn Chính sách (dùng chung với test / verify). N-POL1: chỉ xem + kiểm (`POST /api/policy/validate`); câu của
// Lưu / quay lui (409 `version_conflict`, hộp xác nhận quay lui) bỏ cùng nút — N-POL2 thêm lại theo route thật.
export const TOO_LARGE_TEXT = "Nội dung quá dài";
export const NOT_OBJECT_TEXT = "Nội dung chính sách phải là một đối tượng JSON ({…})";
export const VALID_TEXT = "Chính sách hợp lệ — máy chủ không thấy lỗi nào.";
export const INVALID_TEXT = "Chính sách chưa hợp lệ — xem các dòng được đánh dấu.";
/** 422 `invalid_request` (thân sai hình dạng) — không có vị trí trong nội dung để đánh dấu. */
export const SHAPE_TEXT = "Máy chủ không đọc được nội dung gửi đi — kiểm tra lại JSON rồi thử lại.";
/** 403 của validate (cần `policy:edit`). */
export const CHECK_FORBIDDEN_TEXT = "Bạn không có quyền kiểm tra chính sách.";
/** 5xx, lỗi mạng, thân trả về sai dạng: câu chung, KHÔNG kèm chi tiết từ máy chủ. */
export const CHECK_FAILED_TEXT = "Chưa kiểm tra được — hệ thống đang bận hoặc mất kết nối. Vui lòng thử lại sau.";
export const CHECK_MISSING_TEXT = "Máy chủ chưa có chức năng kiểm tra chính sách.";

/** Lỗi của validate → câu + (422 `invalid_policy`) danh sách lỗi theo vị trí. Không bao giờ đưa thân lỗi 5xx ra màn. */
export function checkFailure(e: unknown): { text: string; issues: Issue[] } {
  if (!(e instanceof ApiError)) return { text: CHECK_FAILED_TEXT, issues: [] };
  if (e.status === 422 && e.code === "invalid_policy") {
    return { text: INVALID_TEXT, issues: e.issues.length > 0 ? e.issues : [{ loc: [], msg: INVALID_TEXT }] };
  }
  if (e.status === 422) return { text: SHAPE_TEXT, issues: [] };
  if (e.status === 403) return { text: CHECK_FORBIDDEN_TEXT, issues: [] };
  if (e.status === 413) return { text: TOO_LARGE_TEXT, issues: [] };
  if (routeMissing(e)) return { text: CHECK_MISSING_TEXT, issues: [] };
  if (e.status === 401 || e.status === 429) return { text: errorMessage(e), issues: [] };
  return { text: CHECK_FAILED_TEXT, issues: [] };
}
