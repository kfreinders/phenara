import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { buildTimelineTicks, ErrorNotice, Loading } from "../components";
import { useSchedulerStatus } from "../hooks";
import { formatBytes, formatDateTime, relativeFutureTime } from "../format";

const lifecycleLabels = { upcoming: "Upcoming", active: "Active", finished: "Finished", empty: "Empty schedule" };

function NextAction({ schedule, draftState, summary, analysis }) {
  if (draftState === "ready") return <section className="card schedule-action"><div><span className="eyebrow">Schedule draft</span><h3>Draft ready for review</h3><p>Continue reviewing the saved draft before activating it.</p></div><Link className="primary-link" to="/schedule/review">Review draft</Link></section>;
  if (draftState === "invalid") return <section className="card schedule-action"><div><span className="eyebrow">Schedule draft</span><h3>Draft needs attention</h3><p>Open the schedule builder to correct the saved draft.</p></div><Link className="primary-link" to="/schedule">Open schedule builder</Link></section>;
  if (schedule?.lifecycle !== "finished") return null;
  if (analysis && (analysis.pending > 0 || analysis.running > 0)) return <section className="card schedule-action"><div><span className="eyebrow">Finishing experiment</span><h3>Analyzing captured images</h3><p>The download will become available after the remaining image analysis completes.</p></div><strong>{analysis.succeeded} / {analysis.total}</strong></section>;
  const issues = summary && summary.failed + summary.missed + summary.elapsed_unreported > 0;
  return <section className="card schedule-action"><div><span className="eyebrow">Experiment complete</span><h3>{issues ? "Experiment finished with capture issues" : "Experiment finished"}</h3><p>{issues ? "Review the outcomes, then download the experiment data." : "Download the completed dataset to your computer."}</p></div><Link className="primary-link" to={`/experiments/${schedule.run.id}`}>Download experiment data</Link></section>;
}

export function SchedulerPage() {
  const { data, error } = useSchedulerStatus();
  if (!data && !error) return <Loading label="Loading scheduler overview" />;
  if (!data) return <ErrorNotice error={error} />;
  const schedule = data.schedule;
  const storageRisk = schedule && data.storage && schedule.estimated_remaining_storage_bytes > data.storage.free_bytes;
  return <section className="scheduler-page" aria-live="polite">
    <div className="scheduler-heading"><div><h2>Scheduler overview</h2><p>Live service health and planned experiment progress.</p></div></div>
    {data.status === "unavailable" && <div className="health-alert" role="alert">{data.message}</div>}
    {(data.schedule_error || data.schedule_is_last_reported || data.status === "invalid_schedule") && <div className="schedule-warning">{data.schedule_error ?? (data.schedule_is_last_reported ? "Showing the last reported schedule; live state cannot currently be confirmed." : "The edited schedule was rejected. The valid schedule remains active.")}</div>}
    {storageRisk && <div className="storage-risk" role="alert">Storage risk: remaining captures need approximately {formatBytes(schedule.estimated_remaining_storage_bytes)}, but only {formatBytes(data.storage.free_bytes)} is free.</div>}
    <NextAction schedule={schedule} draftState={data.draft_state} summary={data.capture_summary} analysis={data.analysis_summary} />
    {!schedule ? <section className="card schedule-empty"><h3>No schedule loaded</h3><Link className="primary-link" to={data.draft_state === "ready" ? "/schedule/review" : "/schedule"}>{data.draft_state === "ready" ? "Review draft" : "Create a schedule"}</Link></section> : <Dashboard data={data} />}
  </section>;
}

