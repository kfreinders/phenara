import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice, HelpTip, Loading, WorkflowSteps } from "../components";

const numericFields = new Set(["num_days", "replicates", "replicate_interval_seconds", "every_step_minutes", "duration_minutes", "duration_step_minutes", "centered_before_minutes", "centered_after_minutes", "centered_step_minutes"]);
const modeOptions = [
  ["every", "Every n minutes", "Capture from the start time through the end time at a regular interval. The end is included only when it falls exactly on an interval."],
  ["duration", "Fixed duration", "Capture from the start time for the chosen duration at a regular interval. The final boundary is included only when it falls exactly on an interval."],
  ["centered", "Centered window", "Create a window before and after a center time. Captures are stepped from the start of that window, so the center is included only when it falls on an interval."],
  ["custom", "Custom", "Combine windows with different capture intervals. Use the same start and end time to add a single capture."],
];
const scheduleDefaults = {
  mode: "every",
  experiment_name: "",
  researcher: "",
  notes: "",
  analysis_enabled: false,
  num_days: 14,
  replicates: 1,
  replicate_interval_seconds: 0,
  every_start: "08:00",
  every_end: "19:30",
  every_step_minutes: 30,
  duration_start: "08:00",
  duration_minutes: 720,
  duration_step_minutes: 30,
  centered_center: "12:00",
  centered_before_minutes: 120,
  centered_after_minutes: 120,
  centered_step_minutes: 30,
  custom_windows: [
    { start: "08:00", end: "10:00", step_minutes: 30 },
    { start: "16:00", end: "19:00", step_minutes: 60 },
  ],
};

