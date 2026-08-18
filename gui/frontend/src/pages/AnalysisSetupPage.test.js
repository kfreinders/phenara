import { describe, expect, it } from "vitest";

import { adjustCrop } from "./AnalysisSetupPage";

describe("adjustCrop", () => {
  const crop = { x: 0.2, y: 0.2, width: 0.6, height: 0.6 };

  it("moves the existing area without changing its size", () => {
    expect(adjustCrop(crop, "move", undefined, 0.1, -0.1)).toEqual({
      x: 0.3, y: 0.1, width: 0.6, height: 0.6,
    });
  });

  it("resizes from an individual corner", () => {
    expect(adjustCrop(crop, "resize", "nw", 0.1, 0.05)).toEqual({
      x: 0.3, y: 0.25, width: 0.5, height: 0.55,
    });
  });

  it("keeps moves, handles, and minimum size inside the image", () => {
    expect(adjustCrop(crop, "move", undefined, 2, 2)).toEqual({
      x: 0.4, y: 0.4, width: 0.6, height: 0.6,
    });
    const resized = adjustCrop(crop, "resize", "nw", 2, 2);
    expect(resized.width).toBeCloseTo(0.02);
    expect(resized.height).toBeCloseTo(0.02);
  });
});