function Dashboard({ data }) {
  const s = data.schedule; const storage = data.storage;
  const details = [s.run?.researcher, s.run?.notes].filter(Boolean).join(" · ");
  return <div id="schedule-dashboard">
    <section className="schedule-hero card"><div className="schedule-identity"><span className={`lifecycle-badge lifecycle-badge--${s.lifecycle}`}>{lifecycleLabels[s.lifecycle] ?? s.lifecycle}</span><h3>{s.run?.name ?? (s.lifecycle === "finished" ? "Completed experiment schedule" : "Current experiment schedule")}</h3><p>{s.start_date} → {s.end_date} · {s.num_days} day{s.num_days === 1 ? "" : "s"}</p><p className="schedule-finish"><span>Finishes at</span><strong>{formatDateTime(s.last_capture_at)}</strong></p>{details && <p className="schedule-run-details">{details}</p>}<ScheduleStorage storage={storage} /></div>
      <ScheduleProgressRing schedule={s} /></section>
    <CaptureResults summary={data.capture_summary} dailyProgress={data.daily_capture_progress} />
    <AnalysisProgress summary={data.analysis_summary} />
    <section className="card overview-card"><div className="section-heading"><div><h3>Experiment timeline</h3><p>Planned progress across each experiment day.</p></div></div><div className="experiment-days">{s.days.map(day => <div className={`experiment-day experiment-day--${day.status}`} title={`${day.elapsed_captures} of ${day.total_captures} captures elapsed`} key={day.number}><strong>Day {day.number}</strong><span>{new Date(`${day.date}T12:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}</span></div>)}</div><div className="day-legend"><span className="complete">Complete</span><span className="current">Current</span><span className="upcoming">Upcoming</span></div></section>
    <DailyActivity schedule={s} />
    <StopExperiment schedule={s} initiallyPending={data.cancellation_pending} />
  </div>;
}

function ScheduleProgressRing({ schedule }) {
  const progress = useAnimatedProgress(schedule.progress_percent);
  const complete = progress >= 99.995;
  const [displayMode, setDisplayMode] = useState("idle");
  const modeClass = displayMode === "count"
    ? " progress-ring--show-count"
    : displayMode === "percentage"
      ? " progress-ring--show-percentage"
      : "";
  return <div className={`progress-ring${complete ? " progress-ring--complete" : ""}${modeClass}`} style={{ "--progress": `${progress * 3.6}deg` }} role="img" tabIndex="0" aria-label={`${schedule.progress_percent}% schedule progress. ${schedule.elapsed_captures} of ${schedule.total_captures} planned captures completed.`} onMouseEnter={() => setDisplayMode("count")} onMouseLeave={() => setDisplayMode("percentage")} onFocus={() => setDisplayMode("count")} onBlur={() => setDisplayMode("percentage")}><div className="progress-ring-value"><strong className="progress-ring-percentage">{progress.toFixed(1)}%</strong><strong className="progress-ring-count">{schedule.elapsed_captures} / {schedule.total_captures}</strong></div></div>;
}

function useAnimatedProgress(target, duration = 700) {
  const normalizedTarget = Math.max(0, Math.min(100, Number(target) || 0));
  const [value, setValue] = useState(0);
  const current = useRef(0);
  useEffect(() => {
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
      current.current = normalizedTarget;
      setValue(normalizedTarget);
      return;
    }
    const startValue = current.current;
    const difference = normalizedTarget - startValue;
    if (Math.abs(difference) < 0.01) return;
    const startedAt = performance.now();
    let frame;
    const animate = now => {
      const elapsed = Math.min((now - startedAt) / duration, 1);
      const next = startValue + difference * easeOutCubic(elapsed);
      current.current = next;
      setValue(next);
      if (elapsed < 1) frame = window.requestAnimationFrame(animate);
    };
    frame = window.requestAnimationFrame(animate);
    return () => window.cancelAnimationFrame(frame);
  }, [normalizedTarget, duration]);
  return value;
}

export function easeOutCubic(value) {
  return 1 - Math.pow(1 - value, 3);
}

function AnalysisProgress({ summary }) {
  if (!summary) return null;
  const completed = summary.succeeded + summary.failed;
  const percent = summary.total ? completed / summary.total * 100 : 0;
  const stateLabel = summary.state === "running"
    ? "Analyzing image"
    : summary.state === "unavailable"
      ? "Analysis environment unavailable"
    : summary.pending > 0
      ? "Waiting for a safe capture gap"
      : "Analysis up to date";
  const description = summary.state === "unavailable"
    ? "The configured Python environment is missing the canopy-analysis dependencies. Ask the system administrator to repair the installation."
    : "Analysis runs only when there is enough protected time before the next capture.";
  return <section className="card analysis-progress-card"><div><span className="eyebrow">Automatic analysis</span><h3>{stateLabel}</h3><p>{description}</p></div><div className="analysis-progress-summary"><strong>{summary.succeeded} / {summary.total}</strong><span>images analyzed</span>{summary.failed > 0 && <small>{summary.failed} failed after retrying</small>}</div><div className="analysis-progress-meter" role="progressbar" aria-label={`${completed} of ${summary.total} images processed`} aria-valuenow={completed} aria-valuemin="0" aria-valuemax={summary.total}><i style={{ width: `${percent}%` }} /></div></section>;
}

function ScheduleStorage({ storage }) {
  if (!storage) return <div className="schedule-storage"><span>Capture storage unavailable</span></div>;
  const state = storage.used_percent >= 95 ? "critical" : storage.used_percent >= 90 ? "warning" : "normal";
  return <div className={`schedule-storage schedule-storage--${state}`}><div><span>Capture storage</span><strong>{formatBytes(storage.free_bytes)} free</strong><small>{storage.used_percent.toFixed(1)}% used</small></div><div className={`storage-meter${state === "critical" ? " storage-meter--critical" : state === "warning" ? " storage-meter--warning" : ""}`} role="progressbar" aria-label={`${storage.used_percent.toFixed(1)}% of capture storage used`} aria-valuenow={storage.used_percent} aria-valuemin="0" aria-valuemax="100"><i className="storage-meter-fill" style={{ width: `${Math.min(100, storage.used_percent)}%` }} /></div></div>;
}

function StopExperiment({ schedule, initiallyPending }) {
  const [confirming, setConfirming] = useState(false);
  const [accepted, setAccepted] = useState(false);
  const [pending, setPending] = useState(initiallyPending);
  const [error, setError] = useState(null);
  if (!["active", "upcoming"].includes(schedule.lifecycle)) return null;
  const upcoming = schedule.lifecycle === "upcoming";
  const title = upcoming ? "Cancel scheduled experiment" : "Stop experiment";
  const description = upcoming
    ? "Prevent this experiment from starting. Its schedule will be archived."
    : "Cancel all remaining captures while preserving data already collected.";
  const confirmation = upcoming
    ? "I understand that no captures will be taken for this experiment."
    : "I understand that this experiment cannot be resumed.";
  const stop = async () => {
    setPending(true); setError(null);
    try {
      await api("/api/scheduler/cancel", { method: "POST", body: JSON.stringify({ schedule_hash: schedule.hash }) });
      setConfirming(false);
    } catch (reason) {
      setPending(false); setError(reason);
    }
  };
  return <section className="card stop-experiment">
    <div><h3>{title}</h3><p>{description}</p>{error && <small className="blocked-copy">{error.message}</small>}</div>
    {!confirming ? <div className="stop-actions"><Link className="button-link secondary" to="/schedule">Replace schedule…</Link><button className="danger-button" disabled={pending || initiallyPending} onClick={() => setConfirming(true)}>{pending || initiallyPending ? (upcoming ? "Cancelling schedule…" : "Stopping experiment…") : title}</button></div> : <div className="stop-confirmation"><label><input type="checkbox" checked={accepted} onChange={event => setAccepted(event.target.checked)} /> {confirmation}</label><div><button className="secondary" onClick={() => { setConfirming(false); setAccepted(false); }}>{upcoming ? "Keep schedule" : "Keep running"}</button><button className="danger-button" disabled={!accepted || pending} onClick={stop}>{upcoming ? "Cancel experiment" : "Stop remaining captures"}</button></div></div>}
  </section>;
}

function CaptureResults({ summary, dailyProgress }) {
  if (!summary) return null;
  const results = [
    { key: "succeeded", label: "Successful", value: summary.succeeded, kind: "success" },
    { key: "failed", label: "Failed", value: summary.failed, kind: "failure" },
    { key: "missed", label: "Missed", value: summary.missed, kind: "missed" },
    { key: "pending", label: "Result pending", value: summary.elapsed_unreported, kind: "pending" },
    { key: "remaining", label: "Remaining", value: summary.remaining, kind: "remaining" },
  ];
  const total = summary.total || results.reduce((sum, result) => sum + result.value, 0);
  const visibleResults = results.filter(result => result.key !== "pending" || result.value > 0);
  const percentage = value => total ? (value / total) * 100 : 0;
  const distribution = results.map(result => `${result.label}: ${result.value}`).join(", ");
  return <section className="card capture-results"><div className="section-heading"><div><h3>Capture results</h3><p>Recorded outcomes for the current experiment run.</p></div></div><div className="capture-result-grid">
    <div className="capture-result-bar" role="img" aria-label={`${total} total captures. ${distribution}.`}>
      {results.filter(result => result.value > 0).map(result => <span className={`capture-result-segment capture-result-segment--${result.kind}`} style={{ flexBasis: `${percentage(result.value)}%` }} title={`${result.label}: ${result.value} (${percentage(result.value).toFixed(1)}%)`} key={result.key} />)}
    </div>
    <div className="capture-result-legend">{visibleResults.map(result => <div className={`capture-result-key capture-result-key--${result.kind}`} key={result.key}><span className="capture-result-swatch" aria-hidden="true" /><span>{result.label}</span><strong>{result.value}</strong><small>{percentage(result.value).toFixed(1)}%</small></div>)}</div>
  </div><DailyCaptureProgress progress={dailyProgress} /></section>;
}

function DailyCaptureProgress({ progress }) {
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    if (!selected) return undefined;
    const close = event => { if (event.key === "Escape") setSelected(null); };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [selected]);
  if (!progress?.points?.length) return null;
  const { points, ticks, next, completedWidth, pulseStart, pulseWidth } = buildCaptureProgress(progress);
  const dateLabel = progress.date.replaceAll("-", "/");
  const pointerAlignment = next && next.percent < 10 ? "start" : next && next.percent > 90 ? "end" : "center";
  return <div className="daily-progress"><div className="daily-progress-heading"><div><h4>{progress.is_today ? "Today’s imaging progress" : "Daily imaging progress"}</h4><p>{dateLabel} · Select a successful marker to inspect its image. Smaller markers show technical replicates.</p></div><div className="daily-progress-legend"><span className="succeeded">Successful</span><span className="failed">Failed</span><span className="missed">Missed</span><span className="pending">Pending</span><span className="remaining">Remaining</span></div></div><ScrollableProgressTimeline points={points} ticks={ticks} next={next} completedWidth={completedWidth} pulseStart={pulseStart} pulseWidth={pulseWidth} pointerAlignment={pointerAlignment} onSelect={setSelected} />{selected && <CaptureImageModal capture={selected} onClose={() => setSelected(null)} />}</div>;
}

function CaptureImageModal({ capture, onClose }) {
  const source = `/api/scheduler/capture-image?scheduled_at=${encodeURIComponent(capture.scheduled_at)}`;
  return <div className="capture-image-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget) onClose(); }}><section className="capture-image-modal" role="dialog" aria-modal="true" aria-labelledby="capture-image-title"><header><div><span>Captured image</span><h3 id="capture-image-title">{capture.time} · Replicate {capture.replicate}</h3></div><button type="button" aria-label="Close captured image" onClick={onClose}>×</button></header><img src={source} alt={`Capture taken at ${capture.time}, replicate ${capture.replicate}`} /></section></div>;
}

export function buildCaptureProgress(progress) {
  const groups = progress.points.map(point => {
    const captures = point.captures?.length
      ? point.captures
      : [{ scheduled_at: point.scheduled_at, time: `${point.time}:00`, replicate: 1, status: point.status, message: point.message }];
    return { ...point, scheduled_at: captures[0].scheduled_at, time: captures[0].time.slice(0, 5), captures };
  });
  const start = new Date(groups[0].scheduled_at).getTime();
  const span = Math.max(new Date(groups.at(-1).scheduled_at).getTime() - start, 1000);
  const withPercent = groups.map(group => ({ ...group, percent: ((new Date(group.scheduled_at).getTime() - start) / span) * 100 }));
  const ticks = buildTimelineTicks(groups[0].time, groups.at(-1).time);
  const nextGroupIndex = withPercent.findIndex(group => group.captures.some(capture => ["pending", "remaining"].includes(capture.status)));
  const nextGroup = nextGroupIndex >= 0 ? withPercent[nextGroupIndex] : null;
  const nextCapture = nextGroup?.captures.find(capture => ["pending", "remaining"].includes(capture.status));
  const next = nextCapture ? { ...nextCapture, percent: nextGroup.percent, stackSize: nextGroup.captures.length } : null;
  const completed = nextGroupIndex < 0 ? withPercent.at(-1) : nextGroupIndex > 0 ? withPercent[nextGroupIndex - 1] : null;
  const completedWidth = completed?.percent ?? 0;
  const pulseStart = completedWidth;
  const pulseWidth = next ? Math.max(next.percent - pulseStart, 0) : 0;
  return { points: withPercent, ticks, next, completedWidth, pulseStart, pulseWidth };
}

function ScrollableProgressTimeline({ points, ticks, next, completedWidth, pulseStart, pulseWidth, pointerAlignment, onSelect }) {
  const scrollRef = useRef(null);
  const trackRef = useRef(null);
  const dense = points.length > 30;
  const mainMarkerSize = points.length <= 10
    ? 20
    : Math.max(15, 20 - (points.length - 10) * .25);
  const replicateMarkerSize = mainMarkerSize * .68;
  const maxStackSize = Math.max(...points.map(point => point.captures.length));
  const replicateStep = Math.min(
    replicateMarkerSize + 7,
    82 / Math.max(maxStackSize - 1, 1),
  );
  const stackHeight = (maxStackSize - 1) * replicateStep;
  useEffect(() => {
    const scroller = scrollRef.current; const track = trackRef.current;
    if (!dense || !next || !scroller || !track) return;
    const target = track.offsetWidth * next.percent / 100 - scroller.clientWidth / 2;
    scroller.scrollLeft = Math.max(0, target);
  }, [dense, next?.scheduled_at]);
  return <><div className={`daily-progress-scroll${dense ? " daily-progress-scroll--dense" : ""}`} style={{ paddingTop: `${64 + stackHeight}px`, "--main-marker-size": `${mainMarkerSize}px`, "--replicate-marker-size": `${replicateMarkerSize}px` }} ref={scrollRef}><div className="daily-progress-track" ref={trackRef} style={{ minWidth: dense ? `${Math.max(points.length * 26, 1050)}px` : undefined }}><div className="daily-progress-axis">{completedWidth > 0 && <span className="daily-progress-complete" style={{ width: `${completedWidth}%` }} />}{pulseWidth > 0 && <span className="daily-progress-pulse" style={{ left: `${pulseStart}%`, width: `${pulseWidth}%` }} />}{next && <span className={`daily-next-pointer daily-next-pointer--${pointerAlignment}`} style={{ left: `${next.percent}%`, bottom: `${14 + (next.stackSize - 1) * replicateStep}px` }}><span><strong>{next.status === "pending" ? "Awaiting result" : next.replicate > 1 ? `Next replicate · ${next.time}` : "Next capture"}</strong><small>{relativeFutureTime(next.scheduled_at)}</small></span><i aria-hidden="true" /></span>}{ticks.map(tick => <span className="daily-progress-tick" style={{ left: `${tick.percent}%` }} key={tick.time} />)}{points.map(point => <span className="daily-progress-cluster" style={{ left: `${point.percent}%` }} key={point.scheduled_at}>{point.captures.map(capture => { const label = capture.replicate > 1 ? `Replicate ${capture.replicate}` : "Time point"; const details = `${label} at ${capture.time}: ${capture.status}.${capture.message ? ` ${capture.message}` : ""}${capture.image_available ? " Select to view image." : ""}`; const className = `daily-progress-point daily-progress-point--${capture.status}${capture.replicate > 1 ? " daily-progress-point--replicate" : ""}${capture.image_available ? " daily-progress-point--viewable" : ""}`; return capture.image_available ? <button type="button" className={className} style={{ top: `${-(capture.replicate - 1) * replicateStep}px` }} title={details} aria-label={details} onClick={() => onSelect(capture)} key={capture.scheduled_at} /> : <span className={className} style={{ top: `${-(capture.replicate - 1) * replicateStep}px` }} title={details} aria-label={details} tabIndex="0" key={capture.scheduled_at} />; })}</span>)}</div><div className="daily-progress-scale">{ticks.map(tick => <span style={{ left: `${tick.percent}%` }} key={tick.time}>{tick.time}</span>)}</div></div></div>{dense && <small className="daily-progress-scroll-hint">Scroll to inspect every time point.</small>}</>;
}

function DailyActivity({ schedule: s }) {
  const activity = s.daily_activity;
  const hours = values => values.map(hour => <div className={`activity-hour${hour.capture_count ? " activity-hour--active" : ""}${hour.intensity_percent >= 45 ? " activity-hour--strong" : ""}`} style={{ "--activity-intensity": 0.08 + hour.intensity_percent / 100 * .92 }} title={`${hour.label}: ${hour.capture_count} planned captures`} key={hour.hour}><span>{String(hour.hour).padStart(2, "0")}</span><strong>{hour.capture_count || "·"}</strong></div>);
  return <section className="dashboard-grid"><section className="card overview-card activity-card"><div className="section-heading"><div><h3>{s.varies_by_day ? "Imaging windows across day blocks" : "Daily imaging window"}</h3><p>{s.varies_by_day ? `Up to ${s.daily_time_points} time points and ${s.daily_captures} planned captures on a scheduled day.` : `${s.daily_time_points} time points and ${s.daily_captures} planned captures per day.`}</p></div></div><div className="activity-summary"><div><span>Imaging window</span><strong>{activity.window_label}</strong><small>{activity.window_duration_label}</small></div><div><span>Cadence</span><strong>{activity.cadence_label}</strong></div><div><span>Peak load</span><strong>{activity.peak_captures_per_hour} captures / hour</strong></div></div><div className="activity-profile-shell" role="img" aria-label="Hourly imaging activity across scheduled days"><div className="activity-period"><span>00–11</span><div className="activity-hours">{hours(activity.hours.slice(0, 12))}</div></div><div className="activity-period"><span>12–23</span><div className="activity-hours">{hours(activity.hours.slice(12))}</div></div></div><div className="activity-legend"><span>No captures</span><i /><span>Peak: {activity.peak_captures_per_hour} captures per hour</span></div><div className="replicate-compact"><div><strong>Technical replicates</strong><p>{s.replicates} capture{s.replicates === 1 ? "" : "s"} per time point, spaced {s.replicate_interval_seconds} seconds apart.</p></div><div className="replicate-burst">{s.replicate_offsets.map(item => <div key={item.number}><strong>{item.number}</strong><span>+{item.offset_seconds}s</span></div>)}</div></div></section></section>;
}
