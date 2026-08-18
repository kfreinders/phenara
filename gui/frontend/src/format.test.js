import { describe, expect, it } from "vitest";
import { formatBytes, relativeFutureTime } from "./format";

describe("dashboard formatting", () => {
  it("formats storage with compact decimal units", () => {
    expect(formatBytes(null)).toBe("—");
    expect(formatBytes(7_600_000)).toBe("8 MB");
    expect(formatBytes(12_500_000_000)).toBe("12.5 GB");
  });

  it("formats future capture times relative to a supplied clock", () => {
    const now = new Date("2026-07-23T00:00:00Z");
    expect(relativeFutureTime("2026-07-23T00:00:25Z", now)).toBe("in 25 sec");
    expect(relativeFutureTime("2026-07-23T01:30:00Z", now)).toBe("in 1 hr 30 min");
  });
});

