// Dữ liệu GIẢ cho Chính sách — chỉ dùng trong test (vitest) qua mocks/handlers/policy.ts. Hình dạng = route THẬT
// backend/app/api/policy.py (N-POL1): bản đang chạy nạp từ file → `version_id` 0, `version` "file-<8 hex>", `updated_by`
// null, `is_current` true; `/versions` = MẢNG TRẦN đúng 1 mục, `restored_from` null.
// Nội dung là luật MẪU trung tính (intent "demo") — KHÔNG chép config/policy.json (luật thật đọc từ backend thật).
// Xoá khi: N-POL2 thay test bằng hợp đồng đủ (lưu / quay lui) — xoá cùng mocks/handlers/policy.ts.

export const POLICY_DEMO = {
  constants: { DEMO_LIMIT: 3, THRESHOLD_LOW: 0.2, THRESHOLD_HIGH: 0.8 },
  rules: [
    { id: "D1", type: "allow", intent: "demo", action: "demo_read", description: "Luật mẫu: cho phép thao tác đọc" },
    { id: "D2", type: "approval_required", intent: "demo", action: "demo_change", description: "Luật mẫu: thay đổi cần duyệt" },
    { id: "D3", type: "deny", intent: "demo", action: "demo_remove", description: "Luật mẫu: không cho xoá" },
  ],
};

export const DEMO_VERSION = "file-0a1b2c3d";
export const DEMO_UPDATED_AT = "2026-10-01T01:00:00Z";
