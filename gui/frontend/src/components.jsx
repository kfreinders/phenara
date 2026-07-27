import { useEffect, useRef, useState } from "react";

export function HelpTip({ id, label, children }) {
  const [open, setOpen] = useState(false);
  const root = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const closeOutside = event => { if (!root.current?.contains(event.target)) setOpen(false); };
    const closeOnEscape = event => { if (event.key === "Escape") { setOpen(false); root.current?.querySelector('[role="button"]')?.focus(); } };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => { document.removeEventListener("pointerdown", closeOutside); document.removeEventListener("keydown", closeOnEscape); };
  }, [open]);
  const toggleWithKeyboard = event => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setOpen(current => !current);
    }
  };
  return <span className={`mode-help${open ? " is-open" : ""}`} ref={root} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false); }}>
    <span className="mode-help-trigger" role="button" tabIndex="0" aria-label={`Explain ${label}`} aria-expanded={open} aria-describedby={id} onClick={() => setOpen(current => !current)} onKeyDown={toggleWithKeyboard}>(?)</span>
    <span className="mode-help-tooltip" id={id} role="tooltip">{children}</span>
  </span>;
}

export function WorkflowSteps({ current, analysisEnabled = false }) {
  const steps = analysisEnabled
    ? ["Capture mode", "Schedule", "Align camera", "Calibrate", "Review", "Activate"]
    : ["Capture mode", "Schedule", "Align camera", "Review", "Activate"];
  return <ol className="workflow-steps" style={{ "--workflow-step-count": steps.length }} aria-label="Schedule activation progress">
    {steps.map((label, index) => {
      const number = index + 1;
      const complete = number < current;
      const currentStep = number === current;
      return <li key={label} className={`workflow-step${complete ? " workflow-step--complete" : ""}${currentStep ? " workflow-step--current" : ""}`} aria-current={currentStep ? "step" : undefined}>
        <span>{complete ? "✓" : number}</span><strong>{label}</strong>
      </li>;
    })}
  </ol>;
}

export function Loading({ label = "Loading" }) {
  return <section className="card react-loading" role="status"><span className="react-spinner" />{label}</section>;
}

export function ErrorNotice({ error }) {
  return error ? <section className="alert error" role="alert">{error.message ?? error}</section> : null;
}

export function SchedulePreview({ preview }) {
  const timelineTicks = buildTimelineTicks(preview.first_time, preview.last_time);
  const timelinePoints = condenseTimelinePoints(preview.timeline_points);
  const timelineCondensed = timelinePoints.length < preview.timeline_points.length;
  const extraReplicates = Math.max(preview.replicates - 1, 0);
  const shownReplicates = Math.min(extraReplicates, 8);
  return <section className="preview-panel">
    <div className="preview-overview">
      <article className="preview-overview-card"><span>Experiment dates</span><div className="preview-range"><strong>{preview.start_date.replaceAll("-", "/")}</strong><i aria-hidden="true">→</i><strong>{preview.end_date.replaceAll("-", "/")}</strong></div><small>{preview.num_days} day{preview.num_days === 1 ? "" : "s"}</small></article>
      <article className="preview-overview-card"><span>Daily imaging window</span><div className="preview-range"><strong>{preview.first_time}</strong><i aria-hidden="true">→</i><strong>{preview.last_time}</strong></div><small>{preview.daily_time_points} time point{preview.daily_time_points === 1 ? "" : "s"} per day</small></article>
      <article className="preview-overview-card"><span>Capture volume</span><strong className="preview-total">{preview.total_captures}</strong><small>{preview.daily_captures} per day · {preview.replicates} per time point</small></article>
    </div>
    <div className="visual-preview-grid">
      <section className="schedule-graphic-card">
        <div className="graphic-card-header"><h3>Daily imaging window</h3><p>{preview.summary_sentence}</p>{timelineCondensed && <small>Markers are condensed for readability; all {preview.daily_time_points} time points remain scheduled.</small>}</div>
        <div className="timeline-shell" aria-label="Daily capture timeline">
          <div className={`timeline-axis${timelineCondensed ? " timeline-axis--condensed" : ""}`}>
            {timelineTicks.map(tick => <span className="timeline-tick" style={{ left: `${tick.percent}%`, "--timeline-delay": `${100 + tick.percent * 5}ms` }} key={tick.time} />)}
            {timelinePoints.map(point => <span className="timeline-capture" style={{ left: `${point.percent}%`, "--timeline-delay": `${100 + point.percent * 5}ms` }} title={`${point.time}: ${preview.replicates} capture${preview.replicates === 1 ? "" : "s"}`} key={point.time}>{extraReplicates > 0 && <span className="timeline-replicates" aria-label={`${extraReplicates} additional replicate${extraReplicates === 1 ? "" : "s"} at ${point.time}`}>{Array.from({ length: shownReplicates }, (_, index) => <i key={index} />)}{extraReplicates > shownReplicates && <small>+{extraReplicates - shownReplicates}</small>}</span>}<i className="timeline-point" /></span>)}
          </div>
          <div className="timeline-scale">{timelineTicks.map(tick => <span style={{ left: `${tick.percent}%` }} key={tick.time}>{tick.time}</span>)}</div>
        </div>
      </section>
    </div>
  </section>;
}

export function buildTimelineTicks(first, last) {
  const toMinutes = value => { const [hours, minutes] = value.split(":").map(Number); return hours * 60 + minutes; };
  const format = value => `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
  const start = toMinutes(first); const end = toMinutes(last); const span = Math.max(end - start, 0);
  if (!span) return [{ time: first, percent: 0 }];
  const intervals = [1, 2, 5, 10, 15, 30, 60, 120, 180, 240, 360, 720];
  const interval = intervals.find(value => value >= span / 6) ?? 720;
  const values = [start];
  for (let value = Math.ceil((start + 1) / interval) * interval; value < end; value += interval) values.push(value);
  values.push(end);
  return values.map(value => ({ time: format(value), percent: ((value - start) / span) * 100 }));
}

export function condenseTimelinePoints(points, limit = 40) {
  if (points.length <= limit) return points;
  const indexes = Array.from({ length: limit }, (_, index) => Math.round(index * (points.length - 1) / (limit - 1)));
  return indexes.map(index => points[index]);
}
