import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";

describe("experiment history", () => {
  it("offers metadata filtering and cleanup navigation", () => {
    const source = readFileSync(new URL("./ExperimentHistoryPage.jsx", import.meta.url), "utf8");
    expect(source).toContain("Experiment history");
    expect(source).not.toContain("Metadata ledger");
    expect(source).toContain("raw_data_blocker_ids");
    expect(source).toContain("metadata records retained");
    expect(source).toContain("Raw files exported and removed");
  });

  it("presents the retained record metadata graphically", () => {
    const source = readFileSync(new URL("./ExperimentDownloadPage.jsx", import.meta.url), "utf8");
    expect(source).toContain("Capture results");
    expect(source).toContain("Protocol summary");
    expect(source).toContain("Full experiment configuration");
    expect(source).toContain("Copy schedule JSON");
    expect(source).toContain("Download schedule JSON");
    expect(source).toContain("<h3>Metadata</h3>");
    expect(source).toContain("record-outcome-bar");
    expect(source).toContain("Schedule SHA-256");
    expect(source).not.toContain("Back to scheduler overview");
    expect(source).not.toContain("Back to experiment history");
  });
});
