import { describe, expect, it } from "vitest";

import { buildTimelineTicks, condenseTimelinePoints } from "./components";

describe("buildTimelineTicks", () => {
  it("uses human-friendly clock divisions while preserving both endpoints", () => {
    expect(buildTimelineTicks("08:00", "19:30").map(tick => tick.time)).toEqual([
      "08:00",
      "10:00",
      "12:00",
      "14:00",
      "16:00",
      "18:00",
      "19:30",
    ]);
  });
});

describe("condenseTimelinePoints", () => {
  it("retains readable, evenly distributed markers including both endpoints", () => {
    const points = Array.from({ length: 691 }, (_, index) => ({ time: String(index), percent: index / 6.9 }));
    const condensed = condenseTimelinePoints(points);

    expect(condensed).toHaveLength(40);
    expect(condensed[0]).toBe(points[0]);
    expect(condensed.at(-1)).toBe(points.at(-1));
  });
});
