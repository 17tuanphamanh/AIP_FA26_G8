// Hàm thuần của tab "So sánh phương án" (hợp đồng N-PA §2). KHÔNG xếp hạng, KHÔNG tô màu, KHÔNG mũi tên, KHÔNG điểm tổng:
// mỗi ô chỉ là chữ. Định dạng dùng chung với các tab khác (metrics.ts).
import type { StrategiesDashboard, StrategyMetric, StrategyRatio, StrategySource, StrategyValue } from "../../api/types.ts";
import { formatRate, formatUsd } from "./metrics.ts";

/** Mẫu số / số ca dưới ngưỡng này → "chưa đủ dữ liệu (n=…)". */
export const MIN_SAMPLE = 20;
export const NO_VALUE = "—";
export const COMPARE_NOTE =
  "Các chỉ số vận hành không có chiều tốt hơn, tuỳ ưu tiên của đơn vị. Tỉ lệ bỏ sót ca cần người chỉ đo được trên bộ tình huống có nhãn (báo cáo đánh giá).";
export const SIM_BAND = "DỮ LIỆU THỬ";
export const COMPARE_MISSING_TEXT = "Máy chủ chưa có số liệu so sánh phương án.";
export const UNAVAILABLE_CELL = "Chưa có dữ liệu";
/** Nguồn số liệu: "Thật" (mặc định) / "Dữ liệu thử" — không có "tất cả". */
export const SOURCES: readonly { key: StrategySource; label: string }[] = [
  { key: "real", label: "Thật" },
  { key: "sim", label: "Dữ liệu thử" },
];

const NBSP = "\u00a0";
const integer = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 });
const decimal = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 });
const few = (n: number) => `chưa đủ dữ liệu (mới có ${integer.format(n)} ca)`;

function valueText(value: number, unit: string | undefined): string {
  switch (unit) {
    case "count":
      return integer.format(value);
    case "s":
      return `${decimal.format(value)}${NBSP}giây`;
    case "min":
      // Gọn 13/11 (TA): 0 < x < 0,05 phút làm tròn thành "0 phút" trông như lỗi → nói theo giây.
      if (value > 0 && value < 1) return `${integer.format(Math.max(1, Math.round(value * 60)))}${NBSP}giây`;
      return `${decimal.format(value)}${NBSP}phút`;
    case "usd":
      return `${formatUsd(value)}${NBSP}USD`;
    case undefined:
      return decimal.format(value);
    default:
      return `${decimal.format(value)}${NBSP}${unit}`;
  }
}

/**
 * Chữ của một ô. Thứ tự: ô null → "—"; ratio: mẫu < 20 → "chưa đủ dữ liệu (n=mẫu)", còn lại "<tỉ lệ> (a/b)"; value: có `n`
 * < 20 → "chưa đủ dữ liệu (n=…)", `value` null → "—", còn lại số + đơn vị (+ " (n=…)" khi có `n`).
 */
export function cellText(metric: Pick<StrategyMetric, "kind" | "unit">, cell: StrategyRatio | StrategyValue | null): string {
  if (cell === null) return NO_VALUE;
  if (metric.kind === "ratio") {
    const { num, den } = cell as StrategyRatio;
    if (den < MIN_SAMPLE) return few(den);
    return `${formatRate(num / den)} (${integer.format(num)} trên ${integer.format(den)} ca)`; // gọn 13/11 (TA)
  }
  const { value, n } = cell as StrategyValue;
  if (n !== undefined && n < MIN_SAMPLE) return few(n);
  if (value === null) return NO_VALUE;
  return `${valueText(value, metric.unit)}${n === undefined ? "" : ` (đo trên ${integer.format(n)} ca)`}`;
}

/** Các loại yêu cầu của bảng phụ: theo thứ tự xuất hiện đầu tiên khi đi qua các cột (thứ tự server), không sắp. */
export function intentKeys(strategies: readonly string[], mix: Record<string, Record<string, number>>): string[] {
  const keys: string[] = [];
  for (const s of strategies) {
    const row = Object.hasOwn(mix, s) ? mix[s]! : {};
    for (const k of Object.keys(row)) if (!keys.includes(k)) keys.push(k);
  }
  return keys;
}

export function intentCell(mix: Record<string, Record<string, number>>, strategy: string, intent: string): string {
  const row = Object.hasOwn(mix, strategy) ? mix[strategy]! : null;
  return row && Object.hasOwn(row, intent) ? integer.format(row[intent]!) : NO_VALUE;
}

/** Phương án có ít nhất một ô số (khác null) — cột toàn "—" làm bảng trông như lỗi (gọn 13/11, TA). */
export function strategiesWithData(data: StrategiesDashboard): string[] {
  const has = data.strategies.filter((s) => data.metrics.some((m) => Object.hasOwn(m.values, s) && m.values[s] !== null && m.values[s] !== undefined));
  return has.length > 0 ? has : [...data.strategies];
}

export const HIDDEN_STRATEGY_NOTE = (names: string[]) =>
  `Chưa có ticket thật cho: ${names.join("; ")}. Các phương án này chỉ chạy trên bộ tình huống thử — chọn “Dữ liệu thử” để so sánh đủ.`;