export function ScheduleBuilderPage({ edit = false }) {
  const navigate = useNavigate(); const [params] = useSearchParams(); const [form, setForm] = useState(null); const [defaults, setDefaults] = useState(null); const [minimum, setMinimum] = useState(""); const [error, setError] = useState(null); const [saving, setSaving] = useState(false);
  useEffect(() => {
    const analysisChoice = params.get("analysis");
    if (!edit && !["0", "1"].includes(analysisChoice)) { navigate("/schedule", { replace: true }); return; }
    api(`/api/schedule/configure?edit=${edit}`).then(data => {
      if (!edit && data.draft_state === "ready") navigate("/schedule/review", { replace: true });
      else {
        const analysis_enabled = ["0", "1"].includes(analysisChoice) ? analysisChoice === "1" : data.form.analysis_enabled;
        setForm({ ...data.form, analysis_enabled });
        setDefaults({
          ...scheduleDefaults,
          ...data.defaults,
          analysis_enabled,
          start_date: data.minimum_start_date,
        });
        setMinimum(data.minimum_start_date);
      }
    }).catch(setError);
  }, [edit, navigate, params]);
  if (!form && !error) return <Loading label="Loading schedule builder" />;
  const update = event => {
    const { name, value } = event.target; let next = numericFields.has(name) ? Number(value) : value;
    setForm(current => {
      const changed = { ...current, [name]: next };
      if (name === "replicates") changed.replicate_interval_seconds = next > 1 ? (current.replicate_interval_seconds || 30) : 0;
      return changed;
    });
  };
  const resetDefaults = () => {
    setForm(current => resetScheduleForm(current, defaults, minimum));
    setError(null);
  };
  const updateCustomWindow = (index, field, value) => {
    setForm(current => ({
      ...current,
      custom_windows: current.custom_windows.map((window, windowIndex) => (
        windowIndex === index
          ? { ...window, [field]: field === "step_minutes" ? Number(value) : value }
          : window
      )),
    }));
  };
  const addCustomWindow = () => {
    setForm(current => {
      const previous = current.custom_windows.at(-1);
      const nextStart = previous?.end ?? "12:00";
      return {
        ...current,
        custom_windows: [
          ...current.custom_windows,
          { start: nextStart, end: nextStart, step_minutes: previous?.step_minutes ?? 30 },
        ],
      };
    });
  };
  const removeCustomWindow = index => {
    setForm(current => ({
      ...current,
      custom_windows: current.custom_windows.filter((_, windowIndex) => windowIndex !== index),
    }));
  };
  const submit = async event => { event.preventDefault(); setError(null); if (minimum && form.start_date < minimum) { setError(new Error("Start date cannot be in the past.")); return; } setSaving(true); try { await api("/api/schedule/draft", { method: "POST", body: JSON.stringify(form) }); navigate("/camera?workflow=schedule"); } catch (reason) { setError(reason); } finally { setSaving(false); } };
  return <><WorkflowSteps current={2} analysisEnabled={form?.analysis_enabled} /><section className="card schedule-builder-card"><div className="card-header"><div><h2>Schedule builder</h2><p>Step 2: configure when Phenopi should capture images.</p></div><div className="schedule-builder-header-actions"><button className="secondary" type="button" disabled={!defaults || JSON.stringify(form) === JSON.stringify(defaults)} onClick={resetDefaults}>Reset defaults</button><Link className="button-link secondary" to={edit ? "/schedule/edit" : "/schedule"}><span aria-hidden="true">←</span> Back to capture mode</Link></div></div><ErrorNotice error={error} />{form && <form className="schedule-form" onSubmit={submit}>
    <fieldset><legend>Experiment</legend><div className="grid experiment-details"><TextField label="Experiment name" name="experiment_name" value={form.experiment_name} onChange={update} required maxLength={80} /><TextField label="Researcher" optional name="researcher" value={form.researcher ?? ""} onChange={update} maxLength={80} /></div><label><span className="field-label">Notes <span className="optional">Optional</span></span><textarea name="notes" maxLength="1000" rows="3" value={form.notes ?? ""} onChange={update} /></label>
      <div className="grid schedule-timing-fields"><DateField label="Start date" name="start_date" value={form.start_date} minimum={minimum} onChange={update} /><Field label="Number of days" type="number" name="num_days" value={form.num_days} min="1" max="365" onChange={update} /><Field label="Replicates" type="number" name="replicates" value={form.replicates} min="1" max="100" onChange={update} /><label className={`replicate-interval-control${form.replicates <= 1 ? " is-inactive" : ""}`}>Replicate interval (s)<input type="number" name="replicate_interval_seconds" min="0" max="86400" value={form.replicate_interval_seconds} readOnly={form.replicates <= 1} aria-disabled={form.replicates <= 1} onChange={update} required /></label></div></fieldset>
    <fieldset><legend>Schedule mode</legend><div className="schedule-mode-options">{modeOptions.map(([value, label, help]) => <div className={`mode-option${form.mode === value ? " is-selected" : ""}`} key={value}><label><input type="radio" name="mode" value={value} checked={form.mode === value} onChange={update} /><ScheduleModeIcon mode={value} /><span><strong>{label}</strong><small>{modeDescription(value)}</small></span></label><HelpTip label={`${label} mode`} id={`mode-help-${value}`}>{help}</HelpTip></div>)}</div>
      {form.mode === "every" && <div className="grid schedule-mode-fields"><TimeField label="Start time" name="every_start" value={form.every_start} onChange={update} /><TimeField label="End time" name="every_end" value={form.every_end} onChange={update} /><Field label="Step minutes" type="number" name="every_step_minutes" value={form.every_step_minutes} min="1" max="1440" onChange={update} /></div>}
      {form.mode === "duration" && <div className="grid schedule-mode-fields"><TimeField label="Start time" name="duration_start" value={form.duration_start} onChange={update} /><Field label="Duration minutes" type="number" name="duration_minutes" value={form.duration_minutes} min="0" max="1439" onChange={update} /><Field label="Step minutes" type="number" name="duration_step_minutes" value={form.duration_step_minutes} min="1" max="1440" onChange={update} /></div>}
      {form.mode === "centered" && <div className="grid schedule-mode-fields"><TimeField label="Center time" name="centered_center" value={form.centered_center} onChange={update} /><Field label="Before minutes" type="number" name="centered_before_minutes" value={form.centered_before_minutes} min="0" max="1439" onChange={update} /><Field label="After minutes" type="number" name="centered_after_minutes" value={form.centered_after_minutes} min="0" max="1439" onChange={update} /><Field label="Step minutes" type="number" name="centered_step_minutes" value={form.centered_step_minutes} min="1" max="1440" onChange={update} /></div>}
      {form.mode === "custom" && <CustomScheduleEditor windows={form.custom_windows ?? []} onChange={updateCustomWindow} onAdd={addCustomWindow} onRemove={removeCustomWindow} />}
      <ScheduleWindowPreview form={form} />
    </fieldset>
    <div className="actions"><button type="submit" disabled={saving}>{saving ? "Saving experiment…" : "Continue to camera alignment"}</button></div>
  </form>}</section></>;
}

export function resetScheduleForm(current, defaults, currentDate = "") {
  if (!defaults) return current;
  return {
    ...current,
    ...scheduleDefaults,
    ...defaults,
    analysis_enabled: current.analysis_enabled,
    start_date: currentDate || defaults.start_date || current.start_date,
  };
}

