// ĐIỂM IMPORT DUY NHẤT về kiểu API cho component (KH mục 2, 3).
// Chuyển giả → thật: xoá kiểu ở `contracts-tam.ts`, re-export kiểu tương ứng từ `schema.gen.ts` (sinh bằng
// `npm run gen:api`) ngay tại file này — component không phải sửa.
// F0: chưa có `schema.gen.ts` (gen:api cần backend chạy — 12b Q-fe-1).
export type * from "./contracts-tam.ts";
