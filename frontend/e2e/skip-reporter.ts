// Reporter `list` không in lý do test.skip → in thêm ở cuối lượt: test nào bị BỎ QUA và vì sao (vd thiếu biến môi
// trường). Lý do chỉ là tên biến / câu cố định trong test — không bao giờ chứa giá trị bí mật.
import type { Reporter, TestCase, TestResult } from "@playwright/test/reporter";

export default class SkipReasonReporter implements Reporter {
  private readonly skipped: string[] = [];

  onTestEnd(test: TestCase, result: TestResult): void {
    if (result.status !== "skipped") return;
    const reason = test.annotations.find((a) => a.type === "skip")?.description ?? "không ghi lý do";
    this.skipped.push(`  - ${test.title}: ${reason}`);
  }

  onEnd(): void {
    if (this.skipped.length === 0) return;
    process.stdout.write(`\nBỎ QUA ${this.skipped.length} test:\n${this.skipped.join("\n")}\n`);
  }

  printsToStdio(): boolean {
    return true;
  }
}
