import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

describe("schedule review actions", () => {
  it("uses accessible icons for secondary draft actions", () => {
    const source = readFileSync(new URL("./ScheduleReviewPage.jsx", import.meta.url), "utf8");

    expect(source).toContain('aria-label="Discard draft"');
    expect(source).toContain('aria-label="Edit draft"');
    expect(source).toContain('aria-label="Review camera alignment"');
    expect(source).toContain("<ReviewActionIcon");
    expect(source).toContain("Activate schedule");
  });
});