function ScheduleWindowPreview({ form }) {
  const preview = buildModePreview(form);
  if (!preview.valid) return <section className="schedule-window-preview schedule-window-preview--invalid" aria-live="polite"><strong>Daily time window</strong><p>{preview.message}</p></section>;
  const left = preview.start / 14.4;
  return <section className="schedule-window-preview" aria-label={preview.summary} aria-live="polite">
    <header><div><strong>Daily time window</strong><p>{preview.summary}</p></div><span>{preview.captureCount} time point{preview.captureCount === 1 ? "" : "s"}</span></header>
    <div className="schedule-window-shell">
      <div className="schedule-window-axis">
        {preview.ranges.map((range, index) => <span className="schedule-window-selection" style={{ left: `${range.start / 14.4}%`, width: `${(range.end - range.start) / 14.4}%` }} key={index} />)}
        {preview.points.map((minute, index) => <i className="schedule-window-capture" style={{ left: `${minute / 14.4}%` }} title={`Capture at ${formatClock(minute)}`} key={index} />)}
        {preview.center !== null && <i className="schedule-window-center" style={{ left: `${preview.center / 14.4}%` }} title={`Center time ${formatClock(preview.center)}`} />}
        <span className="schedule-window-boundary schedule-window-boundary--start" style={{ left: `${left}%` }}>{formatClock(preview.start)}</span>
        {preview.end !== preview.start && <span className="schedule-window-boundary schedule-window-boundary--end" style={{ left: `${preview.end / 14.4}%` }}>{formatClock(preview.end)}</span>}
      </div>
      <div className="schedule-window-scale" aria-hidden="true">{[0, 360, 720, 1080, 1440].map(minute => <span style={{ left: `${minute / 14.4}%` }} key={minute}>{formatClock(minute)}</span>)}</div>
    </div>
  </section>;
}

export function buildModePreview(form, markerLimit = 40) {
  let start; let end; let step; let center = null; let ranges = [];
  if (form.mode === "every") {
    start = parseClock(form.every_start); end = parseClock(form.every_end); step = Number(form.every_step_minutes);
  } else if (form.mode === "duration") {
    start = parseClock(form.duration_start); end = start === null ? null : start + Number(form.duration_minutes); step = Number(form.duration_step_minutes);
  } else if (form.mode === "centered") {
    center = parseClock(form.centered_center);
    start = center === null ? null : center - Number(form.centered_before_minutes);
    end = center === null ? null : center + Number(form.centered_after_minutes);
    step = Number(form.centered_step_minutes);
  } else if (form.mode === "custom") {
    const custom = buildCustomSchedule(form.custom_windows);
    if (!custom.valid) return custom;
    const indexes = custom.points.length <= markerLimit
      ? Array.from({ length: custom.points.length }, (_, index) => index)
      : Array.from({ length: markerLimit }, (_, index) => Math.round(index * (custom.points.length - 1) / (markerLimit - 1)));
    return {
      ...custom,
      captureCount: custom.points.length,
      points: indexes.map(index => custom.points[index]),
      center,
      summary: `${custom.points.length} unique time point${custom.points.length === 1 ? "" : "s"} across ${custom.ranges.length} window${custom.ranges.length === 1 ? "" : "s"}`,
    };
  } else {
    return { valid: false, message: "Select a schedule mode to preview its daily window." };
  }
  if (start === null || end === null || !Number.isFinite(step) || step <= 0) return { valid: false, message: "Enter a valid time and an interval greater than zero to preview the window." };
  if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end > 1439) return { valid: false, message: "The selected time window must stay within a single day." };
  if (end < start) return { valid: false, message: "The end time must not be earlier than the start time." };
  const captureCount = Math.floor((end - start) / step) + 1;
  const indexes = captureCount <= markerLimit ? Array.from({ length: captureCount }, (_, index) => index) : Array.from({ length: markerLimit }, (_, index) => Math.round(index * (captureCount - 1) / (markerLimit - 1)));
  const points = indexes.map(index => start + index * step);
  const interval = `${step} minute${step === 1 ? "" : "s"}`;
  ranges = [{ start, end }];
  return { valid: true, start, end, step, center, captureCount, points, ranges, summary: `${formatClock(start)}–${formatClock(end)} · every ${interval}` };
}

