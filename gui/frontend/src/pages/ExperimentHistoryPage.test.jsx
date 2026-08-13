import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

describe("experiment history", () => {
  it("offers metadata filtering and cleanup navigation", () => {
    const source = readFileSync(new URL("./ExperimentHistoryPage.jsx", import.meta.url), "utf8");
    expect(source).toContain("Metadata ledger");
    expect(source).toContain("raw_data_blocker_ids");
    expect(source).toContain("metadata records retained");
    expect(source).toContain("Raw files exported and removed");
  });
});
