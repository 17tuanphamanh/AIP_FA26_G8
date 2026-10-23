// ĐIỂM IMPORT DUY NHẤT về kiểu API cho component (KH mục 2, 3).
// Chuyển giả → thật: xoá kiểu ở `contracts-tam.ts`, re-export kiểu tương ứng từ `schema.gen.ts` (sinh bằng
// `npm run gen:api`) ngay tại file này — component không phải sửa.
// F0: chưa có `schema.gen.ts` (gen:api cần backend chạy — 12b Q-fe-1).
import type { components } from "./schema.gen.ts";

export type * from "./contracts-tam.ts";

type S = components["schemas"];

// ---------------------------------------------------------------- Chính sách (F7, route thật — N-POL1)
// backend/app/api/policy.py: GET /api/policy (`PolicyView`), GET /api/policy/versions (MẢNG TRẦN `PolicyVersionItem`),
// POST /api/policy/validate (200 `ValidateOk`; 422 `InvalidPolicy` | `InvalidRequestBody`). Nối tên schema với ĐÚNG
// route: src/api/schema.check.ts. Thân gửi đi của validate: `PolicyValidateIn` (contracts-tam.ts — route tự đọc thân).
export type PolicyView = S["PolicyView"];
export type PolicyVersionItem = S["PolicyVersionItem"];
export type PolicyValidateOk = S["ValidateOk"];
export type PolicyInvalid = S["InvalidPolicy"];