export function buildCustomSchedule(windows) {
  if (!Array.isArray(windows) || windows.length === 0) return { valid: false, message: "Add at least one capture window." };
  const pointSet = new Set();
  const ranges = [];
  for (let index = 0; index < windows.length; index += 1) {
    const window = windows[index];
    const start = parseClock(window.start);
    const end = parseClock(window.end);
    const step = Number(window.step_minutes);
    if (start === null || end === null || !Number.isFinite(step) || step <= 0) return { valid: false, message: `Complete window ${index + 1} with valid times and an interval greater than zero.` };
    if (end < start) return { valid: false, message: `Window ${index + 1} ends before it starts.` };
    ranges.push({ start, end });
    for (let minute = start; minute <= end; minute += step) pointSet.add(minute);
  }
  const points = [...pointSet].sort((left, right) => left - right);
  return { valid: true, start: points[0], end: points.at(-1), points, ranges };
}

function CustomScheduleEditor({ windows, onChange, onAdd, onRemove }) {
  return <section className="custom-schedule-editor">
    <header><div><strong>Capture windows</strong><p>Combine intervals or add a single time point. Overlapping captures are included once.</p></div><button className="secondary custom-window-add" type="button" onClick={onAdd}><span aria-hidden="true">＋</span> Add window</button></header>
    <div className="custom-window-list">
      {windows.map((window, index) => <article className="custom-window" key={index}>
        <div className="custom-window-number"><span>{index + 1}</span><strong>Window {index + 1}</strong></div>
        <TimeField label="Start time" name={`custom_start_${index}`} value={window.start} onChange={event => onChange(index, "start", event.target.value)} />
        <TimeField label="End time" name={`custom_end_${index}`} value={window.end} onChange={event => onChange(index, "end", event.target.value)} />
        <Field label="Every (minutes)" type="number" name={`custom_step_${index}`} value={window.step_minutes} min="1" max="1440" onChange={event => onChange(index, "step_minutes", event.target.value)} />
        <button className="custom-window-remove" type="button" aria-label={`Remove window ${index + 1}`} disabled={windows.length === 1} onClick={() => onRemove(index)}>×</button>
      </article>)}
    </div>
  </section>;
}

function modeDescription(mode) {
  return {
    every: "One regular daily interval",
    duration: "Start time plus a duration",
    centered: "Around a central event",
    custom: "Several intervals or time points",
  }[mode];
}

function ScheduleModeIcon({ mode }) {
  if (mode === "every") return <svg className="schedule-mode-icon" viewBox="0 0 48 48" aria-hidden="true"><circle cx="24" cy="24" r="17" /><path d="M24 14v10l7 5" /><circle className="schedule-mode-icon-dot" cx="12" cy="24" r="2" /><circle className="schedule-mode-icon-dot" cx="24" cy="7" r="2" /><circle className="schedule-mode-icon-dot" cx="36" cy="24" r="2" /></svg>;
  if (mode === "duration") return <svg className="schedule-mode-icon" viewBox="0 0 48 48" aria-hidden="true"><path d="M17 8h14M24 8v5M34 15l3-3" /><circle cx="24" cy="28" r="14" /><path d="M24 19v9h8" /><path className="schedule-mode-icon-accent" d="M14 37a14 14 0 0 0 20 0" /></svg>;
  if (mode === "centered") return <svg className="schedule-mode-icon" viewBox="0 0 48 48" aria-hidden="true"><path d="M6 24h36" /><circle className="schedule-mode-icon-dot" cx="10" cy="24" r="2.5" /><circle className="schedule-mode-icon-dot" cx="17" cy="24" r="2.5" /><circle className="schedule-mode-icon-dot" cx="31" cy="24" r="2.5" /><circle className="schedule-mode-icon-dot" cx="38" cy="24" r="2.5" /><path className="schedule-mode-icon-accent" d="m24 15 9 9-9 9-9-9Z" /></svg>;
  return <svg className="schedule-mode-icon" viewBox="0 0 48 48" aria-hidden="true"><path d="M7 14h15M27 14h14M7 34h9M21 34h20" /><circle className="schedule-mode-icon-dot" cx="10" cy="14" r="3" /><circle className="schedule-mode-icon-dot" cx="18" cy="14" r="3" /><circle className="schedule-mode-icon-dot" cx="30" cy="14" r="3" /><circle className="schedule-mode-icon-dot" cx="38" cy="14" r="3" /><circle className="schedule-mode-icon-dot" cx="10" cy="34" r="3" /><circle className="schedule-mode-icon-dot" cx="24" cy="34" r="3" /><circle className="schedule-mode-icon-dot" cx="38" cy="34" r="3" /><path className="schedule-mode-icon-accent" d="M24 8v12M18 28v12" /></svg>;
}

function parseClock(value) {
  const match = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(value ?? "");
  return match ? Number(match[1]) * 60 + Number(match[2]) : null;
}

