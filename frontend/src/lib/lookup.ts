// Tra bảng theo khoá không tin cậy (server trả, URL, ô nhập) — dùng chung mọi màn.

/**
 * Tra bảng theo khoá RIÊNG của bảng (`Object.hasOwn`), không đi qua prototype: khoá do server trả hoặc người gõ (severity,
 * rule_id, audience, khoá map…) như "__proto__" / "constructor" / "toString" mà tra `X[k]` sẽ ra object/hàm của
 * Object.prototype → React vỡ màn hoặc hiện "function …". Không có → `fallback`.
 */
export function ownEntry<T>(table: Readonly<Record<string, T>>, key: string, fallback: NoInfer<T>): T {
  return Object.hasOwn(table, key) ? (table[key] as T) : fallback;
}
/** Nhãn theo khoá; khoá lạ → hiện nguyên khoá. */
export const labelOf = (table: Readonly<Record<string, string>>, key: string): string => ownEntry(table, key, key);
