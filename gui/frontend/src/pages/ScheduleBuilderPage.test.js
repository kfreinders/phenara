import { describe, expect, it } from "vitest";

import { buildModePreview, resetScheduleForm } from "./ScheduleBuilderPage";

describe("resetScheduleForm", () => {
  it("restores schedule defaults while preserving the analysis workflow choice", () => {
    const defaults = {
      experiment_name: "",
      analysis_enabled: false,
      start_date: "",
      num_days: 14,
      mode: "every",
    };
    const current = {
      experiment_name: "Changed experiment",
      analysis_enabled: true,
      start_date: "2026-08-10",
      num_days: 3,
      mode: "duration",
    };

    expect(resetScheduleForm(current, defaults, "2026-07-28")).toMatchObject({
      ...defaults,
      analysis_enabled: true,
      start_date: "2026-07-28",
    });
  });

  it("does not drop fields when an older backend omits defaults", () => {
    const current = {
      experiment_name: "Changed experiment",
      researcher: "Researcher",
      analysis_enabled: false,
      start_date: "2026-08-10",
      num_days: 3,
      future_field: "preserved",
    };

    const reset = resetScheduleForm(
      current,
      { analysis_enabled: false },
      "2026-07-28",
    );

    expect(reset.start_date).toBe("2026-07-28");
    expect(reset.num_days).toBe(14);
    expect(reset.every_start).toBe("08:00");
    expect(reset.future_field).toBe("preserved");
  });
});

describe("buildModePreview", () => {
  it("builds an every-n-minutes window without forcing a non-aligned endpoint", () => {
    const preview = buildModePreview({
      mode: "every",
      every_start: "09:00",
      every_end: "09:45",
      every_step_minutes: 30,
    });

    expect(preview).toMatchObject({ valid: true, start: 540, end: 585, captureCount: 2 });
    expect(preview.points).toEqual([540, 570]);
  });

  it("derives a fixed-duration window", () => {
    const preview = buildModePreview({
      mode: "duration",
      duration_start: "12:00",
      duration_minutes: 60,
      duration_step_minutes: 20,
    });

    expect(preview).toMatchObject({ valid: true, start: 720, end: 780, captureCount: 4 });
    expect(preview.points).toEqual([720, 740, 760, 780]);
  });

  it("steps centered captures from the start rather than forcing the center", () => {
    const preview = buildModePreview({
      mode: "centered",
      centered_center: "12:00",
      centered_before_minutes: 45,
      centered_after_minutes: 45,
      centered_step_minutes: 30,
    });

    expect(preview).toMatchObject({ valid: true, start: 675, end: 765, center: 720, captureCount: 4 });
    expect(preview.points).toEqual([675, 705, 735, 765]);
    expect(preview.points).not.toContain(720);
  });

  it("rejects incomplete, reversed, and cross-midnight windows", () => {
    expect(buildModePreview({ mode: "every", every_start: "09:", every_end: "10:00", every_step_minutes: 30 }).valid).toBe(false);
    expect(buildModePreview({ mode: "every", every_start: "10:00", every_end: "09:00", every_step_minutes: 30 }).valid).toBe(false);
    expect(buildModePreview({ mode: "duration", duration_start: "23:30", duration_minutes: 60, duration_step_minutes: 15 }).valid).toBe(false);
  });

  it("supports zero-duration windows and condenses dense markers", () => {
    const single = buildModePreview({ mode: "duration", duration_start: "09:00", duration_minutes: 0, duration_step_minutes: 30 });
    const dense = buildModePreview({ mode: "every", every_start: "00:00", every_end: "23:59", every_step_minutes: 1 });

    expect(single).toMatchObject({ valid: true, captureCount: 1, points: [540] });
    expect(dense.captureCount).toBe(1440);
    expect(dense.points).toHaveLength(40);
    expect(dense.points[0]).toBe(0);
    expect(dense.points.at(-1)).toBe(1439);
  });
});
