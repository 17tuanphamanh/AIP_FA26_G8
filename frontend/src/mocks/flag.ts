// KH 4.3 #1: dữ liệu giả CHỈ khi dev VÀ bật cờ. Ở bản build `import.meta.env.DEV` là hằng `false`
// nên mọi nhánh dùng cờ này bị loại khỏi bundle (`npm run check:dist` kiểm lại).
export const MOCK_ENABLED: boolean = import.meta.env.DEV && import.meta.env.VITE_API_MOCK === "1";
