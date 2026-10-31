// TOTP RFC 6238 (HOTP RFC 4226): HMAC-SHA-1, 6 chữ số, bước 30 s, mốc T0 = 0 — chỉ dùng `node:crypto`, không thư viện.
// Dùng cho test quản lý (quan.tm): sinh mã từ E2E_MANAGER_TOTP_SECRET (base32, đúng secret đã enroll MFA). Hàm không
// in, không ghi secret hay mã.
import { createHmac } from "node:crypto";

export const TOTP_STEP_SECONDS = 30;
export const TOTP_DIGITS = 6;

const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/** Giải base32 (RFC 4648): bỏ qua dấu cách, gạch nối, '=' cuối; không phân biệt hoa thường. Ký tự lạ → ném lỗi. */
export function base32Decode(text: string): Buffer {
  const clean = text.replace(/[\s-]/g, "").replace(/=+$/, "").toUpperCase();
  if (clean.length === 0) throw new Error("secret TOTP rỗng");
  let bits = 0;
  let value = 0;
  const bytes: number[] = [];
  for (const char of clean) {
    const index = BASE32.indexOf(char);
    if (index < 0) throw new Error("secret TOTP không phải base32 (A–Z, 2–7)"); // không đưa ký tự vào thông báo
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((value >>> bits) & 0xff);
    }
  }
  return Buffer.from(bytes);
}

/** HOTP(K, C): HMAC-SHA-1 rồi cắt động (RFC 4226 §5.3), `digits` chữ số, giữ số 0 đầu. */
export function hotp(key: Buffer, counter: number, digits = TOTP_DIGITS): string {
  const message = Buffer.alloc(8);
  message.writeBigUInt64BE(BigInt(counter));
  const mac = createHmac("sha1", key).update(message).digest();
  const offset = (mac[mac.length - 1] ?? 0) & 0x0f;
  const binary = (mac.readUInt32BE(offset) & 0x7fffffff) % 10 ** digits;
  return String(binary).padStart(digits, "0");
}

/** Bước thời gian (counter) tại `unixSeconds`. */
export const totpCounter = (unixSeconds: number, step = TOTP_STEP_SECONDS): number => Math.floor(unixSeconds / step);

/** Mã TOTP của secret base32 tại bước `counter`. */
export const totpAt = (secretBase32: string, counter: number, digits = TOTP_DIGITS): string =>
  hotp(base32Decode(secretBase32), counter, digits);
