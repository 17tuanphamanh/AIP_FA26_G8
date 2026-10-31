// Test đơn vị cho e2e/totp.ts bằng vector chuẩn RFC 6238 phụ lục B (SHA-1, secret ASCII "12345678901234567890").
// Chạy TAY bằng test runner có sẵn của Node (không cần vitest, không nằm trong `npm run test`):
//   node --test e2e/totp.test.ts          (Node ≥ 22.18 tự bỏ kiểu TS; Node cũ hơn: thêm --experimental-strip-types)
import assert from "node:assert/strict";
import { test } from "node:test";
import { base32Decode, hotp, totpAt, totpCounter } from "./totp.ts";

const RFC_SEED_ASCII = "12345678901234567890";
const RFC_SEED_B32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"; // base32 của RFC_SEED_ASCII

// RFC 6238 phụ lục B, cột SHA1 (8 chữ số) → 6 chữ số cuối là mã 6 số.
const VECTORS: [seconds: number, eight: string][] = [
  [59, "94287082"],
  [1111111109, "07081804"],
  [1111111111, "14050471"],
  [1234567890, "89005924"],
  [2000000000, "69279037"],
  [20000000000, "65353130"],
];

test("base32 của secret RFC giải ra đúng 20 byte ASCII", () => {
  assert.equal(base32Decode(RFC_SEED_B32).toString("ascii"), RFC_SEED_ASCII);
  assert.equal(base32Decode("gezd gnbv-gy3tqojqgezdgnbvgy3tqojq====").toString("ascii"), RFC_SEED_ASCII);
  assert.throws(() => base32Decode("GEZ1"), /không phải base32/);
  assert.throws(() => base32Decode("  "), /rỗng/);
});

test("T=59 → 287082 (6 số)", () => {
  assert.equal(totpAt(RFC_SEED_B32, totpCounter(59)), "287082");
});

test("đủ vector SHA-1 của RFC 6238 (8 số và 6 số)", () => {
  const key = Buffer.from(RFC_SEED_ASCII, "ascii");
  for (const [seconds, eight] of VECTORS) {
    assert.equal(hotp(key, totpCounter(seconds), 8), eight, `T=${seconds} (8 số)`);
    assert.equal(totpAt(RFC_SEED_B32, totpCounter(seconds)), eight.slice(-6), `T=${seconds} (6 số)`);
  }
});

test("giữ số 0 đầu", () => {
  assert.equal(totpAt(RFC_SEED_B32, totpCounter(1234567890)), "005924");
});