function formatClock(minutes) {
  const hours = Math.floor(minutes / 60);
  return `${String(hours).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
}

function DateField({ label, name, value, minimum, onChange }) {
  const picker = useRef(null);
  const [year = "", month = "", day = ""] = String(value ?? "").split("-");
  const changePart = (index, part) => {
    const parts = [year, month, day];
    parts[index] = part.replace(/\D/g, "").slice(0, index === 0 ? 4 : 2);
    onChange({ target: { name, value: parts.join("-") } });
  };
  const normalizePart = (index, part) => {
    if (!part) return;
    const width = index === 0 ? 4 : 2;
    changePart(index, part.padStart(width, "0"));
  };
  const openPicker = () => {
    if (typeof picker.current?.showPicker === "function") picker.current.showPicker();
    else picker.current?.click();
  };
  const pickerValue = /^\d{4}-\d{2}-\d{2}$/.test(value ?? "") ? value : "";
  return <div className="fixed-format-field">
    <span className="fixed-format-label" id={`${name}-label`}>{label} <small>YYYY-MM-DD</small></span>
    <div className="fixed-date-control">
      <div className="fixed-format-input" role="group" aria-labelledby={`${name}-label`}>
        <input value={year} inputMode="numeric" maxLength="4" pattern="\d{4}" aria-label="Year" placeholder="YYYY" onChange={event => changePart(0, event.target.value)} onBlur={event => normalizePart(0, event.target.value)} required />
        <span aria-hidden="true">-</span>
        <input value={month} inputMode="numeric" maxLength="2" pattern="(?:0[1-9]|1[0-2])" aria-label="Month" placeholder="MM" onChange={event => changePart(1, event.target.value)} onBlur={event => normalizePart(1, event.target.value)} required />
        <span aria-hidden="true">-</span>
        <input value={day} inputMode="numeric" maxLength="2" pattern="(?:0[1-9]|[12]\d|3[01])" aria-label="Day" placeholder="DD" onChange={event => changePart(2, event.target.value)} onBlur={event => normalizePart(2, event.target.value)} required />
      </div>
      <button className="date-picker-button" type="button" aria-label="Open graphical date picker" onClick={openPicker}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M7 3v4m10-4v4M3 10h18" /></svg></button>
      <input className="native-date-picker" ref={picker} type="date" value={pickerValue} min={minimum} tabIndex="-1" aria-hidden="true" onChange={event => onChange({ target: { name, value: event.target.value } })} />
    </div>
  </div>;
}

function TimeField({ label, name, value, onChange }) {
  const [hours = "", minutes = ""] = String(value ?? "").split(":");
  const emit = next => onChange({ target: { name, value: next } });
  const changePart = (index, part) => {
    const parts = [hours, minutes];
    parts[index] = part.replace(/\D/g, "").slice(0, 2);
    emit(parts.join(":"));
  };
  const normalizePart = (index, part) => {
    if (part) changePart(index, part.padStart(2, "0"));
  };
  const adjust = amount => {
    const parsed = parseClock(value);
    emit(formatClock(Math.max(0, Math.min(1439, (parsed ?? 0) + amount))));
  };
  return <div className="fixed-format-field">
    <span className="fixed-format-label" id={`${name}-label`}>{label} <small>HH:MM</small></span>
    <div className="fixed-time-control">
      <div className="fixed-format-input fixed-time-input" role="group" aria-labelledby={`${name}-label`}>
        <input value={hours} inputMode="numeric" maxLength="2" pattern="(?:[01]\d|2[0-3])" aria-label={`${label} hours`} placeholder="HH" onChange={event => changePart(0, event.target.value)} onBlur={event => normalizePart(0, event.target.value)} required />
        <span aria-hidden="true">:</span>
        <input value={minutes} inputMode="numeric" maxLength="2" pattern="[0-5]\d" aria-label={`${label} minutes`} placeholder="MM" onChange={event => changePart(1, event.target.value)} onBlur={event => normalizePart(1, event.target.value)} required />
      </div>
      <span className="time-step-buttons">
        <button type="button" aria-label={`Increase ${label.toLowerCase()} by one minute`} onClick={() => adjust(1)}>▲</button>
        <button type="button" aria-label={`Decrease ${label.toLowerCase()} by one minute`} onClick={() => adjust(-1)}>▼</button>
      </span>
    </div>
  </div>;
}

function Field({ label, ...props }) { return <label>{label}<input {...props} required /></label>; }
function TextField({ label, optional, ...props }) { return <label><span className="field-label">{label} {optional && <span className="optional">Optional</span>}</span><input type="text" {...props} /></label>; }
