// Mốc thời gian ISO 8601 CÓ múi giờ (`Z` hoặc `±hh:mm`) — hợp đồng thông báo §1/§2 (`created_at`, `server_now`, `deadline`).
// Thiếu múi giờ thì `Date.parse` đọc theo giờ máy → lệch 7 tiếng tuỳ máy: coi là sai, không đoán.
const ISO_TZ = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:\d{2})$/;

export const isIsoWithZone = (value: unknown): value is string =>
  typeof value === "string" && ISO_TZ.test(value) && !Number.isNaN(Date.parse(value));

/** ms của mốc ISO có múi giờ; sai dạng → null. */
export const isoMs = (value: unknown): number | null => (isIsoWithZone(value) ? Date.parse(value) : null);
