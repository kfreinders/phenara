import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ErrorNotice, HelpTip, Loading, WorkflowSteps } from "../components";

const numericFields = new Set(["num_days", "replicates", "replicate_interval_seconds", "every_step_minutes", "duration_minutes", "duration_step_minutes", "centered_before_minutes", "centered_after_minutes", "centered_step_minutes"]);
const modeOptions = [
  ["every", "Every n minutes", "Capture from the start time through the end time at a regular interval. The end is included only when it falls exactly on an interval."],
  ["duration", "Fixed duration", "Capture from the start time for the chosen duration at a regular interval. The final boundary is included only when it falls exactly on an interval."],
  ["centered", "Centered window", "Create a window before and after a center time. Captures are stepped from the start of that window, so the center is included only when it falls on an interval."],
];

export function ScheduleBuilderPage({ edit = false }) {
  const navigate = useNavigate(); const [params] = useSearchParams(); const [form, setForm] = useState(null); const [minimum, setMinimum] = useState(""); const [error, setError] = useState(null); const [saving, setSaving] = useState(false);
  useEffect(() => {
    const analysisChoice = params.get("analysis");
    if (!edit && !["0", "1"].includes(analysisChoice)) { navigate("/schedule", { replace: true }); return; }
    api(`/api/schedule/configure?edit=${edit}`).then(data => {
      if (!edit && data.draft_state === "ready") navigate("/schedule/review", { replace: true });
      else {
        const analysis_enabled = ["0", "1"].includes(analysisChoice) ? analysisChoice === "1" : data.form.analysis_enabled;
        setForm({ ...data.form, analysis_enabled }); setMinimum(data.minimum_start_date);
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
  const submit = async event => { event.preventDefault(); setError(null); if (minimum && form.start_date < minimum) { setError(new Error("Start date cannot be in the past.")); return; } setSaving(true); try { await api("/api/schedule/draft", { method: "POST", body: JSON.stringify(form) }); navigate("/camera?workflow=schedule"); } catch (reason) { setError(reason); } finally { setSaving(false); } };
  return <><WorkflowSteps current={2} analysisEnabled={form?.analysis_enabled} /><section className="card"><div className="card-header"><div><h2>Schedule builder</h2><p>Step 2: configure when Phenopi should capture images.</p></div><Link className="button-link secondary" to={edit ? "/schedule/edit" : "/schedule"}><span aria-hidden="true">←</span> Back to capture mode</Link></div><ErrorNotice error={error} />{form && <form className="schedule-form" onSubmit={submit}>
    <fieldset><legend>Experiment</legend><div className="grid experiment-details"><TextField label="Experiment name" name="experiment_name" value={form.experiment_name} onChange={update} required maxLength={80} /><TextField label="Researcher" optional name="researcher" value={form.researcher ?? ""} onChange={update} maxLength={80} /></div><label><span className="field-label">Notes <span className="optional">Optional</span></span><textarea name="notes" maxLength="1000" rows="3" value={form.notes ?? ""} onChange={update} /></label>
      <div className="grid schedule-timing-fields"><DateField label="Start date" name="start_date" value={form.start_date} minimum={minimum} onChange={update} /><Field label="Number of days" type="number" name="num_days" value={form.num_days} min="1" max="365" onChange={update} /><Field label="Replicates" type="number" name="replicates" value={form.replicates} min="1" max="100" onChange={update} /><label className={`replicate-interval-control${form.replicates <= 1 ? " is-inactive" : ""}`}>Replicate interval (s)<input type="number" name="replicate_interval_seconds" min="0" max="86400" value={form.replicate_interval_seconds} readOnly={form.replicates <= 1} aria-disabled={form.replicates <= 1} onChange={update} required /></label></div></fieldset>
    <fieldset><legend>Schedule mode</legend><div className="radio-row">{modeOptions.map(([value, label, help]) => <div className="mode-option" key={value}><label><input type="radio" name="mode" value={value} checked={form.mode === value} onChange={update} /> {label}</label><HelpTip label={`${label} mode`} id={`mode-help-${value}`}>{help}</HelpTip></div>)}</div>
      {form.mode === "every" && <div className="grid schedule-mode-fields"><TimeField label="Start time" name="every_start" value={form.every_start} onChange={update} /><TimeField label="End time" name="every_end" value={form.every_end} onChange={update} /><Field label="Step minutes" type="number" name="every_step_minutes" value={form.every_step_minutes} min="1" max="1440" onChange={update} /></div>}
      {form.mode === "duration" && <div className="grid schedule-mode-fields"><TimeField label="Start time" name="duration_start" value={form.duration_start} onChange={update} /><Field label="Duration minutes" type="number" name="duration_minutes" value={form.duration_minutes} min="0" max="1439" onChange={update} /><Field label="Step minutes" type="number" name="duration_step_minutes" value={form.duration_step_minutes} min="1" max="1440" onChange={update} /></div>}
      {form.mode === "centered" && <div className="grid schedule-mode-fields"><TimeField label="Center time" name="centered_center" value={form.centered_center} onChange={update} /><Field label="Before minutes" type="number" name="centered_before_minutes" value={form.centered_before_minutes} min="0" max="1439" onChange={update} /><Field label="After minutes" type="number" name="centered_after_minutes" value={form.centered_after_minutes} min="0" max="1439" onChange={update} /><Field label="Step minutes" type="number" name="centered_step_minutes" value={form.centered_step_minutes} min="1" max="1440" onChange={update} /></div>}
      <ScheduleWindowPreview form={form} />
    </fieldset>
    <div className="actions"><button type="submit" disabled={saving}>{saving ? "Saving experiment…" : "Continue to camera alignment"}</button></div>
  </form>}</section></>;
}

function ScheduleWindowPreview({ form }) {
  const preview = buildModePreview(form);
  if (!preview.valid) return <section className="schedule-window-preview schedule-window-preview--invalid" aria-live="polite"><strong>Daily time window</strong><p>{preview.message}</p></section>;
  const left = preview.start / 14.4;
  const width = (preview.end - preview.start) / 14.4;
  return <section className="schedule-window-preview" aria-label={preview.summary} aria-live="polite">
    <header><div><strong>Daily time window</strong><p>{preview.summary}</p></div><span>{preview.captureCount} time point{preview.captureCount === 1 ? "" : "s"}</span></header>
    <div className="schedule-window-shell">
      <div className="schedule-window-axis">
        <span className="schedule-window-selection" style={{ left: `${left}%`, width: `${width}%` }} />
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
  let start; let end; let step; let center = null;
  if (form.mode === "every") {
    start = parseClock(form.every_start); end = parseClock(form.every_end); step = Number(form.every_step_minutes);
  } else if (form.mode === "duration") {
    start = parseClock(form.duration_start); end = start === null ? null : start + Number(form.duration_minutes); step = Number(form.duration_step_minutes);
  } else if (form.mode === "centered") {
    center = parseClock(form.centered_center);
    start = center === null ? null : center - Number(form.centered_before_minutes);
    end = center === null ? null : center + Number(form.centered_after_minutes);
    step = Number(form.centered_step_minutes);
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
  return { valid: true, start, end, step, center, captureCount, points, summary: `${formatClock(start)}–${formatClock(end)} · every ${interval}` };
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
