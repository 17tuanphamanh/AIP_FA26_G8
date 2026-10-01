// Thông báo MỘT lần đi kèm điều hướng: mã nằm trong history state (`navigate(to, { state: flashState(…) })`), KHÔNG vào
// URL. Chỉ hiện câu trong bảng dưới — không bao giờ hiện chữ tuỳ ý lấy từ state.
export const FLASH = {
  override_other_user: "Bạn đã đăng nhập bằng tài khoản khác — thao tác ghi đè đã huỷ.",
  policy_other_user: "Bạn đã đăng nhập bằng tài khoản khác — thao tác trên chính sách đã huỷ.",
} as const;

export type FlashKey = keyof typeof FLASH;

export const flashState = (key: FlashKey) => ({ flash: key });

export function flashText(state: unknown): string | null {
  const key = (state as { flash?: unknown } | null)?.flash;
  return typeof key === "string" && Object.hasOwn(FLASH, key) ? FLASH[key as FlashKey] : null;
}
